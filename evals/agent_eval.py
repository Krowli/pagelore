#!/usr/bin/env python3
"""How does a real Claude Code agent use the memory, behaviour by behaviour?

    python3 evals/agent_eval.py --label baseline                  # 2 arms × 6 tasks × 10 runs
    python3 evals/agent_eval.py --models claude-opus-5-5,claude-sonnet-5 --label baseline
    python3 evals/agent_eval.py --arms mcp --tasks C --runs 3 --label try
    python3 evals/agent_eval.py --dry-run --tasks C               # build, print, run nothing
    python3 evals/agent_eval.py --summarize evals/results/a.jsonl [evals/results/b.jsonl]

`evals/acceptance.py` answers one yes/no — did at least one search land — for one
session, and keeps nothing. Real logs show more than that question can see: agents
re-asking the store the same thing in reworded queries (the same top page three to
five times), `--touching` never used, pages not written after a fix. An instruction
change aimed at one of those has to be accepted or rejected on a number for that
behaviour, so this runs a fixed set of tasks many times and keeps every session.

The protocol
------------
Each session gets a fresh throwaway project built by `acceptance.build_project`:
the evaluation corpus written out as a real store, plus the files its task needs.
The memory reaches the agent one of two ways (`--arms`):

  include   the project's CLAUDE.md holds `@<absolute path to the rendered block>`,
            what `lore init` writes; run with an empty strict MCP config
  mcp       no instruction file; a `.mcp.json` with a server named `pagelore`
            (this tree's `lore mcp`), passed as the strict MCP config

`--strict-mcp-config` is on in both, always: without it Claude Code loads the
user's claude.ai connectors (mail, drive, …) into the session, which pollutes the
measurement and shows an eval agent the user's mail.

The agent is `claude -p` with stream-json output, no session persistence, project
settings only, and `Bash(lore:*) Read Edit Write Grep Glob` (plus the two MCP tools
in the mcp arm). `lore` on its PATH is a shim to this working tree —
`PAGELORE_BIN` overrides what the shim runs — and the run refuses to start unless
`lore --version` names this tree's version and directory, because a stale `lore`
measured is a different program measured. The child env drops the parent session's
`CLAUDE_CODE_*` / `CLAUDECODE` markers and every `PAGELORE_*` override, and points
`PAGELORE_HOME` at a directory that does not exist, so a session never refreshes
the user's `~/.pagelore`.

`--models` runs every cell once per model (`claude --model …`); without it none is
passed and the CLI default runs. Each session records the model it asked for and
the one the init event reports, and the summary groups by the latter.

Sessions run one at a time — runs outer, then tasks, models, arms, so the cells
being compared are close in time — each in its own process group, killed whole on
`--timeout` so the MCP server does not linger. Each is appended to `--out` as one
JSON line the moment it ends, after one header line describing the run; a crash
keeps what was done. An existing `--out` is refused unless `--append` is given. Per session: the init event (model, Claude Code version, MCP servers, counts
of skills / plugins / agents — local runs happen inside the user's own Claude Code
environment, so comparisons must be paired in the same one), every tool call in
order, the result event, the store's log, and the metrics below. The tasks are
`evals/agent_tasks.json`.

Metrics
-------
  searched              the store logged at least one search
  n_searches            searches logged
  repeats               searches whose top hit was the top hit of an earlier one
  used_touching         some search passed `--touching` / `touching`
  searched_before_edit  the first search call came before the first Edit/Write that
                        landed on a file outside the store; None when nothing did
  grep_memory           scanned `.memory` around the command: a Grep/Glob into it or
                        over the whole project (no path, `.`, the root), or a shell
                        grep -r / find / git grep / cd .memory that reaches it
  read_memory_file      opened a page file directly (Read, or cat/head/sed in Bash)
                        — the MCP arm has no `show`, so this is how it reads a hit
  wrote_page            the store logged a write
  correct               per task: `answer_any` matched, or for an unanswerable task
                        the answer abstained (`abstain_any`); None when ungraded
  mentions_obsolete     `obsolete_any` matched (the superseded decision showed up)
  endorses_obsolete     it showed up and nothing from `answer_any` did — history
                        next to the current decision is not an endorsement

Phrases are facts only their page carries, matched case-insensitively on word
boundaries in a normalised answer (units joined, arrows unified), so "oom" is not
"room" and "26MB" is "26 mb".

`--summarize` never trusts the metrics a record stored: it re-scores every session
from its raw tools, answer and log with the current rules and tasks, and prints a
one-line notice per file when that changed anything, so two files are never
compared under two rulebooks (`SCORING_VERSION` is stored for tracing). It prints
one row per model × arm × task with Wilson 95% intervals on
every rate. Given two files it prints, per row, B − A for each rate with a Newcombe
95% interval and Fisher's exact two-sided p, and both medians of each per-session
number with a Mann-Whitney U p (normal approximation, tie- and continuity-corrected,
so rough below about eight sessions a side); p < 0.05 is starred. `--json` emits
the same as JSON.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import itertools
import json
import math
import os
import platform
import re
import shlex
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "src"))

from acceptance import build_project, log_events  # noqa: E402

from pagelore import __version__, instructions  # noqa: E402

TASKS = HERE / "agent_tasks.json"
# Bumped whenever `metrics` or a task's phrases change what a session scores.
# Every record carries it, and `--summarize` re-scores every record with the
# current rules anyway, so two files are never compared under two rulebooks.
SCORING_VERSION = 3
ARMS = ("include", "mcp")
TIMEOUT = 600
BASE_TOOLS = ["Bash(lore:*)", "Read", "Edit", "Write", "Grep", "Glob"]
MCP_TOOLS = ["mcp__pagelore__memory_search", "mcp__pagelore__memory_write"]
SEARCH_TOOL = "mcp__pagelore__memory_search"
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
READ_VERBS = {"cat", "head", "tail", "sed", "less", "more", "awk", "bat"}
GREP_VERBS = {"grep", "egrep", "fgrep"}
OPERATORS = {";", "&&", "||", "|", "&", "\n"}
# What a page file looks like from the project root, for "would this glob reach it".
PAGE_PATH = ".memory/some-page.md"
# Rates shown by the summary, in column order, and their short headers.
RATES = [("searched", "searched"), ("correct", "correct"),
         ("endorses_obsolete", "obsolete"), ("searched_before_edit", "srch<edit"),
         ("used_touching", "touching"), ("wrote_page", "wrote"),
         ("grep_memory", "grep_mem"), ("read_memory_file", "read_mem")]
# Per-session numbers compared by medians (Mann-Whitney U) across two files.
NUMBERS = ["n_searches", "repeats", "num_turns", "total_cost_usd"]


# --- tasks ---------------------------------------------------------------------

def load_tasks(path: Path = TASKS) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["tasks"]


# --- one session's stream --------------------------------------------------------

def parse_stream(text: str) -> dict:
    """claude's stream-json: the init event, every tool call in order with whether
    its result came back as an error, and the result event."""
    init, result, tools, errors = {}, {}, [], {}
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init" and not init:
            init = event
        elif kind == "result":
            result = event
        elif kind in ("assistant", "user"):
            for item in (event.get("message") or {}).get("content") or []:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "tool_use":
                    tools.append({"id": item.get("id"), "name": item.get("name"),
                                  "input": item.get("input") or {}})
                elif item.get("type") == "tool_result":
                    errors[item.get("tool_use_id")] = bool(item.get("is_error"))
    for tool in tools:
        tool["error"] = errors.get(tool.pop("id"))
    env = {"model": init.get("model"),
           "claude_code_version": init.get("claude_code_version"),
           "mcp_servers": init.get("mcp_servers"),
           "n_skills": len(init.get("skills") or []),
           "n_plugins": len(init.get("plugins") or []),
           "n_agents": len(init.get("agents") or []),
           "memory_paths": init.get("memory_paths")}
    return {"env": env, "tools": tools, "result": {
        "answer": result.get("result") or "",
        "num_turns": result.get("num_turns"),
        "duration_ms": result.get("duration_ms"),
        "total_cost_usd": result.get("total_cost_usd"),
        "is_error": result.get("is_error"),
        "permission_denials": result.get("permission_denials"),
    }}


# --- matching an answer --------------------------------------------------------

_UNIT = re.compile(r"(\d)[\s\-]*(ms|s|secs?|seconds?|mins?|minutes?|kb|mb|gb)\b")


def normalise(text: str) -> str:
    """Lower case, straight quotes, one space, arrows as `->`, and a number joined
    to its unit by exactly one space — so "16s", "16 s" and "16-s" are one form,
    and "26MB" is "26 mb"."""
    text = text.lower()
    for curly, straight in (("’", "'"), ("‘", "'"), ("“", '"'),
                            ("”", '"')):
        text = text.replace(curly, straight)
    for arrow in ("→", "⟶", "=>", "⇒"):
        text = text.replace(arrow, "->")
    text = re.sub(r"[\s  ]+", " ", text)
    return _UNIT.sub(r"\1 \2", text)


def matches(text: str, phrases) -> bool | None:
    """Any phrase, on word boundaries in the normalised text; `re:` marks a regex
    over the normalised text. None when the task has no such phrases."""
    if not phrases:
        return None
    text = normalise(text)
    for phrase in phrases:
        body = phrase[3:] if phrase.startswith("re:") else re.escape(normalise(phrase))
        if re.search(r"(?<!\w)(?:" + body + r")(?!\w)", text):
            return True
    return False


# --- reading the tool sequence -------------------------------------------------

def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _segments(command: str) -> list[list[str]]:
    """The simple commands of a shell line, split on `;`, `&&`, `||`, `|`, `&` and
    newlines outside quotes — `grep -E "a|b" .memory` is one command, not two. A
    heredoc body is text, not commands, so a line carrying `<<` ends the command.
    Leading `VAR=value` words are dropped, so the first word is what runs."""
    if "<<" in command:
        command = command.split("<<", 1)[0]
    lex = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    try:
        tokens = list(lex)
    except ValueError:  # an unbalanced quote
        tokens = command.split()
    out, current = [], []
    for token in tokens:
        if token in OPERATORS:
            out.append(current)
            current = []
        else:
            current.append(token)
    out.append(current)
    trimmed = []
    for words in out:
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words = words[1:]
        if words:
            trimmed.append(words)
    return trimmed


def _bash(tool: dict) -> list[list[str]]:
    return _segments(tool["input"].get("command", "")) if tool["name"] == "Bash" else []


def is_search(tool: dict) -> bool:
    """A call that runs a search: the MCP tool, or a simple command whose first
    word is `lore`/`pagelore` and second is `search` — not `echo "lore search"`."""
    if tool["name"] == SEARCH_TOOL:
        return True
    return any(w[0] in ("lore", "pagelore") and w[1:2] == ["search"] for w in _bash(tool))


def is_edit(tool: dict) -> bool:
    """An Edit/Write that landed, of a file outside the store. A call the harness
    refused, or that failed, changed nothing and is not the first edit."""
    return (tool["name"] in EDIT_TOOLS and tool.get("error") is not True
            and ".memory" not in str(tool["input"].get("file_path")
                                     or tool["input"].get("notebook_path") or ""))


def _covers_root(path, root: str | None) -> bool:
    """A search path that is the project root or above it — a recursive search
    from there walks `.memory` too."""
    if path in (None, "", ".", "./"):
        return True
    if not root:
        return False
    try:
        Path(root).resolve().relative_to(Path(str(path)).resolve())
        return True
    except (ValueError, OSError):
        return False


def _glob_re(pattern: str) -> re.Pattern:
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        elif pattern[i] == "{" and "}" in pattern[i:]:
            j = pattern.index("}", i)
            out += "(?:" + "|".join(re.escape(x) for x in pattern[i + 1:j].split(",")) + ")"
            i = j + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


def _reaches_page(pattern: str | None, basename_rule: bool = False) -> bool:
    """Would a glob, applied from the project root, match a page file? A Grep
    `glob` without a slash follows ripgrep's rule and matches a name at any depth;
    a Glob pattern is a path from the root."""
    if not pattern:
        return True
    if basename_rule and "/" not in pattern:
        return bool(_glob_re(pattern).match(PAGE_PATH.rsplit("/", 1)[1]))
    return bool(_glob_re(pattern).match(PAGE_PATH))


def _grep_operands(words: list[str]) -> tuple[bool, list[str]]:
    """(recursive, path operands) of a grep command line."""
    recursive, positional, given_pattern, skip = False, [], False, False
    for w in words[1:]:
        if skip:
            skip = False
            continue
        if w in ("-e", "-f", "--regexp", "--file"):
            given_pattern, skip = True, True
        elif w.startswith("--"):
            recursive |= w in ("--recursive", "--dereference-recursive")
            given_pattern |= w.startswith(("--regexp=", "--file="))
        elif w.startswith("-") and len(w) > 1:
            recursive |= "r" in w or "R" in w
        else:
            positional.append(w)
    return recursive, positional if given_pattern else positional[1:]


def _find_reaches_page(rest: list[str], in_memory: bool, root: str | None) -> bool:
    """A `find` that can list a page file: it starts in or above the store and no
    `-name`/`-iname` filter excludes `*.md`."""
    starts = []
    for w in rest:
        if w.startswith(("-", "(", "!")):
            break
        starts.append(w)
    names, where = [], []
    for flag, value in zip(rest, rest[1:]):
        if flag in ("-name", "-iname"):
            names.append(value.lower() if flag == "-iname" else value)
        elif flag in ("-path", "-ipath", "-wholename"):
            where.append(value)
    page = PAGE_PATH.rsplit("/", 1)[1]
    if names and not any(_glob_re(n).match(page) for n in names):
        return False
    if any(".memory" in w for w in starts + where) or in_memory:
        return True
    return any(_covers_root(w, root) for w in starts or ["."])


def scans_memory(tool: dict, root: str | None = None) -> bool:
    """Looked through the store around the command: a Grep/Glob into `.memory` or
    over the whole project, or a shell grep/find/git grep that reaches it. Only
    where a search looks counts — a pattern that mentions `.memory` is text."""
    name, inp = tool["name"], tool["input"]
    if name in ("Grep", "Glob", "LS"):
        where = [inp.get("path"), inp.get("glob")] + ([inp.get("pattern")] if name == "Glob"
                                                       else [])
        if any(isinstance(w, str) and ".memory" in w for w in where):
            return True
        if not _covers_root(inp.get("path"), root):
            return False
        if name == "Glob":
            return _reaches_page(inp.get("pattern"))
        if name == "Grep":
            kind = inp.get("type")
            if kind and kind not in ("md", "markdown"):
                return False
            return _reaches_page(inp.get("glob"), basename_rule=True)
        return False
    in_memory = False
    for words in _bash(tool):
        verb, rest = words[0], words[1:]
        if verb == "cd":
            in_memory = any(".memory" in w for w in rest)
            continue
        if verb in GREP_VERBS:
            recursive, paths = _grep_operands(words)
        elif verb in ("rg", "ag", "ack"):
            recursive = any(w in ("--hidden", "-uu", "-uuu", "-u") for w in rest)
            paths = [w for w in rest if not w.startswith("-")][1:]
        elif verb == "git" and rest[:1] == ["grep"]:
            recursive = False
            tail = rest[1:]
            paths = (tail[tail.index("--") + 1:] if "--" in tail
                     else [w for w in tail if not w.startswith("-")][1:])
        elif verb == "find":
            if _find_reaches_page(rest, in_memory, root):
                return True
            continue
        else:
            continue
        if in_memory or any(".memory" in w for w in paths):
            return True
        if recursive and (not paths or any(_covers_root(w, root) for w in paths)):
            return True
    return False


def reads_memory_file(tool: dict) -> bool:
    if tool["name"] == "Read":
        return ".memory" in str(tool["input"].get("file_path", ""))
    in_memory = False
    for words in _bash(tool):
        if words[0] == "cd":
            in_memory = any(".memory" in w for w in words[1:])
        elif words[0] in READ_VERBS and (in_memory or any(".memory" in w for w in words[1:])):
            return True
    return False


def metrics(task: dict, tools: list[dict], answer: str, events: list[dict],
            root: str | None = None) -> dict:
    """`root` is the project directory, so a Grep over an absolute path can be told
    to be the whole project rather than one subdirectory."""
    searches = [e for e in events if e.get("event") == "search"]
    tops, repeats = set(), 0
    for e in searches:
        top = e.get("top")
        if top is None:
            continue
        repeats += top in tops
        tops.add(top)
    first_search = next((i for i, t in enumerate(tools) if is_search(t)), None)
    first_edit = next((i for i, t in enumerate(tools) if is_edit(t)), None)
    if first_edit is None:
        before = None
    else:
        before = bool(searches) and first_search is not None and first_search < first_edit
    abstained = matches(answer, task.get("abstain_any"))
    current = matches(answer, task.get("answer_any"))
    obsolete = matches(answer, task.get("obsolete_any"))
    if current is not None:
        correct = current
    elif task.get("kind") == "unanswerable":
        correct = abstained
    else:
        correct = None
    return {
        "searched": bool(searches),
        "n_searches": len(searches),
        "repeats": repeats,
        "used_touching": any("touching" in e for e in searches),
        "edited": first_edit is not None,
        "searched_before_edit": before,
        "grep_memory": any(scans_memory(t, root) for t in tools),
        "read_memory_file": any(reads_memory_file(t) for t in tools),
        "wrote_page": any(e.get("event") == "write" for e in events),
        "n_writes": sum(e.get("event") == "write" for e in events),
        "n_rejects": sum(e.get("event") == "reject" for e in events),
        "correct": correct,
        "abstained": abstained,
        "mentions_obsolete": obsolete,
        # History next to the current decision is fine; the old decision alone
        # is the answer the superseded marker exists to prevent.
        "endorses_obsolete": None if obsolete is None else bool(obsolete and not current),
    }


# --- statistics ------------------------------------------------------------------

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - margin), min(1.0, centre + margin)


def fisher_exact(ka: int, na: int, kb: int, nb: int) -> float | None:
    """Two-sided Fisher's exact p for k/n in A against k/n in B: the sum of every
    table with these margins that is no more likely than the one observed."""
    if na == 0 or nb == 0:
        return None
    hits, total = ka + kb, na + nb

    def prob(x):
        return math.comb(hits, x) * math.comb(total - hits, na - x) / math.comb(total, na)

    observed = prob(ka)
    p = sum(prob(x) for x in range(max(0, hits - nb), min(na, hits) + 1)
            if prob(x) <= observed * (1 + 1e-7))
    return min(1.0, p)


def newcombe(ka: int, na: int, kb: int, nb: int) -> tuple[float, float] | None:
    """95% interval for rate(B) − rate(A) from the two Wilson intervals
    (Newcombe 1998, method 10)."""
    wa, wb = wilson(ka, na), wilson(kb, nb)
    if not wa or not wb:
        return None
    pa, pb = ka / na, kb / nb
    d = pb - pa
    return (d - math.sqrt((pb - wb[0]) ** 2 + (wa[1] - pa) ** 2),
            d + math.sqrt((wb[1] - pb) ** 2 + (pa - wa[0]) ** 2))


def mann_whitney(a: list[float], b: list[float]) -> float | None:
    """Two-sided p of the Mann-Whitney U test by the normal approximation, with the
    tie correction and a 0.5 continuity correction — rough below ~8 per side."""
    a = [x for x in a if x is not None]
    b = [x for x in b if x is not None]
    if not a or not b:
        return None
    values = sorted(a + b)
    ranks, i = {}, 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[j + 1] == values[i]:
            j += 1
        ranks[values[i]] = (i + j) / 2 + 1
        i = j + 1
    na, nb, n = len(a), len(b), len(a) + len(b)
    u = sum(ranks[x] for x in a) - na * (na + 1) / 2
    ties = sum(t ** 3 - t for t in (values.count(v) for v in set(values)))
    var = na * nb / 12 * ((n + 1) - ties / (n * (n - 1))) if n > 1 else 0
    if var <= 0:
        return 1.0
    z = max(0.0, abs(u - na * nb / 2) - 0.5) / math.sqrt(var)
    return math.erfc(z / math.sqrt(2))


# --- summary -------------------------------------------------------------------

def rate(values) -> dict:
    known = [bool(v) for v in values if v is not None]
    k, n = sum(known), len(known)
    ci = wilson(k, n)
    return {"k": k, "n": n, "rate": k / n if n else None,
            "lo": ci[0] if ci else None, "hi": ci[1] if ci else None}


def _median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def model_of(session: dict) -> str:
    return str(session.get("model") or session.get("requested_model") or "?")


def summarize(sessions: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for s in sessions:
        groups.setdefault((model_of(s), s["arm"], s["task"]), []).append(s)
    out = []
    for (model, arm, task), rows in sorted(groups.items()):
        g = {"model": model, "arm": arm, "task": task, "n": len(rows),
             "errors": sum(bool(r.get("is_error") or r.get("timed_out")) for r in rows)}
        for key, _ in RATES:
            g[key] = rate(r.get(key) for r in rows)
        g["values"] = {key: [r.get(key) for r in rows] for key in NUMBERS}
        g["median_searches"] = _median(r.get("n_searches") for r in rows)
        g["mean_repeats"] = statistics.mean(r.get("repeats") or 0 for r in rows)
        g["median_turns"] = _median(r.get("num_turns") for r in rows)
        g["median_cost"] = _median(r.get("total_cost_usd") for r in rows)
        out.append(g)
    return out


def load_results(path: Path) -> tuple[list[dict], list[dict]]:
    headers, sessions = [], []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        (headers if row.get("type") == "header" else sessions).append(row)
    return headers, [s for s in sessions if s.get("type") == "session"]


def _pct(r: dict) -> str:
    if r["rate"] is None:
        return "—"
    return f"{r['rate'] * 100:3.0f}% [{r['lo'] * 100:.0f}–{r['hi'] * 100:.0f}] {r['k']}/{r['n']}"


def _num(v, fmt="{:.1f}") -> str:
    return "—" if v is None else fmt.format(v)


def environment(headers: list[dict], sessions: list[dict]) -> dict:
    def distinct(key):
        return sorted({str(s.get(key)) for s in sessions})
    return {"labels": sorted({str(h.get("label")) for h in headers}),
            "git": sorted({f"{h.get('git')}{'+dirty' if h.get('dirty') else ''}"
                           for h in headers}),
            "block": sorted({str(h.get("block_sha")) for h in headers}),
            "tool_search": sorted({str(h.get("enable_tool_search")) for h in headers}),
            "model": distinct("model"), "claude_code": distinct("claude_code_version"),
            "skills": distinct("n_skills"), "plugins": distinct("n_plugins"),
            "agents": distinct("n_agents")}


def print_table(name: str, env: dict, groups: list[dict]) -> None:
    print(f"== {name}")
    print("   " + "  ".join(f"{k}={','.join(v)}" for k, v in env.items()))
    print(f"{'model':18} {'arm':8} {'task':4} {'n':>3} {'err':>3}  "
          + "  ".join(f"{h:>20}" for _, h in RATES)
          + f"  {'med srch':>8} {'mean rep':>8} {'med turn':>8} {'med $':>6}")
    for g in groups:
        print(f"{g['model']:18} {g['arm']:8} {g['task']:4} {g['n']:>3} {g['errors']:>3}  "
              + "  ".join(f"{_pct(g[k]):>20}" for k, _ in RATES)
              + f"  {_num(g['median_searches']):>8} {_num(g['mean_repeats'], '{:.2f}'):>8}"
              f" {_num(g['median_turns']):>8} {_num(g['median_cost'], '{:.3f}'):>6}")
    print()


def compare(a: list[dict], b: list[dict]) -> list[dict]:
    """B against A for every model × arm × task in both: each rate with its
    difference, Newcombe interval and Fisher p; each per-session number with both
    medians and a Mann-Whitney p."""
    left = {(g["model"], g["arm"], g["task"]): g for g in a}
    right = {(g["model"], g["arm"], g["task"]): g for g in b}
    out = []
    for key in sorted(set(left) & set(right)):
        base = {"model": key[0], "arm": key[1], "task": key[2]}
        for metric, _ in RATES:
            ra, rb = left[key][metric], right[key][metric]
            ci = newcombe(ra["k"], ra["n"], rb["k"], rb["n"])
            p = fisher_exact(ra["k"], ra["n"], rb["k"], rb["n"])
            out.append({**base, "metric": metric, "kind": "rate",
                        "a": ra["rate"], "b": rb["rate"],
                        "a_k": ra["k"], "a_n": ra["n"], "b_k": rb["k"], "b_n": rb["n"],
                        "delta": None if ci is None else rb["rate"] - ra["rate"],
                        "lo": ci[0] if ci else None, "hi": ci[1] if ci else None,
                        "p": p, "significant": p is not None and p < 0.05})
        for metric in NUMBERS:
            va, vb = left[key]["values"][metric], right[key]["values"][metric]
            ma, mb = _median(va), _median(vb)
            p = mann_whitney(va, vb)
            out.append({**base, "metric": metric, "kind": "median", "a": ma, "b": mb,
                        "delta": None if ma is None or mb is None else mb - ma,
                        "p": p, "significant": p is not None and p < 0.05})
    return out


def print_diff(diff: list[dict], paths: list[str]) -> None:
    print(f"== difference: B ({paths[1]}) − A ({paths[0]})")
    print("   rates: Δ with Newcombe 95% interval, Fisher's exact two-sided p; numbers:")
    print("   medians, Mann-Whitney U p by normal approximation. * marks p < 0.05")
    print(f"{'model':18} {'arm':8} {'task':4} {'metric':22} {'A':>10} {'B':>10} "
          f"{'Δ':>8} {'95% CI':>15} {'p':>7}")
    for d in diff:
        star = " *" if d["significant"] else ""
        p = _num(d["p"], "{:.3f}")
        if d["kind"] == "rate":
            a = "—" if d["a"] is None else f"{d['a_k']}/{d['a_n']}"
            b = "—" if d["b"] is None else f"{d['b_k']}/{d['b_n']}"
            delta = "—" if d["delta"] is None else f"{d['delta'] * 100:+.0f}pp"
            ci = "—" if d["lo"] is None else f"[{d['lo'] * 100:+.0f}, {d['hi'] * 100:+.0f}]"
        else:
            a, b = _num(d["a"], "{:.2f}"), _num(d["b"], "{:.2f}")
            delta, ci = ("—" if d["delta"] is None else f"{d['delta']:+.2f}"), ""
        print(f"{d['model']:18} {d['arm']:8} {d['task']:4} {d['metric']:22} {a:>10} {b:>10} "
              f"{delta:>8} {ci:>15} {p:>7}{star}")


def rescore(sessions: list[dict], tasks: dict[str, dict]) -> dict:
    """Recompute every session's metrics from its raw tools, answer and log with
    the current rules and task spec, in place. Returns what differed from the
    metrics stored when it ran."""
    changed_sessions, changed_fields, skipped = 0, 0, 0
    stored_versions = set()
    for s in sessions:
        stored_versions.add(s.get("scoring_version"))
        task = tasks.get(s.get("task"))
        if task is None or "tools" not in s:
            skipped += 1
            continue
        fresh = metrics(task, s.get("tools") or [], s.get("answer") or "",
                        s.get("log") or [], s.get("project"))
        diff = sum(s.get(k) != v for k, v in fresh.items())
        changed_fields += diff
        changed_sessions += bool(diff)
        s.update(fresh)
    return {"sessions": len(sessions), "changed_sessions": changed_sessions,
            "changed_fields": changed_fields, "not_rescored": skipped,
            "stored_versions": sorted(str(v) for v in stored_versions)}


def rescore_notice(path: str, r: dict) -> str | None:
    if not (r["changed_fields"] or r["not_rescored"]):
        return None
    return (f"note: {path}: re-scored with scoring v{SCORING_VERSION} (stored: "
            f"{', '.join(r['stored_versions'])}); {r['changed_fields']} field(s) in "
            f"{r['changed_sessions']} of {r['sessions']} session(s) differ from the stored "
            f"metrics" + (f"; {r['not_rescored']} could not be re-scored (unknown task "
                          "or no raw tools) and keep their stored metrics"
                          if r["not_rescored"] else ""))


def summarize_files(paths: list[str], as_json: bool) -> int:
    loaded = [load_results(Path(p)) for p in paths]
    tasks = {t["id"]: t for t in load_tasks()}
    rescored = [rescore(sessions, tasks) for _, sessions in loaded]
    for path, r in zip(paths, rescored):
        notice = rescore_notice(path, r)
        if notice:
            print(notice, file=sys.stderr if as_json else sys.stdout)
    tables = [summarize(sessions) for _, sessions in loaded]
    envs = [environment(h, s) for h, s in loaded]
    diff = compare(tables[0], tables[1]) if len(tables) == 2 else []
    if as_json:
        print(json.dumps({"scoring_version": SCORING_VERSION,
                          "files": [{"path": p, "environment": e, "groups": t, "rescored": r}
                                    for p, e, t, r in zip(paths, envs, tables, rescored)],
                          "diff": diff}, indent=2))
        return 0
    for p, e, t in zip(paths, envs, tables):
        print_table(p, e, t)
    if diff:
        print_diff(diff, paths)
    return 0


# --- running -------------------------------------------------------------------

def child_env(bindir: Path, home: Path) -> dict:
    """A clean child: launched from inside an agent session, the parent's session
    id and nesting markers must not leak into the run being measured, and no
    PAGELORE_* override (PAGELORE_NO_LOG above all) may silence the log the
    metrics are read from. CLAUDE_CODE_OAUTH_TOKEN is credentials, not a marker."""
    env = {k: v for k, v in os.environ.items()
           if not ((k.startswith("CLAUDE_CODE_") and k != "CLAUDE_CODE_OAUTH_TOKEN")
                   or k == "CLAUDECODE" or k.startswith("PAGELORE_"))}
    env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    # Never created: its absence is what keeps `lore` from refreshing a home block.
    env["PAGELORE_HOME"] = str(home)
    return env


def make_shim(bindir: Path) -> Path:
    bindir.mkdir(parents=True, exist_ok=True)
    shim = bindir / "lore"
    target = os.environ.get("PAGELORE_BIN")
    if target:
        body = f'exec {shlex.quote(target)} "$@"\n'
    else:
        src = shlex.quote(str(REPO / "src"))
        body = (f'PYTHONPATH={src}${{PYTHONPATH:+:$PYTHONPATH}} PAGELORE_INVOKED_AS=lore '
                f'exec {shlex.quote(sys.executable)} -m pagelore "$@"\n')
    shim.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    shim.chmod(0o755)
    return shim


def check_lore(env: dict) -> str:
    """The `lore` a session will run, or SystemExit naming what is wrong."""
    found = shutil.which("lore", path=env["PATH"])
    proc = subprocess.run([found or "lore", "--version"], capture_output=True, text=True,
                          env=env, timeout=60) if found else None
    line = proc.stdout.strip() if proc else ""
    if not line.startswith(f"pagelore {__version__} ") or str(REPO / "src" / "pagelore") not in line:
        raise SystemExit(f"FIX: `lore --version` in the session says {line or 'nothing'!r}, "
                         f"not pagelore {__version__} from {REPO / 'src'}. Unset "
                         "PAGELORE_BIN or point it at this tree's program.")
    return line


def agent_command(prompt: str, mcp_config: Path, tools: list[str], model: str | None) -> list[str]:
    # The prompt sits right after -p: --allowedTools is variadic and would swallow it.
    cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
           "--no-session-persistence", "--setting-sources", "project",
           "--strict-mcp-config", "--mcp-config", str(mcp_config)]
    if model:
        cmd += ["--model", model]
    return [*cmd, "--allowedTools", *tools]


def prepare(directory: Path, arm: str, task: dict, model: str | None) -> tuple[Path, list[str]]:
    directory.mkdir(parents=True)
    project = build_project(directory, arm, task.get("files") or {})
    if arm == "include":
        mcp_config = directory / "empty-mcp.json"
        mcp_config.write_text(json.dumps({"mcpServers": {}}) + "\n", encoding="utf-8")
        tools = BASE_TOOLS
    else:
        mcp_config = project / ".mcp.json"
        tools = BASE_TOOLS + MCP_TOOLS
    return project, agent_command(task["prompt"], mcp_config, tools, model)


def tidy_auto_memory(memory_paths) -> int:
    """Claude Code makes `~/.claude/projects/<cwd slug>/memory/` for every session's
    auto memory, so a hundred sessions leave a hundred directories in the user's
    home. Remove the one this session made when it is empty; return how many files
    it held (kept in that case, and recorded, since then the agent used it)."""
    auto = (memory_paths or {}).get("auto") if isinstance(memory_paths, dict) else None
    if not auto:
        return 0
    project = Path(auto).parent
    if (project.parent != Path.home() / ".claude" / "projects"
            or "pm-agent-eval-" not in project.name or not project.is_dir()):
        return 0
    files = sum(1 for f in project.rglob("*") if f.is_file())
    if not files:
        shutil.rmtree(project, ignore_errors=True)
    return files


def _text(value) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value


def kill_tree(proc: subprocess.Popen) -> None:
    """The session and everything it started — the MCP server above all, which
    otherwise outlives a killed `claude` holding the store open."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           capture_output=True, timeout=30)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass


