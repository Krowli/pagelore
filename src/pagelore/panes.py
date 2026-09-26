"""`lore dev --panes` — the screen that was asked for: an opencode-shaped TUI, opt in.

The console's default is the line editor, and that decision stands: a redrawn
widget holds raw mode for the whole session and needs a pty test that races,
where the line editor is pipe-drivable. The panes are an *extra* screen behind
`--panes` and the internal `panes` command, and they borrow the opencode screen's
shape one to one — because that is the shape that was asked for, twice:

- fresh: a logo, a big "Ask anything…" box, a hint bar with the path, the
  shortcuts and the "model" tag;
- once commands have run: a transcript — every command echoed like the prompt
  with its output underneath — and the field shrunk to the bottom line. `/` (or
  ctrl+p) *always* opens a centred command picker with one hint per command;
  `o` opens the top hit of the last search; `↑` walks history. Enter on a bare
  `search` (no query yet) simply leaves `lore > search ` for the query — the
  user's own text stays on the main screen, only the query is missing, and no
  argparse usage ever dumps; the field takes UTF-8 (the store's corpus is
  bilingual), including in the picker's filter.

Commands run in-process through the same `cli.main` the CLI runs, so the output
and the `exit N` codes are bit-for-bit what an agent would see from the same
position — and then the transcript renders the well-known outputs readably:
a `search` turn shows one card per hit (slug, title, the matched window dim
underneath, score and date on the right) instead of the CLI's wrapped prose,
with the raw bytes still stored on the turn. `curses` is POSIX and the screen
needs a real terminal; where either is missing, `--panes` says so and falls
back to the line editor, so a pipe driving `lore dev --panes` still reads lines.

What a key decides is a pure function on `State`, so the bulk of the screen is
tested the way the line editor is: called directly, no terminal — including the
session model, which turns a command into a transcript turn. Only the draw loop
touches curses, and one pty test proves the raw screen draws, runs commands from
the box, opens the picker from a non-empty field, and answers keys. Commands
that must own the terminal (`mcp`, the init wizard, `edit`) are refused from the
field, not half-run.
"""
from __future__ import annotations

import contextlib
import io
import os
import shlex
import sys
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path

try:
    import curses
except ImportError:  # pragma: no cover — Windows ships no curses
    curses = None  # type: ignore[assignment]

from . import __version__
from .lib import Page
from .search import search, snippet

DEFAULT_K = 15
# The CLI's own `search -k` default: the card count must equal the count the
# raw header line promises, so the transcript never shows two different numbers.
SEARCH_K = 10

# Commands that must own the terminal: a stdio server, a wizard, an editor.
# They are refused from the field and run outside the panes, not half-run here.
TERMINAL_COMMANDS = ("mcp", "dev", "edit", "panes")

# The picker, `/` or ctrl+p: every command worth offering, with the one-line
# hint that makes the menu readable before you know the names by heart.
PICKER_HINTS: dict[str, str] = {
    "search": "ranked search over the pages",
    "show": "one page, by slug",
    "list": "every page, newest first",
    "write": "write or amend a page",
    "edit": "a page in $EDITOR",
    "rm": "delete one, logged",
    "stats": "what the store has been doing",
    "init": "the wizard; --yes to skip it",
    "doctor": "what has gone silently wrong",
    "uninstall": "take the memory out",
    "mcp": "the memory as two MCP tools",
    "version": "pagelore version",
    "dev": "the console commands",
    "help": "the command list",
    "clear": "clear the transcript",
    "exit": "leave the screen",
    "panes": "the screen you are in",
}
PICKER_COMMANDS = tuple(PICKER_HINTS)

# Attribute tokens on transcript lines, mapped to curses in the draw loop —
# so the pure model never imports curses. `ERROR` is a failed run's exit line.
NORMAL = 0
BOLD = 1
DIM = 2
ERROR = 3

