# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.8.3] - 2026-09-28

### Added

- **`lore stats` reports which route each search came in on, and repeated
  searches.** The log's `search` events now carry `via` (`"cli"` or `"mcp"`);
  `lore stats` prints a breakdown when any record has it, and treats older
  records without the field as `unknown` rather than miscounting them.
  `lore stats` also reports `repeated`: a search that re-returned, within two
  minutes, the same top page an earlier search in the same session had already
  returned — records without a session (older logs, and clients that do not
  pass a session id, as seen in a real log) are grouped as one stream — the
  paraphrase-and-reask pattern real logs showed.
- **`PAGELORE_NO_LOG` turns logging off entirely.** Any non-empty value makes
  `log_event` a no-op. `evals/speed.py` sets it on every process it spawns, so
  a benchmark run never lands in a real project's log.
- **CI gates retrieval quality, speed, the MCP round trip and documented
  examples.** `tests/test_evals_baseline.py` runs the shipped ranker in-process
  against `evals/baseline.json` and fails a PR that regresses nDCG@10, MRR@10,
  recall, or the unanswerable-query false-confidence rate by more than 0.005, in
  both FTS5-index and no-FTS5 (scan) mode. A new `speed-gate` job fails if a warm
  search over 1000 pages exceeds 1000 ms. `install-smoke`'s MCP step now drives a
  full `tools/call` round trip — `memory_write`, `memory_search`, and a
  credential-shaped write that must be refused. `tests/test_docs_examples.py`
  parses every documented `lore …` command against the real CLI parsers so a
  renamed or removed flag breaks the build instead of the docs.
- **A measurement of how a real Claude Code agent uses the memory.**
  `evals/agent_eval.py` runs `claude -p` against a throwaway project per model ×
  connection (instruction file or MCP) × task and scores each session: whether and
  how often it searched, repeats, `--touching`, search before the first edit,
  bypassing the search through `.memory`, page written, correct or abstained
  answers, turns and cost. A manual GitHub workflow runs it with an
  `ANTHROPIC_API_KEY` secret.

### Changed

- **Agent instructions: every word in one query.** The block and the MCP
  `memory_search` description now ask for synonyms, the component and the symptom
  in one query, and the MCP instructions ask for the file's path as `touching`
  before changing it. Measured on Claude Code: baseline and v1 on Opus 5.5 and
  Sonnet 5 (240 sessions each); the shipped v2 on the Sonnet 5 cells v1 moved
  (80 sessions) (see docs/measurements.md); a first version that also said "do
  not reword" was measured to hurt and was not shipped.
- **The `⚠ source changed` / `⚠ source gone` check is faster on a long history.**
  `git log` is now read incrementally and stopped as soon as every cited source
  has an answer, instead of always walking the full log. `lore show` also reads
  the store once instead of twice.

## [0.8.2] - 2026-09-27

### Fixed

- **`⚠ source changed` now works in the default store mode.** A page that is never
  committed — the default gitignored store, a `home` store, a page not committed
  yet — is compared by its file's modification time instead of being skipped. In
  0.8.0 and 0.8.1 only `⚠ source gone` could appear for those pages.
- **An older copied install is found and removed.** Releases up to 0.3.x were a
  `project-memory` skill copied into `~/.agents/skills/` or a project's
  `.agents/skills/`, with hooks in `.claude/settings.json`; those scripts keep
  working after an upgrade and run beside the current program. `lore uninstall`
  now removes the copy, its `.claude/skills/` link and its hooks (other hooks and
  settings are kept), globally and in every known project; `lore doctor` reports
  them and `lore init` warns. A `project-memory` directory without the old scripts
  is left alone.
- **The warning for a pre-0.6.0 variable name no longer promises 0.7.0.** The old
  names (`PROJECT_MEMORY_*`) still work; the warning now says they stop working in
  a future release.

## [0.8.1] - 2026-09-27

### Fixed

- **`lore uninstall` cleans every connected project, not only the one underfoot.**
  `lore init --scope project` now records the project in `~/.pagelore/projects`, and
  uninstall removes the instruction-file block and the MCP entry from each recorded
  project wherever it is run from. Before, a block in any other repository survived
  and dangled once `--yes` deleted the block file. Projects connected by earlier
  versions were not recorded; run `lore uninstall` inside each of them once.

## [0.8.0] - 2026-09-27

### Changed

- **License: MIT → PolyForm Noncommercial 1.0.0.** Free for personal, research,
  educational and other noncommercial use; selling pagelore or building it into a
  paid product or service needs a separate license from the author. Versions up to
  and including 0.7.0 were released under MIT and stay under MIT.

## [0.7.0] - 2026-09-27

### Added

- **`lore search --touching PATH` logs whether it found a page.** The `search`
  log line gains `touched`: how many of the returned hits were pages whose
  `sources` named one of the given paths, logged only when `--touching` was
  given. `lore stats` gains `touching_searches` (every search that passed
  `--touching`, old logs included), `touching_measured` (the slice of those
  that also carry `touched`, i.e. logged after this field shipped — the miss
  rate is read against this, not against `touching_searches`, so a handful of
  measured misses is not diluted by every old, unmeasurable line),
  `touching_misses` (records with `touched == 0`), and the last 15 missed path
  lists, printed as a `touching` line — `touching N (M measured, K found no
  page touching the path)` — next to the existing zero-hit search line.

- **`lore search` and `lore show` mark a page whose `sources` moved on after the
  page did, from git history.** A hit is marked `⚠ source changed: a.py, b.py`
  when a source's last commit is newer than the page file's own, and
  `⚠ source gone: c.py` when a source no longer resolves at all — a page and a
  source landing in the *same* commit are not marked, since that is one clock
  reading, not two. `--json` hits gain `stale_sources` and `gone_sources`,
  always present, possibly empty. Neither marker changes ranking. Nothing is
  marked outside a git work tree (no repository, no `git` binary, a timed-out
  call) — without git there is no reliable project root to resolve a `gone`
  source against, so the feature stays silent rather than guess. The check runs
  once per search, after ranking is done, not inside `search()` itself, so
  `evals/run.py` (hundreds of `search()` calls per run) pays nothing for it.
  `changed` needs the store itself to be committed to git — the default,
  gitignored store mode and a `home` store (outside the repo) never commit
  pages, so only `gone` appears there; this is not a bug, there is no fallback.

- **`[[slug]]` links are now parsed, checked and surfaced.** `lore write` warns,
  code `dangling_link`, when a `[[slug]]` in the resulting page names no page in
  the store — `⚠ [[x]] names no page in this store — write it, or fix the slug`,
  one line per distinct target, exit code still 0 (it is a warning, not a
  refusal: an agent legitimately writes page A linking to page B before B
  exists). `lore show <slug>` prints `linked from: a, b` on stderr — the other
  pages, sorted, whose `[[slug]]` names the page being shown; stdout is
  unchanged, still byte-identical to the file. A link inside a fenced code
  block or an inline code span is read as literal text, not a cross-reference.

