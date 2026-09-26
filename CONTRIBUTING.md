# Contributing

Thanks for looking. Bug reports, measurements and fixes are all welcome; open an
issue first for anything larger than a fix, so the approach can be agreed before
the work.

## The one rule

**No proposal lands without a number from `evals/` or a failing test it fixes.**
That rule is why two features that measurably improve retrieval are refused (see
[measurements](docs/measurements.md#embeddings-measured-and-refused)) rather than
shipped, and it applies to the maintainer too.

## Setup

```bash
git clone https://github.com/Krowli/pagelore && cd pagelore
make dev          # .venv: editable install, pytest and ruff.
                  # The `lore` already on PATH may be a released build; the one
                  # that tracks this tree is .venv/bin/lore.
make test         # pytest on both retrieval paths, then ruff — both pytest runs
                  # have to pass, the second covers the scan ranker CI never runs
bash tools/smoke.sh   # or: make smoke. Build the wheel, install it in an
                  # isolated environment, and run it end to end exactly as CI's
                  # install-smoke does — the release path rehearsed locally,
                  # nothing published and nothing on this machine touched.
.venv/bin/lore dev    # the same commands in a console; --sandbox rehearses them
                  # against a throwaway store and a fake HOME. A bare `lore` on
                  # a real terminal opens the same console. `--panes` swaps the
                  # prompt for a full-screen view: ask a question or type
                  # a command, watch it run in-process in the transcript — search
                  # hits as readable cards — `/` for the centred, hint-annotated
                  # command picker, `o` to open the top hit (q back).
```

Before a pull request:

- `pytest` and `PAGELORE_NO_FTS5=1 pytest` both pass (`make test` runs both
  and ruff);
- `ruff check .` is clean — line length 100, target `py39`;
- `CHANGELOG.md` has an entry under `[Unreleased]`;
- the runtime stays standard library only, and Python 3.9 compatible;
- an architectural decision, a non-obvious fix or a contract change is recorded
  as a page with `lore write` (this repository's `AGENTS.md` says how).

## Layout

```
src/pagelore/              the program
  cli.py                   the dispatcher: one prefix router, not argparse subcommands
  search.py index.py       ranking, and the FTS5 index that is a cache
  write.py lib.py stats.py the write gate, the store, the log reader
  init.py doctor.py        the wizard, and the detector for what has gone silently wrong
  uninstall.py             takes back out what init wrote
  mcp.py                   the same memory as two MCP tools over stdio, when chosen
  dev.py                   the console: the same commands, --sandbox on a throwaway store
  panes.py                 the full-screen view behind --panes: ask box, transcript with search hits as cards, a centred / picker with hints, a bare search waits for its query on the same line, UTF-8 input; a pure model, curses only for drawing
  instructions.py          renders and refreshes the block an agent reads every turn
  data/AGENT.md            that block — the measured 15/15 text
npm/                       the Node route: a shim, plus src/pagelore vendored at pack time
docs/                      user documentation, page format, retrieval detail, measurements,
                           and primary-source research notes
evals/                     reproducible measurement: corpus, queries, scorer, speed,
                           an MCP probe, and a real-agent acceptance run
tests/                     pytest suite, stdlib only
tools/                     smoke.sh: build the wheel, install it in isolation, run it
Makefile                   `make dev/test/smoke` — the local loop, spelled once
.memory/                   this project's own pages, tracked on purpose
install.sh                 retired; it now only prints the new commands and uninstalls 0.3.x
```

CI runs the suite on Ubuntu, macOS and Windows against 3.11 and 3.13, and on 3.9
on Linux and Intel macOS. It also opens the built wheel and asserts the program is
inside it. That test exists because for months it was not: `pyproject.toml`
declared `py-modules = []` and every published distribution contained LICENSE,
README, pyproject and ten test files. Nothing looked, so nobody knew.

## Releasing

The version is one literal in `src/pagelore/__init__.py`. `npm/package.json`
carries the only copy, because npm cannot read a Python file, and both the packer
and a test refuse a mismatch. To release: bump that literal and the npm one, add a
`CHANGELOG.md` section, regenerate `AGENTS.md` (it carries a version stamp; see
`CLAUDE.md`), then tag.

```bash
git tag -a v0.5.0 -m "pagelore 0.5.0" && git push origin main v0.5.0
```

The tag triggers the release workflow: it checks the tag against the code and the
changelog, opens the wheel, publishes to PyPI through trusted publishing, then to
npm, then cuts the GitHub release with that changelog section as the notes. PyPI
goes first because a PyPI version can never be replaced and an npm one can.
Rehearse the whole path against TestPyPI with a `workflow_dispatch` run first — a
failed publish burns a version number.

## Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Security
issues go through [SECURITY.md](SECURITY.md), not public issues.