# Block-letter "LORE", centred, five pixels tall — the logo borrowed from the
# opencode empty state. One terminal row per pixel row, no halves needed.
LOGO = [
    "  ".join(rows)
    for rows in zip(
        ("█    ", "█    ", "█    ", "█    ", "█████"),  # L
        ("█████", "█   █", "█   █", "█   █", "█████"),  # O
        ("████ ", "█   █", "████ ", "█  █ ", "█   █"),  # R
        ("█████", "█    ", "████ ", "█    ", "█████"),  # E
    )
]


@dataclass
class Turn:
    """One command and its captured run, as the transcript shows it.

    `output` is bit-for-bit what `cli.main` printed, kept so the fidelity checks
    hold and the raw run can always be rendered. `hits` is the ranked result of
    a plain `search` (no flags), letting the transcript draw one card per hit
    instead of the CLI's wrapped prose.
    """

    cmd: str
    rc: int
    output: str
    hits: list[tuple[float, Page]] | None = None


@dataclass
class State:
    """What the screen remembers between keys. All fields are plain data."""

    turns: list[Turn] = dc_field(default_factory=list)
    field: str = ""
    cursor: int = 0
    history: list[str] = dc_field(default_factory=list)
    hist_idx: int | None = None
    picker: bool = False
    picker_idx: int = 0
    hits: list[Page] = dc_field(default_factory=list)
    follow: bool = True
    view_top: int = 0


def query_rows(store: Path, query: str) -> list[Page]:
    """The same ranked search the CLI runs; nothing matches an empty query."""
    if not query:
        return []
    return [page for _, page in search(query, store, k=DEFAULT_K)]


def field_insert(state: State, ch: str) -> None:
    state.field = state.field[:state.cursor] + ch + state.field[state.cursor:]
    state.cursor += len(ch)


def field_backspace(state: State) -> None:
    if state.cursor > 0:
        state.field = (state.field[:state.cursor - 1]
                       + state.field[state.cursor:])
        state.cursor -= 1


def field_cursor(state: State, delta: int) -> None:
    state.cursor = max(0, min(len(state.field), state.cursor + delta))


def open_picker(state: State) -> None:
    state.picker = True
    state.picker_idx = 0


def picker_items(state: State) -> list[str]:
    """The picker's list, narrowed by the text typed since `/`."""
    query = state.field
    return [c for c in PICKER_COMMANDS if c.startswith(query)]


def picker_window(state: State, limit: int) -> tuple[list[str], int, int, bool, bool]:
    """The slice of the picker to draw, with the cursor row inside it.

    The window slides so the cursor is always visible; `limit` is the most rows
    the panel fits. Returns (shown, cursor row, total, has more above, has more
    below) — pure, so the menu has a test without a terminal.
    """
    items = picker_items(state)
    if not items:
        return [], 0, 0, False, False
    idx = state.picker_idx % len(items)
    if limit <= 0:
        return items, idx % len(items), len(items), False, False
    start = max(0, min(idx - limit + 1, len(items) - limit))
    shown = items[start:start + limit]
    return shown, idx - start, len(items), start > 0, start + len(shown) < len(items)


def picker_fill(state: State) -> None:
    """Enter in the picker: fill the field with the picked command's name."""
    items = picker_items(state)
    if items:
        picked = items[state.picker_idx % len(items)]
        state.field = picked + " "
        state.cursor = len(state.field)
    state.picker = False


def history_back(state: State, delta: int) -> None:
    """Walk the command history with ↑/↓ once the field was recalled from it.

    Starts from the newest entry, or from the current position when still inside
    a recall — so repeated ↑ keeps walking back. Fresh typed text is left alone:
    ↑ must not clobber a line the user is composing.
    """
    if not state.history:
        return
    if state.hist_idx is None and state.field:
        return  # fresh text, not a recall
    if state.hist_idx is None:
        state.hist_idx = len(state.history) - 1 if delta < 0 else 0
    else:
        state.hist_idx += delta
    if state.hist_idx < 0:
        state.hist_idx = 0
    if state.hist_idx >= len(state.history):
        state.hist_idx = None
        state.field, state.cursor = "", 0
        return
    state.field = state.history[state.hist_idx]
    state.cursor = len(state.field)