- **`lore write` refuses a title or body that looks like a committed credential**
  (AWS access key, classic or fine-grained GitHub token, Anthropic or OpenAI API
  key, Slack token, PEM private key header), code `secret_in_body`. The refusal
  names the kind and line number only, never the matched value, since the reason
  is written to the store's log. A long random-looking string (40+ chars,
  Shannon entropy ≥ 4.5 bits/char) does not refuse the write — that check has
  false positives on legitimate long tokens — but warns on stderr after a
  successful write: `⚠ body line N looks like a credential (high-entropy
  string) — if it is one, remove it and rewrite the page` (or `⚠ title looks
  like a credential …` for the title). `lore stats` gains `warn_codes`,
  grouped the same way as `reject_codes`.
- **A "looks like an existing page" warning on `lore write` was measured and
  not built.** `evals/duplicate_probe.py` first measured Jaccard and TF-IDF
  cosine over tokenized title+body per *pair* (11 supersedes pairs as
  positives against the eval corpus's other 3994 pairs), which looked
  promising — Jaccard reached 0.818 recall at a 0.93% false-positive rate. But
  the write path does not compare one pair: it compares one new page against
  every other page in the store and warns on the single best match, which is
  90 chances per write for an unrelated page to score high by accident, not
  one. Re-measured per write, recall collapsed to 0.09 (jaccard) / 0.00
  (tfidf cosine) at the same 1%-false-warnings budget — below the 0.5 floor
  the decision was made against. See `.memory/duplicate-warning-measured.md`.

### Fixed

- **`lore write` no longer bumps `updated` on a byte-identical rewrite.**
  Re-running the exact same slug/title/kind/sources/body used to still refresh
  the date and rewrite the file, which made a no-op re-run look like a real
  edit to `git log` and to anything using `updated` as a staleness signal.
  Prints `unchanged: nothing to write` on stderr, still exits 0. `lore stats`
  gains an `unchanged` count next to `new`/`merged`.

## [0.6.0] - 2026-09-27

### Changed

- **One name: everything `project-memory` is now `pagelore`.** The package and the
  command already were; the rest now follows. Breaking, with a migration that needs
  no hand edits — see
  [upgrading to 0.6.0](docs/installation.md#upgrading-to-060-one-name).
  - **`~/.project-memory` → `~/.pagelore`.** The first command after the upgrade (or
    `lore init`) moves it with one rename and leaves a link at the old path, so a
    `--store home` project whose `.memory` symlink points into the old directory keeps
    working. The `@` include `lore init` wrote is repointed, inside its managed block
    only, in `~/.claude/CLAUDE.md`, `~/.gemini/GEMINI.md` and the current project's
    `CLAUDE.md`/`GEMINI.md`. When both directories exist nothing is merged and
    `lore doctor` reports it; with `PAGELORE_HOME` set nothing moves.
  - **`PROJECT_MEMORY_*` → `PAGELORE_*`** (`DIR`, `HOME`, `NO_REFRESH`, `NO_FTS5`,
    and `PYTHON` in the npm shim). The old names are still read when the new one is
    unset, with a one-line deprecation warning on stderr (never on `--json` stdout or
    the MCP stream). **0.7.0 removes them.**
  - **MCP server `project-memory` → `pagelore`**, in every registration `lore init`
    writes: Claude Code's `.mcp.json` and user scope, Gemini, Codex and Cursor.
    `init` replaces an old entry that has exactly the shape it used to write (through
    `claude mcp remove` / `codex mcp remove` where it went in that way) and leaves an
    edited one alone; `lore uninstall` removes both names; `lore doctor` reports an
    old one. Tool names are unchanged; the client prefix becomes
    `mcp__pagelore__memory_search`.
  - The search index cache moves to `~/.cache/pagelore/` and rebuilds on the next
    search; `~/.cache/project-memory/` can be deleted.
  - The repository is now `github.com/Krowli/pagelore`; the old URL redirects.

### Fixed

- **`lore uninstall --yes` deleted `--store home` pages.** It removed the whole
  `~/.pagelore/` directory, and a `lore init --store home` project keeps its pages
  there (`~/.pagelore/<project>/`, reached through the project's `.memory` link) —
  while its help said "not your pages". It now removes only pagelore's own files
  there (the block `AGENT.md`, its `.version` stamp, and scratch files a crashed
  write left), keeps and lists every store and anything else it did not write, and
  removes the directory only once it is empty. The `~/.project-memory` link is
  removed only when it points at that directory and the directory is gone.

## [0.5.1] - 2026-09-26

### Added

- **`lore mcp` tells the agent when to use it.** The `initialize` reply now carries
  `instructions` — the MCP field a client may add to the system prompt — so an agent
  with only the server connected, and no instruction file, is told to search before
  stating anything about the project and to write after a decision or a non-obvious
  fix. The text is the instruction block's own paragraphs, marked in
  `data/AGENT.md` and naming `memory_search` and `memory_write` in place of the shell
  commands, so the two routes cannot drift; about 1.2k characters. Measured on
  Claude Code's default settings, MCP alone: 4/10 sessions searched before
  answering without it, 10/10 with it. `evals/mcp_probe.py --handshake` shows what
  a client receives.

### Fixed

- **Parallel writes to one page lost sections on Windows.** Traced on a Windows
  runner: the holder's delete of its lock file was refused while another writer
  was reading the owner's pid out of it, and the release gave up, leaving the lock
  behind; then the liveness probe reported the exited owner as *alive* (it answered
  "no such process" with true), so every other writer waited out the sixty-second
  timeout and wrote unlocked at once. And a writer that tried to create the lock
  while Windows was still deleting the previous one got "access denied", took it
  for an unlockable store and wrote unlocked immediately. The release now waits
  out the momentary read, the probe answers correctly, and a refused create is
  waited on like an existing lock. The 12-writer test went from 3 failing
  iterations in 50 to 0 in 100 on Python 3.11 and 3.13.

## [0.5.0] - 2026-09-26

### Added

- **`lore show <slug>`, `lore list`, `lore edit <slug>`, `lore rm <slug>`, `lore version`.**
  The contract used to open a page with `cat <store path>/<slug>.md`, which was
  correct and never typed; it now says `lore show <slug>`, the slug a search
  printed and nothing to copy. `list` shows what `ls` cannot — kind, date, and which
  pages were superseded. `edit` opens a page in `$VISUAL`/`$EDITOR` and says so if
  the page came back under the floor search applies, which is the one way a hand
  edit goes wrong silently. `rm` deletes and logs, so `stats` still adds up. `version`
  is a word as well as a flag, and the flag is now listed by the bare command.
- **`lore mcp`, a stdio MCP server in the box.** The same two functions the commands
  call, behind `memory_search` and `memory_write` — same ranking, same write gate,
  same `FIX:` lines. It finds the store from `PROJECT_MEMORY_DIR`, then the project
  Claude Code names in `CLAUDE_PROJECT_DIR`, then by walking up from the cwd, because
  a stdio server is promised no working directory. stdout carries JSON-RPC lines and
  nothing else, written as bytes so a Windows text stream cannot add a `\r`.
- **A fourth question: how the agent reaches it.** Instruction file, MCP server, or
  both; `--via file|mcp` is the same answer for a script. Enter keeps the file — the
  measured default — and the measurement sits on the question: on Claude Code the
  file searched 15/15, MCP alone 0/15 in September and 3/5 re-measured on the day this
  shipped. The numbers used to keep MCP out of the package; they are an argument for
  a default, not for deciding on someone's behalf.
- **`lore dev`, the console — and a bare `lore` on a real terminal opens it.**
  Every line is one lore command, run in its own child process, so output and exit
  codes are exactly what an agent would see. `--sandbox` runs the same console
  against a throwaway store, project and HOME, so `write`, `init` and `uninstall`
  can be rehearsed and then discarded. Anywhere that is not a terminal a bare
  `lore` still prints usage and exits 0, which is the contract an agent probe leans
  on.
- **`lore dev --panes`, an opencode-shaped screen, behind a flag.** Fresh it
  looks like the screen it was copied from: a logo, a big "Ask anything…" box, a
  hint bar with the store, the shortcuts and the "model" tag. Once a command has
  run it becomes a transcript — every command echoed like the prompt, its output
  underneath, exactly what `cli.main` prints — and the field shrinks to the
  bottom line. `/` (or ctrl+p) *always* opens a centred command picker — one
  hint per command, a filter, j/k and ↑/↓ — even when the field is not empty,
  `o` opens the top hit of the last search (the slug is never retyped),
  `↑` walks history, PgUp/PgDn scroll the transcript, `q` is back to the line
  editor. Enter on a bare `search` (no query yet) leaves the field as
  `lore > search ` — the user's own text stays on the main screen, only the
  query is missing, so there is no second screen and no argparse usage — and
  the field takes full UTF-8, so a query over the bilingual corpus types like
  any other text. Transcripts of a plain `search`
  render readably, not as the CLI's
  wrapped prose: one card per hit, slug and title on the line with the score
  and date right-aligned, and the matched window dim underneath — the raw bytes
  are still stored on the turn, so a flagged search falls straight back to the
  byte-for-byte text. Commands that must own the terminal (the MCP server, the
  init wizard, `edit`) are refused from the field rather than half-run. It is
  opt in (`--panes`, or the internal `panes` command) and the line editor stays
  the default, so the bare-`lore` probe contract never sees it. What a key
  decides is a pure function on the screen model, tested the way the line
  editor is — called directly, and one pty test proves the raw screen draws the
  ask box, runs commands, opens the picker from a non-empty field, and answers
  `o`. `curses` is POSIX and the screen needs a real terminal; where either is
  missing it says so and falls back to the line editor, so a pipe driving
  `lore dev --panes` still reads lines.
  Measured (`evals/panes_keystrokes.py`, `make eval-panes`): find + read one
  page costs `len(slug) + 7` fewer keystrokes and two fewer process spawns than
  the CLI's `search` + `show` round trip; every other command from the field
  additionally spawns 0 processes where the line editor spawns one child per
  line.
- **A local release rehearsal.** `tools/smoke.sh` (a `make smoke` away) builds the
  wheel, installs it into an isolated environment, and runs the same end-to-end
  steps CI's install-smoke runs — including the MCP route — against a throwaway
  HOME, without publishing anything or touching a real install. It also exposes
  the two-lores trap: `lore doctor` proves the MCP handshake by running `lore mcp`
  from PATH, so the smoke leads PATH with the freshly installed command, and
  `evals/acceptance.py` gains `PAGELORE_BIN` to do the same when measuring.
- **`Makefile`** with `make dev` (editable env, with a hint about the `lore`
  already on PATH), `make test` (both retrieval paths, then ruff) and `make smoke`.
  `.mcp.json` and Gemini's `settings.json` are merged in place with everything else
  kept; `~/.claude.json` and Codex's `config.toml` go through the harness's own
  `mcp add`, run when it is on PATH and printed when it is not.
- **`lore doctor` sees an MCP registration**, checks the command it names is on PATH,
  and proves the server the harness will run answers `tools/list` with the two tools
  — an old install earlier on PATH fails there and says which one.
- **`lore doctor` names a shadowing install.** When the `lore` on PATH is a
  different install than the one running, the `command` check fails and says which
  one PATH picks, reading the answer out of `--version` — the two-lores trap the
  smoke rehearsal exposed. A binary that will not answer `--version` is reported
  as the old-build case of the same fault.
- **`lore uninstall` takes the MCP entry back out** of `.mcp.json` and `settings.json`,
  deletes a `.mcp.json` it emptied, and runs or prints `claude mcp remove` /
  `codex mcp remove` for the files it does not edit by hand.
- **Cursor.** `lore init --agent cursor` (and a fourth row in the wizard): the MCP
  route writes `.cursor/mcp.json` in the project or `~/.cursor/mcp.json` globally,
  with `type: "stdio"` as Cursor's field table requires; the file route writes the
  project's `AGENTS.md`, which Cursor reads alongside Codex — the wizard row now says
  so — and globally, where Cursor keeps user rules in Customize → Rules rather than a
  file, says what to paste. `lore uninstall` takes the entry out of both `mcp.json`
  files and never deletes them; `lore doctor` reports the registration.
- **`lore init --json`.** The result — block, scope, agents, route and every change
  with its path — as one JSON document on stdout; the messages a person reads go to
  stderr.

### Changed

- **The wizard looks like one.** Bold questions, dim notes and key hints, a coloured
  cursor row, one label column in both menu shapes, `~/` paths, and an answered
  question collapses to one line — `✔ Where should this apply?  This project only` —
  instead of leaving the whole menu standing under the next one. `NO_COLOR` and
  `TERM=dumb` turn the colour off; a pipe never gets it. The numbered prompt for
  pipes and CI is unchanged.
- `evals/mcp_probe.py` is a wrapper over the shipped server, so the acceptance run
  measures what ships.
- **`lore init` says `unchanged`** for an instruction file or MCP config that
  already carries exactly what it would write, and leaves the file untouched instead
  of rewriting it and calling that `updated`.
- **The README is a front page again**, about a hundred lines, and the rest moved
  into `docs/`: `installation.md`, `agents.md` (every agent, one project, one
  specific agent — a Claude Code subagent, a Codex profile, environment only),
  `mcp.md`, `cli.md`, `configuration.md` (every environment variable read),
  `troubleshooting.md` (every `lore doctor` line), `faq.md` and `measurements.md`.
  Client configuration is checked against each client's documentation and linked.
- **Repository hygiene.** `CONTRIBUTING.md` (the README's contributing section and
  layout), `SECURITY.md` (private advisories), `CODE_OF_CONDUCT.md`, issue and
  pull request templates, Dependabot for Actions and pip, a social preview image,
  and package metadata: more keywords on PyPI and npm, a classifier per supported
  Python version, and a `Documentation` link.

### Fixed

- **`lore uninstall` and `lore doctor` now see `--scope project`.** In a repository,
  uninstall strips the managed block from the project's `CLAUDE.md`, `GEMINI.md` and
  `AGENTS.md` as well as the global files, and doctor checks those blocks — a dangling
  include or a stale paste — and counts them as connected. Before, a project-scope
  block survived uninstall and doctor reported nothing connected.
- **Codex's instruction file follows `CODEX_HOME`.** `init`, `uninstall` and `doctor`
  used `~/.codex/AGENTS.md` whatever `CODEX_HOME` said, while the MCP code already
  read `$CODEX_HOME/config.toml`; both now come from one place.

## [0.4.1] - 2026-09-19

`lore init` got an arrow-key menu and a question it was missing. Both came from the
first person to run it, whose reaction to typing a digit at a wall of text was that
it looked nothing like a normal command-line tool. That was fair, and the honest
answer was that fifteen tests checked whether the wizard did the right thing and not
one of them looked at what using it was like.

### Added

- **A third question: where this applies.** The wizard offered three files and all
  three were global. The screen said "applies to every project" and gave no
  alternative, which is a notice rather than a choice. Now the first question is
  "this project only" or "every project", and the project answer writes into that
  repository's own `CLAUDE.md`, `GEMINI.md` or `AGENTS.md`. `--scope project` is the
  same answer for a script, and it says so rather than guessing when there is no
  repository to scope to.
- **Arrow keys.** Up and down move, space ticks a box, enter confirms, escape skips,
  and the list is redrawn in place. Digits still work for anyone who ignores all of
  that. Where there is no terminal to put into raw mode — a pipe, a CI job, a test —
  the numbered prompt is used exactly as before, which is why `lore init --agent
  claude --yes` keeps working in scripts and why every existing test of these
  questions still drives the same path.
- Paths in the menus are shown as `~/…` rather than in full, so the rows stop
  wrapping and stay readable at a glance.

### Fixed

- The terminal was switched into raw mode per keypress, leaving it cooked in
  between. A key pressed in that window was echoed onto the screen as `^[[B` and
  then discarded, because `tty.setraw` defaults to `TCSAFLUSH`, which throws away
  queued input — so the menu looked broken and then waited forever for a key that
  had already been pressed. Raw mode is now held for the whole question and entered
  before the question is printed, closing the window entirely.

### Notes

Key handling is a pure function over byte sequences, including the two forms of
arrow escape that terminals send and the Windows two-byte form, because terminal
behaviour cannot be asserted from a test that has no terminal. Two pty tests cover
the wiring those cannot reach: one drives arrows through the menu directly, the other
drives the whole wizard.

## [0.4.0] - 2026-09-19

Read the first two entries before you upgrade. The second one describes a failure
that produces no error message at all.

### Your notes are safe

Nothing about `.memory/` changed — pages, frontmatter, the log and the index are
byte-compatible, and `lore search` finds every page you already have. There is
nothing to migrate and nothing to export.

### If you used the `@…/USE.md` include line, your agent will silently load nothing

That file lived in the skill directory, and the skill directory is gone. An `@path`
pointing at a file that does not exist produces **no error in any harness** — the
agent simply stops searching, and nothing connects that to the upgrade. If your
`CLAUDE.md` or `GEMINI.md` contains a line like

    @~/.agents/skills/project-memory/USE.md

it is now dead. Fix:

```bash
sh install.sh --uninstall      # takes out the old block; or edit the line out yourself
pipx install pagelore
lore init                      # writes the new block and offers the new line
```

`lore init` recognises the old marker and replaces that block rather than adding a
second one, so forgetting the first step costs you nothing. `lore doctor` reports
an include pointing at a file that is gone.

### If you pasted the block's text instead, you get a loud error

Codex and Cursor users pasted the text rather than an import. That copy still tells
the agent to run a script path that no longer exists, so the agent gets
`No such file or directory` and can tell you about it. Same fix: `lore init`, then
replace the pasted block.

### Installing it

```bash
pipx install pagelore          # Python, no Node needed
npm install -g pagelore        # Node, no pip needed — it vendors the Python
lore init
```

`lore init` writes the instruction block, then asks which agent should use it and
shows the exact line and file before changing anything. Its default connects
nothing. Inside a git repository it also asks whether this project's pages are
private or tracked.

`install.sh` and the `curl … | bash` one-liner still exist, because a published URL
cannot be recalled and deleting the file would pipe GitHub's 404 page into a shell.
They install nothing now: they print these commands, still run the old
`--uninstall` path, and exit 1 so a pipeline fails loudly. Scheduled for deletion
in 0.6.0.

### Why the name changed

The package is `pagelore` and the command is `lore` because `project-memory` and
`pm` are both already taken on PyPI **and** on npm, by unrelated products in the
same niche. Not churn — there was no free name to keep.

### Removed: plugin and extension installs

The skill directory, all six plugin manifests and the Gemini extension file are
gone; there is no Agent Skills packaging any more. If you installed it that way,
that install is separate and this release cannot reach it:

```
Claude Code   /plugin uninstall project-memory
Gemini CLI    gemini extensions uninstall project-memory
Codex, Cursor, Kimi   remove the directory you pointed them at
```

The marketplace entry is gone too, so `/plugin marketplace add Krowli/project-memory`
now 404s. Tag `v0.3.5` is the final plugin release and stays installable.

**This cost something measurable, and here is the number.** A registered skill
directory gave a harness a description to index, and that description alone made
the agent search before answering in **15 of 15** sessions with no instruction line
anywhere. With nothing registered and no line, it is **0 of 15**. So the packaging
was not dead weight; it was a working fallback for the user who installs and then
connects nothing. The recommended setup is 15/15 either way, which is why the trade
was made, and three things now cover the gap that did not exist before: `lore init`
runs at install time and offers the line, `lore doctor` calls an unconnected
install a fault rather than a neutral state, and a bare `lore` says so in one line.

### What you get for it

- The command an agent runs is `lore search "…"`, with no path in it. It is correct
  in every layout instead of in one of three. A user hit exactly this in 0.3.4: a
  project-scoped install, and the documented verification command answered
  `No such file or directory`. The instruction block carried three sentences
  explaining which of three layouts you might be in; they are deleted.
- You can grant an agent `Bash(lore:*)` instead of `Bash(python3:*)` — one program
  rather than arbitrary Python.
- Updates arrive with `pipx upgrade pagelore`. Twice this month a change landed on
  `main` and reached zero users because no manifest was bumped.
- The block that makes an agent search is refreshed by every `lore` invocation, so
  a new release does not need you to re-copy anything.
- `lore doctor` names the three states that used to be invisible: a dangling
  include, a stale pasted copy, a leftover skill directory.
- `lore uninstall` takes the block back out. `pipx uninstall` cannot, because it
  never learns about a file this program edited.

### Changed, under the hood

- One literal in `src/pagelore/__init__.py` is the version. It used to live in ten
  hand-edited places guarded by five drift tests; `npm/package.json` carries the
  only remaining copy, because npm cannot read a Python file, and both the packer
  and a test refuse a mismatch.
- The built distribution contains the program. Until now it never had: `py-modules
  = []` in `pyproject.toml` silenced an auto-discovery failure, and every published
  artefact held LICENSE, README, pyproject and ten test files. CI now opens the
  wheel and asserts the modules and data files are inside it, installs it with
  pipx on three operating systems, and uses it the way a user does.
- Seven tests that checked whether one hard-coded script path resolved in three
  documented install layouts are deleted, not replaced. That class of test cannot
  exist any more, which is the clearest single argument for the repackage.
- The 15 pages in this repository's own store had their `sources:` repointed by
  `tools/retarget_sources.py` rather than through `lore write`, because
  `write_page` unions sources and never removes one — amending through the command
  would have left every page citing both the live path and the dead one, exit 0,
  silently. `updated:` was not bumped: the content did not change that day, and the
  date feeds ranking.

### Added

- **`lore init`, `lore doctor`, `lore uninstall`.** Interactivity in `init` is an
  injectable parameter defaulting to `isatty()`, so the questions are tested in
  process with one pty test proving the default wiring. The shell installer this
  replaces shipped a dead prompt — a question placed after the value it decided —
  and it passed review because nothing could reach that branch.
- **`npm install -g pagelore`**, a shim that finds an interpreter and hands it the
  vendored Python. No pip, no `postinstall`, so `--ignore-scripts` and a corporate
  registry mirror both work. `python -m pagelore` exits 69 below the Python floor
  and the shim reads that as "try the next candidate", printing one message after
  it has tried them all and naming each. Candidate order is platform-specific
  because Windows has no `python3`. `PROJECT_MEMORY_PYTHON` is exclusive: a named
  interpreter that does not work fails loudly instead of falling back silently.
- **`evals/speed.py`**, so the timing table in the README is reproducible. The
  earlier figures came from an uncommitted script and are superseded rather than
  comparable. One search end to end, 90 pages: 52 ms warm, 76 ms with the index
  refused; 1 000 pages: 69 against 341 ms; 5 000 pages: 139 against 1 507 ms.
- **`evals/mcp_probe.py`**, a stdio MCP server exposing the two tools, and
  `evals/acceptance.py --pointer mcp|mcp+include` to run a real session against
  it. The CLI was chosen early and never measured against MCP; this settles it
  with numbers rather than opinion. Retrieval quality was never the question —
  the server calls the same functions — so what was measured is whether an agent
  reaches for the memory more reliably when the tools are in its tool list.
  Fifteen sessions per arm: the instruction line 15/15, MCP on Claude Code's
  default settings **0/15**, MCP with `ENABLE_TOOL_SEARCH=false` 15/15, both
  together 15/15. The zero is Claude Code deferring MCP tools behind tool search
  by default, so the single advantage MCP was supposed to have is absent out of
  the box. MCP is not shipped; the probe stays so the question can be re-run.

## [0.3.5] - 2026-09-19

The final release installed as a copied skill directory. Nothing in the code
changed; this tag exists so that the install instructions published for 0.3.x keep
resolving to something, instead of to a 404, after the packaging is deleted.

**The program is now installed with a package manager, and the command is `lore`:**

```bash
pipx install pagelore          # or: npm install -g pagelore
lore init
```

Your pages are safe and unchanged — `.memory/` is byte-compatible and `lore search`
finds every page you already have.

If you installed 0.3.x, remove it before or after installing the new one; the two
do not interfere, but leaving the old block in your agent's instruction file leaves
an `@path` pointing at a directory that is about to disappear, and a dead `@path`
produces no error in any harness. The agent just stops searching.

```bash
sh install.sh --uninstall                     # the shell install
/plugin uninstall project-memory              # Claude Code
gemini extensions uninstall project-memory    # Gemini CLI
```

See the 0.4.0 notes for the full upgrade path and for why the name changed:
`project-memory` and `pm` were both already taken on PyPI and on npm.

## [0.3.4] - 2026-09-19

### Added

- **The install asks which agents should use it, and writes the line itself.**
  Printing instructions and leaving the user to carry them out was the step
  people finished the install without taking. It now lists Claude Code, Gemini
  and Codex with the file each one reads, shows the exact path and the exact
  line before touching anything, and writes only after a confirmation. What it
  writes is fenced by marker comments: a second install replaces that block
  rather than stacking another copy, `--uninstall` takes it back out, and
  everything the user wrote around it survives. Declining prints the line to
  add by hand, which is what it used to do unconditionally.

### Fixed

- **The "install here or everywhere" question could not change anything.** It
  ran after the destination had already been worked out, so both answers led to
  the same directory. It now runs before, and a pty-driven test asserts that
  answering "only this one" puts the skill in the repository and not in the
  home directory — the questions are interactive, so a test that pipes stdin
  proves nothing about them.

## [0.3.3] - 2026-09-19

### Added

- **The install ends by naming the line that makes it work.** It printed where
  the files went and stopped, so someone who ran one command was finished and
  had no way to know they were not: the scripts sit on disk and the agent never
  reaches for them until the instruction block is in its configuration. The
  final message now gives that line with the path filled in for the install it
  just did, the file to put it in for each agent, and the command that undoes
  the whole thing.
- **It asks whether to install for every project or only for this one**, when
  there is a terminal to answer on and a repository under foot for the second
  option to mean anything. Before, standing inside a project and running it with
  no flags installed globally in silence, which reads as a script with no
  opinion rather than one that made a choice. Piped through CI it stays global
  without stalling.

## [0.3.2] - 2026-09-19

### Added

- **`./install.sh --uninstall`.** There was no way to take the skill off a
  machine, so the only instruction anyone could be given was a pair of
  `rm -rf` typed by hand, next to a directory of the user's own pages. It
  removes the skill directory and the symlink the install made, names every
  path it deletes, and leaves three things while saying so: the `.memory/`
  stores in your projects, the line you added to your agent's instruction file,
  and any agent definition you wrote. A symlink is removed only when it
  resolves to the directory being deleted, so a link of yours pointing
  elsewhere survives. It runs before the git and Python checks, because taking
  a program off a machine must not depend on the toolchain that put it there.
  README documents it.

## [0.3.1] - 2026-09-19

### Changed

- **README documents how an update actually reaches a user**, per install path,
  because it does not reach them by itself: Claude Code leaves auto-update off
  by default for third-party marketplaces, and a `curl` install has no update
  channel at all beyond `./install.sh --check`. Everything in 0.3.0 that came
  after the tag — the shipped instruction block and the 3.9 floor — was
  unreachable for anyone who had already installed, because a user only
  receives an update when the manifest version changes. Hence this release.

- **The Python floor drops from 3.11 to 3.9**, which is what a stock macOS
  already ships — until now `install.sh` refused the interpreter at
  `/usr/bin/python3`, so the skill would not run on a Mac without a Python
  installed first. The floor was never earned: the five scripts carry no 3.10 or
  3.11 construct, all of them already use `from __future__ import annotations`,
  and the whole suite passes under 3.9.6. CI now runs 3.9 on Linux and Intel
  macOS alongside 3.11 and 3.13 (GitHub publishes no 3.9 build for arm64 macOS
  or Windows), and a test fails if the four places that declare the floor drift
  apart. Windows, which ships no Python at all, stays a documented prerequisite.
- README rewritten around the three questions people ask first: is the skill
  global or local (global by default, the store is always per project), how to
  make an agent keep the memory without hooks (one paste into the agent's
  global instruction file, paths per vendor docs), and what was measured, with
  every table and the command that reproduces it.
- The calibration medians quoted in `SKILL.md` and `references/retrieval.md`
  (5.32 against 5.29) predated the FTS5 index; re-measured with the current
  harness they are 9.93 against 8.73. The conclusion is unchanged: a score
  threshold cannot tell an answerable question from an unanswerable one.

## [0.3.0] - 2026-09-16

### Added

- **`memory_search.py --touching PATH`** — the pages whose `sources` cite that
  file, or anything under that directory, come first, marked `▸ touches <path>`,
  with or without query words. `sources` was the one field every page must carry
  and the one field ranking never read. Measured on a new 50-query `touching`
  set in `evals/corpus.json`: typing the path as words puts the right page first
  38% of the time (nDCG@10 0.545); the flag puts it first by construction
  (0.986, paired +0.441 [+0.349, +0.539]). Without the flag nothing changes,
  and the existing tables did not move. Sources are not in the index, so a
  `--touching` search reads every page.
- **The write gate runs on read.** A page that arrived around `memory_write.py`
  and is under 200 characters is not ranked; search names it on stderr and in
  `--json` so it can be rewritten through the script. A page with no sources is
  shown, marked `⚠ no sources`. `MIN_BODY` moved to `memory_lib` so writer and
  reader share one floor. Search runs on every agent the skill is installed in,
  which is what makes it the place for the check.
- Every log line carries the session id Claude Code exports to the Bash tool
  (`CLAUDE_CODE_SESSION_ID`), and `memory_stats.py` reports sessions, sessions
  that searched and never wrote, and writes per session — the write side's
  "did it happen", collected by the scripts themselves.
- `evals/acceptance.py`: a real session of the agent you name, a question only
  the store answers, and a check of the store's log for the search. The only
  proof that an agent uses the memory unprompted; run it per harness.
- `docs/research/`: primary-source notes behind decisions, starting with how
  superpowers stays portable across thirteen harnesses.

### Removed

- **The three Claude Code hooks.** SessionStart announced the memory,
  PreToolUse denied a hand-written page, Stop reminded a session that changed
  files and wrote nothing — and every one existed on one harness while the
  skill claims to work on any. `hooks/` is gone, `install.sh` no longer writes
  `settings.json` (`--no-hook` with it), and the Cursor manifest declares no
  hooks. Announcing the memory is the skill `description`, the context files
  and the `AGENTS.md` snippet, the way superpowers runs on Codex, Devin and
  Grok; the gate moved to read; the reminder became a finishing rule in
  `SKILL.md` and the pointer files. See `.memory/scripts-carry-the-contract-not-hooks.md`.

### Changed

- `evals/dense_probe.py --static MODEL` runs the hybrid over a model2vec static
  embedding model and reports the cold process cost next to the shipped search.
  Measured with three `potion` models: no hybrid gain clears zero, and the
  cheapest cold start is 527 ms against 86 ms for the whole shipped search — the
  cheap form of the embedding idea is refused on the same grounds as the
  expensive one. See `references/retrieval.md`.

## [0.2.2] - 2026-08-18

### Fixed

- **The hooks were registered as `python3`, which is not a command Windows has.**
  Its installer puts `python`, `py` and `pymanager` on PATH; `python3` exists only
  as an optional versioned alias. So on Windows both hooks silently never ran —
  the agent was never told it had a memory, and the write guard blocked nothing,
  which is precisely the hole it exists to close. `install.sh` now resolves a
  working interpreter (`python3`, then `python`, then `py -3`, each checked for
  3.11+) and writes that one into `settings.json`; `--interpreter` forces a
  choice. It also no longer accepts a Python below 3.11, which the old existence
  check did — on macOS that is `/usr/bin/python3`, still 3.9.
- **The suite could not have caught it.** Every hook test invoked `sys.executable`
  and never the string the installer writes, and `actions/setup-python` puts a
  `python3` shim on Windows runners, so both layers hid it. A test now takes the
  command out of the generated `settings.json` and runs it through a shell.
- `hooks/hooks.json` cannot branch per platform, so the plugin path still
  hard-codes `python3`. That limitation is now in the README rather than in a
  surprise, with a test that keeps the two in sync.

## [0.2.1] - 2026-08-18

### Fixed

- **Contended writes terminated a sibling writer on Windows.** The lock decides
  staleness by asking whether the owning process still exists, and used
  `os.kill(pid, 0)` to ask. That is a liveness probe on POSIX and a kill on
  Windows, where every signal but CTRL_C and CTRL_BREAK is delivered by calling
  TerminateProcess. CI caught it as a hung test run, which was the mild version of
  the symptom. Liveness now goes through a platform check — `OpenProcess` on
  Windows, distinguishing "no such process" from "access denied" — and falls back
  to the mtime rule wherever the answer is unknowable. A test pins `os.kill` to
  that one guarded probe.
- The host identity in a lock file came from `os.uname()`, which does not exist on
  Windows, so every lock there was written and compared as `unknown-host`.
- **A concurrent search made a write fail outright on Windows.** `os.replace`
  replaces a file regardless of who has it open on POSIX and refuses with
  WinError 5 while any reader holds a handle — and a search reading the store is
  exactly that reader. The replace now retries for a few seconds instead of
  raising.
- **A process that had exited was reported as running on Windows.** `OpenProcess`
  succeeds for as long as anyone holds a handle to a dead process, so the handle
  alone means nothing; the exit code decides, with 259 (`STILL_ACTIVE`) meaning
  running.
- **17 of 200 concurrent log lines went missing on Windows.** One `O_APPEND` write
  is atomic against other processes on POSIX and is not on Windows; appends within
  a process are now serialised.
- Tests that depend on POSIX file modes, `mkfifo` or `geteuid` are skipped on
  Windows rather than faked, so the Windows run reports what it actually covered.

## [0.2.0] - 2026-08-18

An audit of the skill against its own claims. Four ways a re-run could destroy
part of a page, a store that could take retrieval down or leak a file it never
owned, a write gate with an unguarded side door, and a contract naming a script
path that existed in one install mode out of four.

### Fixed

- **Re-running a write no longer loses content.** `## ` lines inside a code fence
  are content, not headings — the previous splitter deleted the closing fence and
  everything after it. A body with no heading at all used to be dropped whenever
  the page already had lead-in prose. Sections are replaced in place instead of
  moving to the end of the file, so a one-section amendment reads as one in
  `git diff`. Each of these exited 0 and logged a successful write.
- **Frontmatter fields the tooling does not own are preserved.** Rebuilding from a
  fixed whitelist silently deleted anything else the page carried, which blocked
  extending the format at all.
- **The 200-character floor applies to the resulting page, not to the increment.**
  Recording "this was reversed in June, here is why" against an existing page was
  refused — the cheapest and most valuable write in the system.
- **Concurrent writes to one slug no longer lose sections.** An advisory per-page
  lock plus `os.replace`; measured before the fix, twelve to twenty parallel
  writers lost up to 16 of 20 sections, all exiting 0. A reader can no longer
  observe a half-written page, and log lines cannot interleave.
- **One undecodable page no longer kills every search in the project.** Pages are
  read with `errors="replace"`.
- **NFD text is findable.** `\w+` does not match combining marks, so the NFD form
  of `ёлка` tokenised as `['е', 'лка']` and recall across an NFC/NFD boundary was
  zero — on macOS, which produces that form. Text is normalised to NFC and folded
  with `casefold()`, which also covers `STRASSE` / `straße`.
- **A search no longer creates a store or edits `.gitignore`.** Logging a miss used
  to dirty the working tree of a repository that never opted in. The write path
  still creates and shields the store it needs, including on a refusal.
- **A page symlinked outside the store is ignored.** `ln -s ../.env
  .memory/env-notes.md` made an ordinary search rank and print a secret.
- **Only top-level `*.md` files are indexed.** `mkdir archive; mv` used to leave the
  page indexed and return two hits with the same slug.
- **A store that is a dangling symlink is refused with a `FIX:` line** instead of a
  raw `FileExistsError` — the shape `install.sh --store home` produces if its
  target is gone.
- `memory_stats.py` reports a real median for even counts and tolerates a log line
  from another writer.
- **Every command in `CLAUDE.md`, `AGENTS.md` and `GEMINI.md` now runs.** All three
  hard-coded `.agents/skills/…`, which exists only after `install.sh --project` —
  not in a clone, which is the case `CLAUDE.md` says it exists for. A test extracts
  every command from those files and checks it.
- `install.sh --help` no longer truncates mid-table, hiding two store modes.
- A missing `--kind` is logged as `no_kind` rather than sharing `bad_kind` with an
  invalid one; the two call for opposite fixes.

### Added

- **The runtime knows its own version.** `--version` on every script, and the
  session hook tells the agent which version the project is running. A `curl`
  install has no package manager to ask, so until now neither the user nor the
  agent could tell 0.1.0 from 0.2.0 on disk.
- **`install.sh` installs the latest released tag**, not the tip of `main`, so an
  install is reproducible and a version number means something.
  `PROJECT_MEMORY_REF` still takes a branch or a specific tag, and
  `install.sh --check` reports what is installed against what is released without
  installing anything. A test now guards the `--help` line range, which had
  silently truncated once already.

- **A reproducible evaluation, in the repository.** `python3 evals/run.py --by-type`
  over 90 pages and 270 queries with paired bootstrap intervals, plus an ambiguous
  set and an unanswerable set. `evals/gate_value.py` measures what the write gate
  is worth by putting the stubs it refuses back into the corpus. Nothing in
  `references/retrieval.md` is now argued from figures a reader cannot re-run.
- **A persistent SQLite FTS5 index** (`memory_index.py`), and it is a cache the
  search is allowed to ignore. End to end, as a shell invocation: 235 ms → 99 ms at
  90 pages, 1887 ms → 174 ms at 1000, 4637 ms → 196 ms at 5000. The ~5000-page
  ceiling the documentation used to name is gone. It lives in the cache directory
  rather than the store, uses no WAL, rebuilds whole rather than repairing, elects
  one builder without waiting, and falls back to reading the markdown on any error
  at all. `PROJECT_MEMORY_NO_FTS5=1` forces the fallback, and CI now runs the whole
  suite twice so that path cannot rot.
- `--json` reports `served_by`, so two agents served by different paths can explain
  a difference in tail ordering rather than wondering about it.

### Fixed while measuring

- **Turkish `İ` was unfindable by its ASCII spelling**: `casefold` turns it into
  `i` plus a combining dot, which matches nothing anyone types.
- **The evaluation's own FTS5 baseline was misconfigured** — without `tokenchars
  '_'` the pre-tokenised round trip changed 73 of 486 texts — and `bm25()` weights
  are positional over every column, so passing two weights for a three-column table
  gave the title weight to the unindexed slug and left the title at 1.0. The
  title-weight regression test caught the second one.
- **The supersession tests were still weak.** The fixture is now an unlinked
  control pair: without the link the obsolete page must rank first, and adding the
  link alone must reverse it. The earlier version guarded a score comparison that
  the ranker change quietly invalidated.

### Changed

- `references/retrieval.md` reports measured numbers with paired intervals, states
  what the harness cannot tell you, and records the negative result it produced:
  no score or word-overlap threshold can separate a question the store can answer
  from one it cannot (top-hit medians 5.32 against 5.29). `SKILL.md` now tells the
  agent that a result list is not evidence that an answer exists — the previous
  wording, "if search returns nothing relevant, say so", described a case that
  almost never happens.

- **`--supersedes <slug>`.** The replaced page is stamped `status: superseded` and
  `superseded_by:`, scored at half its BM25F score and marked in every result
  line. Ranking previously had no recency or authority term and tied
  alphabetically, so a reversed decision could outrank the decision that reversed
  it — the failure the README opens with.
- **A `PreToolUse` hook that denies a hand-written page** and names
  `memory_write.py` instead. "Writes are refused, not requested" was itself a
  request while the ordinary Write tool could walk around the validator. Escape
  hatch: `PROJECT_MEMORY_ALLOW_HAND_EDIT=1`.
- **Ranking regression tests.** `W_TITLE` could be set from 5 to 0 — the parameter
  the documentation calls the one that matters — and the whole suite stayed green.
- Snippets follow the query instead of being the page's first 100 characters, and
  every result line carries the `updated` date; the header line carries the store's
  absolute path, so the documented `cat` works from any directory.
- `.memory/` in this repository, tracked on purpose. The project had none, across
  fifteen commits of exactly the work it says to record.
- The session hook fires on `resume` as well, which the test named for it did not
  actually cover.

- The documented heredoc terminator is `PMEOF`, not `EOF`: a page documenting
  heredocs ended its own body early and the shell executed the rest of the text.
- `references/page-format.md` matches the write path — `kind` is required and one
  of four values, `sources` is required, and `note` is gone from both the reference
  and the shipped template.
- `references/retrieval.md` states that the benchmark's artifacts are not in this
  repository, so its figures are reported rather than reproducible; corrects the
  stub-size units; scopes the latency table to one machine and page size; and
  replaces the claim that `grep` is never cheaper with what it actually is — faster,
  and not an alternative, because it returns an unranked list.
- README: the injection is ~1.8 KB rather than ~1.3 KB, CI runs on `main` and pull
  requests rather than every push, a user-scope install neither asks about nor
  creates a store, and Contributing names all eight files carrying the version.
- The read trigger names a class of claim instead of a list of question
  phrasings. Agents read `"why…"` / `"what did we decide…"` as exhaustive and
  answered "what do you know about this project" straight from `AGENTS.md`,
  never searching. It now fires before stating anything about the project —
  what it is, what it does, how a part works, why it is that way.
- The session hook, `SKILL.md` and the three context files say explicitly that
  `AGENTS.md` / `CLAUDE.md` / `README.md` already in context are not a substitute
  for the search: they carry instructions rather than reasons and they drift,
  while a page stays dated and sourced. Both surfaces also name what does *not*
  need a search — a command, a typo, a rename, a file the user named, general
  programming questions — so the wider trigger does not become a search before
  every turn.

### Fixed after an independent audit of the fixes below

The changes above were then audited by agents whose task was to break them. What
they found, all of it now covered by a test that fails when the fix is removed:

- **`--supersedes` copied a symlinked file into the store.** Stamping the replaced
  page walked through its path, so `ln -s ../.env .memory/env-notes.md` — blocked
  on the read path — was read and rewritten as a real page containing the secret,
  which the next search then printed. The write path now refuses to touch anything
  that is not a contained regular file.
- **A nested ```` fence still exposed a quoted heading.** The fence pattern matched
  exactly three backticks, so the first inner ``` closed a longer outer fence —
  and quoting a memory page, the case the fix was written for, requires exactly
  that. Fences are now three *or more* characters, closed CommonMark-style.
- **A repeated `## ` header in an incoming body lost its first copy** on a merge,
  because the incoming sections were built as a dict. Introduced by the in-place
  replacement fix. Same-header chunks are joined, and only the first stored
  occurrence is replaced, so a page with two identical headers is no longer
  filled with the same text twice.
- **An orphan lock defeated the locking.** A lock left by a killed writer was not
  stale for thirty seconds, so every other writer stalled for the full timeout and
  then deleted whatever lock it found — including live ones, losing 2 to 4 of 10
  writers' sections. Staleness is now decided by asking whether the owning process
  still exists, and a live holder's lock is never removed.
- **One hostile entry could take down every search**: a directory named `notes.md`,
  a broken symlink, an unreadable file — and a FIFO did not fail the search, it
  hung it forever. Only readable regular files are indexed now, and the test for
  it runs in a subprocess with a timeout so a regression fails CI instead of
  hanging it.
- **The write guard was trivially bypassable**: the extension check was
  case-sensitive, so `.memory/page.MD` was allowed and clobbers `page.md` on a
  case-insensitive filesystem; `page` with no extension was allowed too; and the
  documented `--store home` mode has no `.memory` in its path at all, so it was
  entirely unguarded. It now covers every file in a store, resolves symlinks, and
  stops over-blocking `.memory/../src/x.ts`.
- **The supersession tests were vacuous.** The whole mechanism could be deleted and
  the suite stayed green, because both fixture pages had the same title and body.
  The fixture now asserts that it is a real inversion before testing the fix.
- **The session-hook budget was only ever measured from the short in-repo path**; a
  normal install location pushed it to 2201 characters against its own 2000 limit.
  The text is shorter and the prose is bounded separately from the path.
- Self-supersession and supersession cycles are refused; an empty `--body` is
  refused rather than silently bumping `updated:`; a read-only store produces a
  refusal instead of a traceback; a killed write leaves no `.tmp` behind; a title
  ending in a quote no longer loses that character on every rewrite; and
  `memory_stats.py` reports a true median.

## [0.1.0] - 2026-08-08

### Added
- `project-memory` skill (`SKILL.md`) with read-before-answer and
  write-after-work workflows.
- `memory_search.py` — ranked search over the markdown store.
- `memory_write.py` — create/section-merge pages with stable frontmatter.
- Claude Code plugin and marketplace manifests.
- Test suite covering search, writing, frontmatter tolerance and manifests.

[Unreleased]: https://github.com/Krowli/pagelore/compare/v0.8.3...HEAD
[0.8.3]: https://github.com/Krowli/pagelore/compare/v0.8.2...v0.8.3
[0.8.2]: https://github.com/Krowli/pagelore/compare/v0.8.1...v0.8.2
[0.8.1]: https://github.com/Krowli/pagelore/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/Krowli/pagelore/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/Krowli/pagelore/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/Krowli/pagelore/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/Krowli/pagelore/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/Krowli/pagelore/compare/v0.4.1...v0.5.0
[0.3.4]: https://github.com/Krowli/pagelore/compare/v0.3.3...v0.3.4
[0.3.3]: https://github.com/Krowli/pagelore/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/Krowli/pagelore/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/Krowli/pagelore/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Krowli/pagelore/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/Krowli/pagelore/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/Krowli/pagelore/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Krowli/pagelore/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Krowli/pagelore/releases/tag/v0.1.0
