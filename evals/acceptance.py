#!/usr/bin/env python3
"""Does an agent use the memory when nobody reminds it? Ask the agent.

    python3 evals/acceptance.py --pointer include --agent \'claude
        --setting-sources project --no-session-persistence
        --allowedTools "Bash(lore:*)" "Bash(cat:*)" Read -p {prompt}\'
    python3 evals/acceptance.py --pointer paste --agent \'codex exec -C {project}
        --skip-git-repo-check --ephemeral --ignore-user-config --ignore-rules
        -s workspace-write {prompt}\'

Nothing in this program fires on its own — no hook, and since 0.4.0 no skill
manifest for a harness to index either. The only thing that makes an agent search
before answering is the instruction block, reaching it through whatever import
syntax its harness has. Whether that fires is not something the code can
guarantee, so it is measured here: superpowers\' porting guide reaches the same
conclusion and makes a real-session acceptance run the one proof.

What it does: writes the evaluation corpus out as a real store inside a throwaway
project, connects the memory the way `--pointer` says, runs the agent command once
with a question only the store can answer, and reads the store\'s log. PASS means
at least one search event landed before the agent answered.

`--pointer` chooses how the memory reaches the agent:

  none      nothing at all. Before 0.4.0 this arm still carried the skill
            directory, so it measured whether a harness\'s skill index was enough
            on its own; it measured 0/15. Now it is a true control — the agent is
            told nothing — and it is kept because a control that cannot pass is
            what makes the other arms mean something.
  paste     the block transcribed into the project\'s CLAUDE.md and AGENTS.md,
            what a user does on a harness with no import syntax
  include   a one-line `@path` import of the rendered block, what `lore init`
            writes on Claude Code and Gemini
  mcp       no instruction block: the memory reached as MCP tools, whose names
            and descriptions the harness puts in front of the model by itself.
            Pass the agent an `--mcp-config {project}/.mcp.json`, and note that
            Claude Code defers MCP tools behind its tool search unless
            ENABLE_TOOL_SEARCH=false is set — measure the tool list, not the
            assumption.

The agent needs `lore` on PATH; this refuses to run without it, because an agent
that wants to search and cannot is scored the same as one that never tried.
`PAGELORE_BIN` overrides which `lore` runs — an editable install in this tree is
the right target, and a stale `lore` a PATH can already own must not be the one
measured.

`{prompt}`, `{project}` and `{repo}` are substituted into the agent command.
The command is split with shlex, so quote as you would in a shell.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "src"))

import run as harness  # noqa: E402

from pagelore import instructions  # noqa: E402

# A prose query from the corpus whose answer is in exactly one page and nowhere
# else: the project is fictional, so nothing but the store can answer it.
QUESTION = ("This project's terminal does not use the graphics card to draw by default. "
            "Why was that decided? Answer in two sentences.")
RELEVANT = "render-canvas-default-renderer"


def build_project(directory: Path, pointer: str) -> Path:
    project = directory / "project"
    project.mkdir()
    (project / "src").mkdir()
    (project / "src" / "main.ts").write_text("export {}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    harness.materialise(harness.load_corpus()["pages"], project)

    block = instructions.render()
    if pointer == "paste":
        (project / "CLAUDE.md").write_text(block, encoding="utf-8")
        (project / "AGENTS.md").write_text(block, encoding="utf-8")
    elif pointer in ("include", "mcp+include"):
        # An absolute path, because the block under test is this working tree's
        # rather than an installed one; a user gets the ~/ form from `lore init`.
        target = project / "AGENT.md"
        target.write_text(block, encoding="utf-8")
        (project / "CLAUDE.md").write_text(f"@{target}\n", encoding="utf-8")
    if pointer in ("mcp", "mcp+include"):
        # Nothing tells the model the memory exists except the tool list, which
        # is the whole point of the comparison.
        (project / ".mcp.json").write_text(json.dumps({"mcpServers": {"pagelore": {
            "type": "stdio", "command": sys.executable,
            "args": [str(HERE / "mcp_probe.py")],
            "env": {"PAGELORE_DIR": str(project / ".memory")},
        }}}, indent=2), encoding="utf-8")
    return project


def log_events(store: Path) -> list[dict]:
    log = store / ".log.jsonl"
    if not log.exists():
        return []
    out = []
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--agent", required=True,
                    help="agent command with {prompt}, {project} and {repo} placeholders")
    ap.add_argument("--pointer", choices=("none", "paste", "include", "mcp", "mcp+include"), default="none",
                    help="how the memory reaches the agent (default: none)")
    ap.add_argument("--question", default=QUESTION)
    ap.add_argument("--keep", action="store_true", help="leave the project on disk")
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args(argv)

    command = os.environ.get("PAGELORE_BIN") or shutil.which("lore") or shutil.which("pagelore")
    if command is None:
        print("FIX: no `lore` on PATH. `pipx install -e .` or `pip install -e .` first — "
              "an agent that tries to search and cannot scores the same as one that "
              "never tried, and the run would be meaningless.", file=sys.stderr)
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="pm-acceptance-"))
    project = build_project(tmp, args.pointer)
    store = project / ".memory"
    before = len(log_events(store))

    cmd = [part.format(prompt=args.question, project=str(project), repo=str(REPO))
           for part in shlex.split(args.agent)]
    # A clean child: launched from inside an agent session, the session id and
    # nesting markers of the parent must not leak into the run being measured.
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("CLAUDE_CODE_") or k == "CLAUDECODE")}
    started = time.perf_counter()
    proc = subprocess.run(cmd, cwd=project, capture_output=True, text=True,
                          timeout=args.timeout, env=env)
    elapsed = time.perf_counter() - started

    events = log_events(store)[before:]
    searches = [e for e in events if e.get("event") == "search"]
    writes = [e for e in events if e.get("event") == "write"]
    answer = proc.stdout.strip()
    mentions = RELEVANT.split("-")[1] in answer.lower()  # "canvas"

    print(f"agent      {' '.join(cmd[:2])}  (exit {proc.returncode}, {elapsed:.0f}s)")
    print(f"project    {project}  pointer={args.pointer}")
    print(f"command    {command}")
    print(f"searches   {len(searches)}" + (f"   first: {searches[0].get('query')!r}"
                                           if searches else ""))
    print(f"writes     {len(writes)}")
    print(f"answer     {answer[:300]!r}")
    verdict = "PASS" if searches else "FAIL"
    print(f"\n{verdict}: the agent {'searched the store before answering' if searches else 'answered without searching the store'}"
          + ("" if not searches else f"; answer {'names' if mentions else 'does not name'} the canvas decision"))
    if proc.returncode != 0:
        print(f"\nstderr:\n{proc.stderr[-2000:]}", file=sys.stderr)
    if not args.keep:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if searches else 1


if __name__ == "__main__":
    raise SystemExit(main())