def _needs_real_terminal(argv: list[str]) -> str | None:
    """Why a command must not run from the field, or None if it may."""
    name = argv[0]
    if name in TERMINAL_COMMANDS:
        return (f"{name} owns the terminal — run it outside the panes,"
                " in `lore dev` or the shell")
    if name == "init" and "--yes" not in argv:
        return "init is a wizard — pass --yes (or run it outside the panes)"
    return None


def run_command(state: State, store: Path, *, cwd: Path,
                sandbox: Path | None = None,
                home: Path | None = None) -> tuple[int, str]:
    """Run the field's command in-process, captured; return (rc, output).

    The same `cli.main` the CLI runs, with stdout and stderr captured — so the
    output, the `FIX:` lines and the exit code are exactly what an agent would
    see from the same position. In a sandbox the store, HOME and cwd point at
    the throwaway tree, mirroring what the line editor's children get.
    """
    argv = shlex.split(state.field)
    if not argv:
        return 0, ""
    why = _needs_real_terminal(argv)
    if why:
        return 1, why

    from . import cli
    out, err = io.StringIO(), io.StringIO()
    overrides: dict[str, str] = {}
    if sandbox is not None:
        overrides["PAGELORE_DIR"] = str(store)
        if home is not None:
            overrides["HOME"] = str(home)
            overrides["USERPROFILE"] = str(home)
    saved: dict[str, str | None] = {k: os.environ.get(k) for k in overrides}
    for k, v in overrides.items():
        os.environ[k] = v
    old_cwd = os.getcwd()
    try:
        if cwd != old_cwd:
            os.chdir(cwd)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = cli.main(argv)
            except SystemExit as exc:
                # argparse validation (a query-less `search`, a slug-less `rm`,
                # `--version`, `--help`) raises SystemExit instead of returning.
                # A child would just exit with that code; in-process it must
                # become the turn's rc, or the whole screen dies with it.
                rc = exc.code if isinstance(exc.code, int) else 1
    finally:
        os.chdir(old_cwd)
        for k in saved:
            if saved[k] is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = saved[k]  # type: ignore[assignment]
    return rc, (out.getvalue() + err.getvalue()).rstrip("\n")


def submit(state: State, store: Path, *, cwd: Path,
           sandbox: Path | None = None, home: Path | None = None) -> bool:
    """Enter on the field: run the command, append the turn, reset the field.

    A plain `search` (query, no flags) also remembers its ranked hits, so the
    transcript can draw them as cards and `o` can open the top one without the
    slug ever being retyped. A *bare* `search` (no query, no flags) runs
    nothing: the field is left as `search ` with the cursor after the space —
    the user's own text stays on the main screen and the query is all they
    have to add. No second screen, no usage dump.
    """
    cmd = state.field.strip()
    if not cmd:
        return False
    name, _, rest = cmd.partition(" ")
    if name == "search" and not rest.strip():
        state.field, state.cursor = "search ", len("search ")
        state.picker = False
        return False
    rc, text = run_command(state, store, cwd=cwd, sandbox=sandbox, home=home)
    ranked: list[tuple[float, Page]] = []
    if name == "search" and rest.strip() and not rest.strip().startswith("-"):
        ranked = search(rest.strip(), store, k=SEARCH_K)
        state.hits = [page for _, page in ranked]
    else:
        state.hits = []
    state.turns.append(Turn(cmd=cmd, rc=rc, output=text, hits=ranked or None))
    state.field, state.cursor = "", 0
    state.picker = False
    state.follow = True
    if not state.history or state.history[-1] != cmd:
        state.history.append(cmd)
    state.hist_idx = None
    return True


def open_top_hit(state: State, store: Path, *, cwd: Path,
                 sandbox: Path | None = None, home: Path | None = None) -> None:
    """`o`: open the top hit of the last search as a `show` turn. No slug typed."""
    if not state.hits:
        return
    state.field = f"show {state.hits[0].slug}"
    state.cursor = len(state.field)
    submit(state, store, cwd=cwd, sandbox=sandbox, home=home)
    state.hits = []