def run_session(project: Path, cmd: list[str], env: dict, timeout: int) -> dict:
    """One session in its own process group, so a timeout kills the whole tree.
    stdin is closed: from a pipe, claude waits 3 s for input and warns."""
    started = time.perf_counter()
    group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    proc = subprocess.Popen(cmd, cwd=project, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", env=env, **group)
    try:
        out, err = proc.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        out, err = proc.communicate()
        timed_out = True
    else:
        kill_tree(proc)  # anything the session left running
    return {"stdout": _text(out), "stderr": _text(err),
            "exit_code": None if timed_out else proc.returncode, "timed_out": timed_out,
            "elapsed_s": round(time.perf_counter() - started, 1)}


def _git(*args) -> str:
    try:
        return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True,
                              text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def header(args, lore_line: str, claude_version: str) -> dict:
    return {"type": "header", "date": _dt.datetime.now().isoformat(timespec="seconds"),
            "label": args.label, "pagelore": __version__, "lore": lore_line,
            "git": _git("rev-parse", "--short", "HEAD"),
            "dirty": bool(_git("status", "--porcelain")),
            "block_sha": hashlib.sha256(instructions.render().encode()).hexdigest()[:12],
            "claude": claude_version, "arms": args.arms, "tasks": args.tasks,
            "runs": args.runs, "models": args.models, "timeout": args.timeout,
            "enable_tool_search": os.environ.get("ENABLE_TOOL_SEARCH"),
            "platform": platform.platform(), "python": platform.python_version()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--tasks", default=",".join(t["id"] for t in load_tasks()))
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--label", default="run")
    ap.add_argument("--out", help="default: evals/results/agent-<date>-<version>-<label>.jsonl")
    ap.add_argument("--models", default="",
                    help="comma list passed to claude --model, one session each (e.g. "
                         "claude-opus-5-5,claude-sonnet-5); by default none is passed and "
                         "the CLI default runs. The init event's model is recorded either way")
    ap.add_argument("--timeout", type=int, default=TIMEOUT, help="seconds per session")
    ap.add_argument("--dry-run", action="store_true",
                    help="build the projects and print the commands; run nothing")
    ap.add_argument("--keep", action="store_true", help="keep the project directories")
    ap.add_argument("--append", action="store_true",
                    help="add sessions to an existing --out file instead of refusing")
    ap.add_argument("--summarize", nargs="+", metavar="FILE",
                    help="summarize one results file, or compare two")
    ap.add_argument("--json", action="store_true", help="the summary as JSON")
    args = ap.parse_args(argv)

    if args.summarize:
        if len(args.summarize) > 2:
            ap.error("--summarize takes one file or two")
        return summarize_files(args.summarize, args.json)

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    if not set(arms) <= set(ARMS):
        ap.error(f"--arms: choose from {', '.join(ARMS)}")
    by_id = {t["id"]: t for t in load_tasks()}
    wanted = [t.strip() for t in args.tasks.split(",") if t.strip()]
    if not set(wanted) <= set(by_id):
        ap.error(f"--tasks: choose from {', '.join(by_id)}")
    models = [m.strip() for m in args.models.split(",") if m.strip()] or [None]
    out = Path(args.out or REPO / "evals" / "results" /
               f"agent-{_dt.date.today().isoformat()}-{__version__}-{args.label}.jsonl")
    if not args.dry_run and out.exists() and out.stat().st_size and not args.append:
        print(f"FIX: {out} already holds results. Pass --append to add to it, or a new "
              "--out — two runs merged by accident read as one.", file=sys.stderr)
        return 2

    root = Path(tempfile.mkdtemp(prefix="pm-agent-eval-"))
    env = child_env(root / "bin", root / "home")
    make_shim(root / "bin")
    lore_line = check_lore(env)
    print(f"lore       {lore_line}")

    claude_version = ""
    if not args.dry_run:
        claude = shutil.which("claude", path=env["PATH"])
        if not claude:
            print("FIX: no `claude` on PATH — `npm install -g @anthropic-ai/claude-code`.",
                  file=sys.stderr)
            return 2
        claude_version = subprocess.run([claude, "--version"], capture_output=True,
                                        text=True, env=env, stdin=subprocess.DEVNULL,
                                        timeout=60).stdout.strip()
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(header(args, lore_line, claude_version)) + "\n")
        print(f"claude     {claude_version}\nout        {out}")

    # Runs outer, then tasks, models, arms: the cells being compared sit close in time.
    for run in range(1 if args.dry_run else args.runs):
        for tid, (mi, model), arm in itertools.product(wanted, enumerate(models), arms):
            task = by_id[tid]
            directory = root / f"{arm}-{tid}-{mi}-{run}"
            project, cmd = prepare(directory, arm, task, model)
            if args.dry_run:
                print(f"{arm} {tid} {project}")
                print("$ " + shlex.join(cmd))
                continue
            done = run_session(project, cmd, env, args.timeout)
            parsed = parse_stream(done["stdout"])
            events = log_events(project / ".memory")
            answer = parsed["result"]["answer"]
            record = {"type": "session", "scoring_version": SCORING_VERSION,
                      "label": args.label, "arm": arm, "task": tid,
                      "kind": task["kind"], "run": run, "requested_model": model,
                      "project": str(project),
                      "exit_code": done["exit_code"], "timed_out": done["timed_out"],
                      "elapsed_s": done["elapsed_s"], **parsed["env"],
                      "auto_memory_files": tidy_auto_memory(parsed["env"]["memory_paths"]),
                      **{k: v for k, v in parsed["result"].items() if k != "answer"},
                      **metrics(task, parsed["tools"], answer, events, str(project)),
                      "answer": answer, "tools": parsed["tools"],
                      "log": [e for e in events if e.get("event") in
                              ("search", "write", "reject")]}
            if done["exit_code"] != 0:
                record["stderr_tail"] = done["stderr"][-2000:]
            with out.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"{record['model'] or model} {arm:8} {tid} run {run}: "
                  f"searched={record['searched']} n={record['n_searches']} "
                  f"repeats={record['repeats']} correct={record['correct']} "
                  f"before_edit={record['searched_before_edit']} "
                  f"wrote={record['wrote_page']} ${record['total_cost_usd']} "
                  f"{done['elapsed_s']}s", flush=True)
            if not args.keep:
                shutil.rmtree(directory, ignore_errors=True)

    if args.dry_run or args.keep:
        print(f"kept       {root}")
    else:
        shutil.rmtree(root, ignore_errors=True)
    if not args.dry_run:
        print()
        summarize_files([str(out)], as_json=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