def wrap(text: str, width: int) -> list[str]:
    """Word-wrap captured output to the transcript width. Pure."""
    if width <= 1:
        return [text]
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        current = ""
        for word in paragraph.split():
            if current and len(current) + 1 + len(word) > width:
                lines.append(current)
                current = word
            else:
                current = f"{current} {word}".strip()
        lines.append(current)
    return lines


def _search_cards(turn: Turn, width: int) -> list[tuple[int, str]] | None:
    """A plain `search` turn as cards: one line per hit with its matched window
    dim underneath, instead of the CLI's wrapped prose.

    The raw output's first line (the count) and its trailing `skipped`
    warnings are kept; the per-hit lines themselves are replaced by the cards.
    """
    if not turn.hits:
        return None
    raw = turn.output.splitlines()
    header = raw[0] if raw else f"{len(turn.hits)} hit(s)"
    lines: list[tuple[int, str]] = [(NORMAL, ln) for ln in wrap(header, width)]
    query = turn.cmd.partition(" ")[2].strip()
    n = len(turn.hits)
    num_w = len(str(n))
    slug_w = min(22, max(10, max((len(p.slug) for _, p in turn.hits), default=10) + 2))
    tail_w = max((len(f"[{s:.1f}] {p.updated}") for s, p in turn.hits), default=0)
    for i, (score, page) in enumerate(turn.hits):
        title_w = max(8, width - 6 - num_w - 2 - slug_w - 2 - tail_w)
        head = (f"  {i + 1:>{num_w}}.  {_truncate(page.slug, slug_w):<{slug_w}}"
                f"  {_truncate(page.title, title_w)}")
        tail = f"[{score:.1f}] {page.updated}"
        need = len(head) + 1 + len(tail)
        card = head + " " * max(1, width - need) + tail if need <= width else _truncate(head, width)
        lines.append((NORMAL, card))
        for wl in wrap(snippet(page, width=max(8, width - 6), query=query), width - 5):
            lines.append((DIM, "    " + wl))
    for ln in raw[1:]:
        if ln.strip().startswith("skipped "):
            lines += [(NORMAL, wl) for wl in wrap(ln, width)]
    return lines


def render_turn(turn: Turn, width: int) -> list[tuple[int, str]]:
    """A turn as transcript lines with attribute tokens: echo, output, exit."""
    lines: list[tuple[int, str]] = [(BOLD, f"lore > {turn.cmd}")]
    cards = _search_cards(turn, width)
    if cards is not None:
        lines += cards
    elif turn.output.rstrip("\n"):
        lines += [(NORMAL, ln) for ln in wrap(turn.output.rstrip("\n"), width)]
    if turn.rc:
        lines.append((ERROR, f"exit {turn.rc}"))
    lines.append((NORMAL, ""))
    return lines


def clamp_view(state: State, total: int, height: int) -> None:
    """Re-follow the transcript bottom unless the user scrolled up with PgUp."""
    if height <= 0:
        return
    bottom = max(0, total - height)
    if state.follow:
        state.view_top = bottom
    else:
        state.view_top = max(0, min(bottom, state.view_top))


def scroll_transcript(state: State, pages: int, height: int, total: int) -> None:
    """PgUp/PgDn: leave the follow, scroll, and follow again at the bottom."""
    bottom = max(0, total - height)
    if pages < 0:
        state.follow = False
        state.view_top = max(0, state.view_top - height)
    else:
        candidate = min(bottom, state.view_top + height)
        state.view_top = candidate
        state.follow = candidate >= bottom


def run_guarded(store: Path, *, prog: str = "lore dev --panes",
                cwd: Path, sandbox: Path | None = None,
                home: Path | None = None) -> bool:
    """Try the screen; report and return False where the terminal cannot host it.

    The gate is the same one the console uses: both ends a real terminal. A pipe
    keeps the line editor — an agent that drives `lore dev` must not lose it.
    """
    try:
        real = sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError, OSError):
        real = False
    if not real:
        print("the panes screen needs a real terminal; back to the line editor")
        return False
    if curses is None:
        print("the panes screen needs curses (POSIX); back to the line editor")
        return False
    try:
        curses.wrapper(_main, store, prog=prog, cwd=cwd, sandbox=sandbox, home=home)
    except curses.error as exc:
        print(f"the panes screen could not start ({exc}); back to the line editor")
        return False
    return True


def _truncate(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:1]
    return text[: (width - 1)] + "…"


def _logo_origin(rows: int, cols: int) -> int:
    """Top row for the logo: pushed down when the terminal is tall."""
    return 1 if rows < 24 else (rows - 14) // 2


def _attr(token: int) -> int:
    """The curses attribute for a transcript token."""
    if token == BOLD:
        return curses.A_BOLD
    if token == DIM:
        return curses.A_DIM
    if token == ERROR:
        if curses.has_colors():
            return curses.color_pair(1) | curses.A_BOLD
        return curses.A_BOLD
    return curses.A_NORMAL


def _draw_picker(stdscr, state: State, rows: int, cols: int, *,
                 top: int | None = None, bottom: bool = False) -> None:
    """The `/` picker: a bordered, centred panel of commands with hints.

    `bottom` pins it above the bottom input line (chat state); `top` anchors it
    below the ask box (empty state). A panel that would not fit its anchor falls
    back to true centring. The window slides so the highlighted row is always
    visible.
    """
    shown, cur, _total, above, below = picker_window(state, 8)
    panel_w = min(60, cols - 6)
    empty = not shown
    if not empty:
        bodys = len(shown)
        footer = 1 if (above or below) else 0
        panel_h = 3 + bodys + footer
    else:
        panel_h = 4
    if panel_h > rows - 2:
        return  # no room even centred: skip rather than draw off-screen
    if bottom:
        top = rows - 1 - panel_h
    elif top is not None and top + panel_h > rows - 1:
        top = (rows - panel_h) // 2
    elif top is None:
        top = (rows - panel_h) // 2
    x = (cols - panel_w) // 2
    edge = "─" * (panel_w - 2)
    # Blank the panel's rectangle first: a modal menu must hide what sits behind
    # it, or the logo and transcript leak around the borders. The next full
    # redraw repaints the covered content when the picker closes.
    for blank_y in range(top, top + panel_h):
        stdscr.addstr(blank_y, x, " " * panel_w)
    stdscr.addstr(top, x, "╭" + edge + "╮")
    if empty:
        stdscr.addstr(top + 1, x, "│" + " " * (panel_w - 2) + "│")
        caption = f"commands — nothing matches {state.field!r}"
        stdscr.addstr(top + 1, x + 2, _truncate(caption, panel_w - 4), curses.A_DIM)
        stdscr.addstr(top + 2, x, "│" + " " * (panel_w - 2) + "│")
        stdscr.addstr(top + 2, x + 2, "Esc clears the filter", curses.A_DIM)
        stdscr.addstr(top + 3, x, "╰" + edge + "╯")
        return
    stdscr.addstr(top + 1, x, "│" + " " * (panel_w - 2) + "│")
    stdscr.addstr(top + 1, x + 2, "commands — type to filter:",
                  curses.A_DIM)
    name_w = max((len(name) for name in shown), default=1)
    for row, name in enumerate(shown):
        label = f"  {name:<{name_w}}   {PICKER_HINTS.get(name, '')}"
        attr = curses.A_REVERSE if row == cur else curses.A_NORMAL
        stdscr.addstr(top + 2 + row, x, "│")
        stdscr.addstr(top + 2 + row, x + 1, _truncate(label, panel_w - 2), attr)
        stdscr.addstr(top + 2 + row, x + panel_w - 1, "│")
    if footer:
        foot_row = top + 2 + bodys
        side = ("above and below" if above and below
                else "below" if below else "above")
        foot = f"j/k move the cursor — more commands {side}"
        stdscr.addstr(foot_row, x, "│")
        stdscr.addstr(foot_row, x + 1, _truncate(foot, panel_w - 2), curses.A_DIM)
        stdscr.addstr(foot_row, x + panel_w - 1, "│")
    stdscr.addstr(top + 2 + bodys + footer, x, "╰" + edge + "╯")


def _wide_char(stdscr, first: int) -> str:
    """Assemble one multibyte UTF-8 character from raw terminal bytes.

    curses hands each byte of a multibyte character to `getch` as a separate
    int ≥ 128, so a Cyrillic letter arrives as two or three raw bytes. The
    continuation bytes (0x80–0xBF) are drained with a short timeout: the last
    character of a burst must decode as soon as the terminal's burst ends, not
    one keystroke later (a blocked read would hold the final letter back until
    the next key). A byte that is not a continuation is pushed back for the
    next loop pass — a fast ASCII key can arrive mid-burst.
    """
    raw = bytearray([first])
    stdscr.timeout(30)
    try:
        while len(raw) < 4:
            nxt = stdscr.getch()
            if nxt == -1:
                break  # burst over: the character is complete
            if 128 <= nxt <= 191:
                raw.append(nxt)
            else:
                curses.ungetch(nxt)
                break
    finally:
        stdscr.timeout(-1)  # back to blocking for the next key
    return bytes(raw).decode("utf-8", "replace")


def _draw_ask(stdscr, store: Path, state: State, rows: int, cols: int) -> None:
    """The empty state, one to one with opencode: logo, ask box, hint bar."""
    if cols >= 46:
        y = _logo_origin(rows, cols)
        for i, row in enumerate(LOGO):
            stdscr.addstr(y + i, (cols - len(row)) // 2, row, curses.A_BOLD)
        if cols >= 60:
            tagline = f"pagelore {__version__} — durable project memory"
            stdscr.addstr(y + len(LOGO) + 1, (cols - len(tagline)) // 2,
                          tagline, curses.A_DIM)

    box_w = min(64, cols - 8)
    box_h = 5
    box_x = (cols - box_w) // 2
    box_y = min(_logo_origin(rows, cols) + 9 if cols >= 46 else 2,
                max(2, rows - 6))
    stdscr.addstr(box_y, box_x, "╭" + "─" * (box_w - 2) + "╮")
    for i in range(1, box_h - 1):
        stdscr.addstr(box_y + i, box_x, "│" + " " * (box_w - 2) + "│")
    stdscr.addstr(box_y + box_h - 1, box_x, "╰" + "─" * (box_w - 2) + "╯")

    ask = "Ask anything…   ·   search \"webgl context lost\" · list · write"
    stdscr.addstr(box_y + 1, box_x + 2, _truncate(ask, box_w - 4), curses.A_DIM)
    prompt = f"lore > {state.field}"
    stdscr.addstr(box_y + 2, box_x + 2, _truncate(prompt, box_w - 4))
    stdscr.move(box_y + 2, min(box_x + box_w - 3, box_x + 2 + len("lore > ") + state.cursor))
    keys = "/ commands · o opens the top hit · ↑ history · q quit"
    stdscr.addstr(box_y + 3, box_x + 2, _truncate(keys, box_w - 4), curses.A_DIM)

    hint = (f"{_truncate(str(store), 30)}   ·   ↑ history · / commands · o top hit · q quit"
            f"   lore · pagelore {__version__}")
    stdscr.addstr(rows - 1, 0, _truncate(hint, cols - 1), curses.A_DIM)

    if state.picker:
        _draw_picker(stdscr, state, rows, cols, top=box_y + box_h + 2)


def _draw_chat(stdscr, state: State, rows: int, cols: int) -> None:
    """The working state: transcript above, the field as the bottom line."""
    height = rows - 1
    width = max(10, cols - 2)
    lines: list[tuple[int, str]] = []
    for turn in state.turns:
        lines += render_turn(turn, width)
    total = len(lines)
    clamp_view(state, total, height)
    for i, (token, line) in enumerate(lines[state.view_top:state.view_top + height]):
        stdscr.addstr(i, 1, _truncate(line, width), _attr(token))

    if state.picker:
        _draw_picker(stdscr, state, rows, cols, bottom=True)

    prompt = f"lore > {state.field}"
    stdscr.addstr(rows - 1, 0, _truncate(prompt, cols - 1))
    stdscr.move(rows - 1, min(cols - 2, len("lore > ") + state.cursor))


def _draw(stdscr, store: Path, state: State) -> None:
    """Redraw the whole screen from the state. One source of truth, no diffing."""
    stdscr.erase()
    rows, cols = stdscr.getmaxyx()
    if rows < 10 or cols < 40:
        return
    try:
        curses.curs_set(1)
    except curses.error:
        pass
    if not state.turns:
        _draw_ask(stdscr, store, state, rows, cols)
    else:
        _draw_chat(stdscr, state, rows, cols)
    stdscr.refresh()


def _main(stdscr, store: Path, *, prog: str, cwd: Path,
          sandbox: Path | None, home: Path | None) -> None:  # pragma: no cover
    """The screen itself: read a key, decide, redraw. `q` is back to the editor."""
    try:
        if curses.has_colors():
            curses.start_color()
            curses.init_pair(1, curses.COLOR_RED, -1)
    except curses.error:
        pass
    # Esc as a bare key must land fast, or curses waits ~1s for a possible
    # escape sequence after it and swallows the first key typed next.
    try:
        curses.set_escdelay(50)
    except (AttributeError, curses.error):
        pass
    state = State()
    while True:
        _draw(stdscr, store, state)
        key = stdscr.getch()
        if key == curses.KEY_RESIZE:
            continue
        if 128 <= key < 256:
            # A multibyte character (the store's corpus is bilingual, and the
            # query step must take Cyrillic): curses sent one raw byte per
            # `getch`, so read the sequence and insert the decoded letter. It
            # lands in the field whether the picker is open (its filter reads
            # the field) or not — ASCII keys keep their two home-grown paths.
            field_insert(state, _wide_char(stdscr, key))
            continue
        if state.picker:
            if key in (ord("\n"), 10, 13):
                picker_fill(state)
            elif key == 27:
                state.picker = False
                state.field, state.cursor = "", 0
            elif key in (curses.KEY_UP, ord("k")):
                state.picker_idx = (state.picker_idx - 1) % max(1, len(picker_items(state)))
            elif key in (curses.KEY_DOWN, ord("j")):
                state.picker_idx = (state.picker_idx + 1) % max(1, len(picker_items(state)))
            elif key in (8, 127, curses.KEY_BACKSPACE):
                field_backspace(state)
            elif key == 21:  # Ctrl-U clears the filter
                state.field, state.cursor = "", 0
            elif 32 <= key <= 126:
                field_insert(state, chr(key))
            continue
        if key in (8, 127, curses.KEY_BACKSPACE):
            field_backspace(state)
        elif key == curses.KEY_DC:
            if state.cursor < len(state.field):
                state.field = (state.field[:state.cursor]
                               + state.field[state.cursor + 1:])
        elif key == 27:  # Esc clears the field, not the session
            state.field, state.cursor = "", 0
        elif key in (1, 5):  # Ctrl-A / Ctrl-E
            state.cursor = 0 if key == 1 else len(state.field)
        elif key == 21:  # Ctrl-U clears the line
            state.field, state.cursor = "", 0
        elif key == curses.KEY_LEFT:
            field_cursor(state, -1)
        elif key == curses.KEY_RIGHT:
            field_cursor(state, 1)
        elif key in (16, ord("/")):  # ctrl+p or `/`: the command picker, always
            open_picker(state)
        elif key in (ord("\n"), 10, 13):
            submit(state, store, cwd=cwd, sandbox=sandbox, home=home)
        elif key == ord("o"):
            if state.field:
                field_insert(state, "o")
            else:
                open_top_hit(state, store, cwd=cwd, sandbox=sandbox, home=home)
        elif key in (curses.KEY_UP, curses.KEY_DOWN):
            history_back(state, -1 if key == curses.KEY_UP else 1)
        elif key in (curses.KEY_PPAGE, curses.KEY_NPAGE):
            height = max(1, stdscr.getmaxyx()[0] - 1)
            total = sum(len(render_turn(t, max(10, stdscr.getmaxyx()[1] - 2)))
                        for t in state.turns)
            scroll_transcript(state, -1 if key == curses.KEY_PPAGE else 1, height, total)
        elif key in (ord("q"), ord("Q")):
            if not state.field:
                return
        elif 32 <= key <= 126:
            field_insert(state, chr(key))