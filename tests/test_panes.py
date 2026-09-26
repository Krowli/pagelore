"""The opencode-shaped screen: a pure model, with one pty test for the raw terminal.

The screen behind `lore dev --panes` borrows the opencode screen's shape one to
one: fresh, a logo and a big "Ask anything…" box; once commands have run, a
transcript of them with the field at the bottom. The line-editor discipline
carries over unchanged — what a keypress decides is plain functions on `State`,
and those are called here with no terminal. Only the draw loop touches curses,
so one pty test proves the raw screen draws the ask box, runs commands typed
into it, answers `/` and `o`, and quits back to the line editor.

Commands run from the field go through the same `cli.main` the CLI runs, so the
in-process output is compared here with a real child's, byte for byte: the field
is fidelity, not a shortcut. What must own the terminal (the MCP server, the
wizard, `edit`) is refused from the field, never half-run.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import conftest
import pytest

from pagelore import panes
from pagelore import write as memory_write


def _page(store: Path, slug: str, title: str) -> None:
    memory_write.write_page(
        store, slug, title, "decision", ["src/a.py"],
        "## Decision\n\nSomething was decided once, at length enough to be a real"
        " page and not a stub." + conftest.FILLER)


@pytest.fixture()
def store(tmp_path):
    d = tmp_path / ".memory"
    d.mkdir()
    for slug in ["zeta-page", "alpha-page", "middle-page"]:
        _page(d, slug, f"{slug} title")
    return d


def _session(command: str = "", history: list[str] | None = None) -> panes.State:
    """A fresh screen state with the field (and optionally history) prefilled."""
    st = panes.State(history=history or [])
    st.field = command
    st.cursor = len(command)
    return st


def _in_project(monkeypatch, tmp_path, store: Path) -> None:
    """The same surroundings a real run needs: cwd at the store's project, and a
    HOME that cannot absorb the post-command housekeeping."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(store.parent)


def _run_field(command: str, store: Path, monkeypatch, tmp_path) -> tuple[panes.State, int, str]:
    """Run a command in-process, as the screen would on Enter, and return the run."""
    _in_project(monkeypatch, tmp_path, store)
    st = _session(command)
    rc, text = panes.run_command(st, store, cwd=store.parent)
    return st, rc, text


def _run_turn(command: str, store: Path, monkeypatch, tmp_path) -> panes.Turn:
    """Enter a command the way the screen would and return the appended turn."""
    _in_project(monkeypatch, tmp_path, store)
    st = _session(command)
    panes.submit(st, store, cwd=store.parent)
    return st.turns[-1]


def test_query_rows_are_the_cli_ranking(store):
    hits = [p.slug for p in panes.query_rows(store, "zeta")]
    assert hits == ["zeta-page"]
    assert panes.query_rows(store, "") == [], "nothing matches an empty search"


def test_the_field_edits_like_a_line():
    st = panes.State()
    panes.field_insert(st, "l")
    panes.field_insert(st, "i")
    assert st.field == "li" and st.cursor == 2
    panes.field_cursor(st, -1)
    panes.field_insert(st, "s")
    assert st.field == "lsi", "an insert lands at the cursor, not the end"
    panes.field_backspace(st)
    assert st.field == "li" and st.cursor == 1
    panes.field_backspace(st)
    panes.field_backspace(st)
    assert st.field == "i" and st.cursor == 0, "backspace never empties past the start"


def test_picker_filters_and_fills_the_field():
    """`/` opens the picker, typing narrows it, Enter fills `name ` and lets the
    rest of the command continue in the same field."""
    st = panes.State()
    panes.open_picker(st)
    assert st.picker
    items = panes.picker_items(st)
    assert "search" in items and "list" in items and "exit" in items
    panes.field_insert(st, "se")
    assert panes.picker_items(st) == ["search"]
    panes.picker_fill(st)
    assert not st.picker
    assert st.field == "search " and st.cursor == len("search ")
    for ch in "zeta":
        panes.field_insert(st, ch)
    assert st.field == "search zeta"


def test_picker_fill_with_no_match_just_closes():
    st = panes.State()
    panes.open_picker(st)
    panes.field_insert(st, "zzz")
    assert panes.picker_items(st) == []
    panes.picker_fill(st)  # must not crash or mangle the field
    assert st.field == "zzz" and not st.picker


def test_history_walks_only_on_an_empty_field():
    st = panes.State(history=["list", "search zeta"])
    panes.history_back(st, -1)
    assert st.field == "search zeta"
    panes.history_back(st, -1)
    assert st.field == "list"
    panes.history_back(st, 1)
    assert st.field == "search zeta"
    panes.history_back(st, 1)  # newer than the newest: the field empties
    assert st.field == ""
    panes.field_insert(st, "x")
    panes.history_back(st, -1)  # text in the field, ↑ does nothing
    assert st.field == "x"
    panes.history_back(st, -1)  # and history does not empty a non-empty field
    assert st.field == "x"


def test_terminal_owning_commands_are_refused_from_the_field():
    """A stdio server, an editor and a wizard that reads stdin must not run half
    through the middle of a curses screen."""
    for argv in (["mcp"], ["dev"], ["edit"], ["panes"]):
        assert panes._needs_real_terminal(argv), argv
    assert panes._needs_real_terminal(["init"]), "the wizard without --yes"
    assert panes._needs_real_terminal(["init", "--store", "home"])
    assert panes._needs_real_terminal(["init", "--yes"]) is None
    assert panes._needs_real_terminal(["search", "zeta"]) is None


def test_run_command_list_prints_the_agent_surface(store, monkeypatch, tmp_path):
    _st, rc, text = _run_field("list", store, monkeypatch, tmp_path)
    assert rc == 0
    assert "3 page(s) in" in text
    for slug in ("zeta-page", "middle-page", "alpha-page"):
        assert slug in text


def test_run_command_search_ranks_the_cli_way(store, monkeypatch, tmp_path):
    _st, rc, text = _run_field("search zeta", store, monkeypatch, tmp_path)
    assert rc == 0
    assert "1 hit(s) in" in text
    assert "zeta-page" in text


def test_run_command_an_unknown_command_preserves_usage_and_exit_2(store, monkeypatch, tmp_path):
    _st, rc, text = _run_field("nonsense", store, monkeypatch, tmp_path)
    assert rc == 2
    assert "unknown command" in text
    assert "FIX:" in text, "the one correction mechanism the agent loop follows"


def test_run_command_matches_a_real_child(store, monkeypatch, tmp_path):
    """In-process execution is fidelity, not a shortcut: the same rc and the same
    listing, byte for byte, as a real `lore list` child in the same position."""
    _st, rc, text = _run_field("list", store, monkeypatch, tmp_path)
    child = subprocess.run([*conftest.LORE, "list"], cwd=store.parent,
                           capture_output=True, env=conftest.lore_env())
    assert rc == child.returncode == 0
    # A Windows child's text-mode stdout writes \r\n; the bytes it means are the same.
    child_text = (child.stdout + child.stderr).decode("utf-8", "replace")
    child_text = child_text.replace("\r\n", "\n").rstrip("\n")
    assert text == child_text, "the field must show exactly what an agent would see"


def test_run_command_turns_argparse_exits_into_rcs(store, monkeypatch, tmp_path):
    """argparse validation (a query-less `search`) raises SystemExit instead of
    returning; in-process that would kill the whole screen, so it must land as
    the turn's rc — exactly the code a child process would exit with."""
    _st, rc, text = _run_field("search", store, monkeypatch, tmp_path)
    assert rc == 2
    assert "give query words" in text
    _st, rc, text = _run_field("search --version", store, monkeypatch, tmp_path)
    assert rc == 0, "--version exits 0 through the same SystemExit, not as a crash"
    assert "pagelore" in text


def test_submit_of_a_bare_search_waits_for_the_query(store, monkeypatch, tmp_path):
    """Enter on a bare `search` used to paint argparse's usage — and then, in
    an over-clever fix, a second screen asking for the query again. Now it runs
    nothing and leaves the user's own text on the main screen: `lore > search `
    with the cursor after the space, so only the query is missing."""
    _in_project(monkeypatch, tmp_path, store)
    st = _session("search")
    assert not panes.submit(st, store, cwd=store.parent)  # no turn yet
    assert st.field == "search " and st.cursor == len("search ")
    assert not st.turns, "a bare search is a dead end no more, but also no turn yet"
    # Enter again with still no query is a harmless no-op, never argparse's usage
    assert not panes.submit(st, store, cwd=store.parent)
    assert st.field == "search " and not st.turns
    # the user only adds the query — Cyrillic included — and then Enter runs it
    panes.field_insert(st, "поиск")
    assert st.field == "search поиск"
    assert panes.submit(st, store, cwd=store.parent)
    turn = st.turns[0]
    assert turn.cmd == "search поиск"
    assert "no matches" in turn.output
    assert st.field == ""
    assert st.history[-1] == "search поиск", "the composed run joins history"
    # flagged or query-ful searches still run straight through, no waiting
    st2 = _session("search zeta")
    assert panes.submit(st2, store, cwd=store.parent)
    assert st2.turns[0].rc == 0 and st2.field == ""


def test_submit_appends_a_turn_and_resets_the_field(store, monkeypatch, tmp_path):
    """Enter: the command becomes a transcript turn, the field empties, and the
    command joins the history; an empty field submits nothing."""
    _in_project(monkeypatch, tmp_path, store)
    st = _session("list")
    assert panes.submit(st, store, cwd=store.parent)
    assert len(st.turns) == 1
    turn = st.turns[0]
    assert turn.cmd == "list" and turn.rc == 0
    assert "3 page(s) in" in turn.output
    assert st.field == "" and st.cursor == 0
    assert st.history == ["list"]
    assert not panes.submit(st, store, cwd=store.parent)
    assert len(st.turns) == 1, "nothing submitted on an empty field"


def test_submit_remembers_search_hits_for_o(store, monkeypatch, tmp_path):
    """`o` opens the top hit of the last search as a `show` turn — the slug is
    never retyped — and only once; with no hits `o` is a no-op."""
    _in_project(monkeypatch, tmp_path, store)
    st = _session("search zeta")
    panes.submit(st, store, cwd=store.parent)
    assert [p.slug for p in st.hits] == ["zeta-page"]
    panes.open_top_hit(st, store, cwd=store.parent)
    assert len(st.turns) == 2
    shown = st.turns[-1]
    assert shown.cmd == "show zeta-page" and shown.rc == 0
    assert "slug: zeta-page" in shown.output
    assert st.hits == [], "o opens once"
    panes.open_top_hit(st, store, cwd=store.parent)
    assert len(st.turns) == 2, "o with no hits changes nothing"


def test_render_turn_echoes_the_command_then_output_then_exit():
    turn = panes.Turn(
        cmd="nonsense", rc=2,
        output="lore: unknown command 'nonsense'\nFIX: lore search 'nonsense'")
    lines = panes.render_turn(turn, 50)
    assert lines[0] == (panes.BOLD, "lore > nonsense"), "the echo reads like the prompt"
    assert lines[-2] == (panes.ERROR, "exit 2"), "a failed run's exit stands out"
    assert lines[-1] == (panes.NORMAL, "")
    non_blank = [ln for tok, ln in lines if ln]
    assert non_blank[1].startswith("lore: unknown"), "the output follows the echo"


def test_render_turn_search_renders_hits_as_cards(store, monkeypatch, tmp_path):
    """A plain `search` turn draws one card per hit — slug and title on the
    line, the matched window dim underneath, score and date on the right —
    instead of the CLI's wrapped prose, and nothing exceeds the width."""
    turn = _run_turn("search zeta", store, monkeypatch, tmp_path)
    assert turn.hits, "the turn carries the ranked hits for the cards"
    lines = panes.render_turn(turn, 60)
    assert lines[0] == (panes.BOLD, "lore > search zeta")
    assert lines[1][0] == panes.NORMAL and "hit(s) in" in lines[1][1]
    assert "zeta-page" in lines[1][1] + "".join(ln for tok, ln in lines), \
        "the count header names the store, so the pty token survives"
    cards = [(tok, ln) for tok, ln in lines if "zeta-page" in ln]
    assert cards and cards[0][0] == panes.NORMAL
    assert any(tok == panes.DIM and ln.strip() for tok, ln in lines), \
        "the matched window is dim underneath the card"
    assert any(re.search(r"\[\d+\.\d+\] \d{4}-\d{2}-\d{2}", ln)
               for tok, ln in lines), \
        "score and date ride on the right of a card"
    for tok, ln in lines:
        assert len(ln) <= 60 or " " not in ln.strip(), \
            (tok, ln, "only an unbreakable token (a store path) may exceed the width")
    assert lines[-1] == (panes.NORMAL, "")


def test_render_turn_search_with_flags_stays_raw(store, monkeypatch, tmp_path):
    """Flagged searches keep the byte-for-byte CLI text: the pretty cards only
    replace plain-query searches, so the readback is never silently re-ranked."""
    turn = _run_turn("search --touching src/a.py zeta", store, monkeypatch, tmp_path)
    assert turn.hits is None
    lines = panes.render_turn(turn, 60)
    assert lines[1][0] == panes.NORMAL and "hit(s) in" in lines[1][1]
    assert not any(tok == panes.DIM for tok, ln in lines[2:]), \
        "no card rendering for a flagged search"


def test_search_cards_keep_the_skipped_warning(store):
    """The stderr warning about short unsearchable pages is not swallowed by
    the card rendering."""
    page = panes.query_rows(store, "zeta")[0]
    turn = panes.Turn(cmd="search zeta", rc=0,
                      output="1 hit(s) in /tmp/.memory\nzeta-page  —  zeta page title  —  x\n"
                             "skipped 2 page(s) under 200 chars, which `lore write` "
                             "would refuse: short-one — rewrite them",
                      hits=[(0.4, page)])
    lines = panes.render_turn(turn, 60)
    assert any("skipped 2 page(s)" in ln for tok, ln in lines), \
        "the warning survives the pretty rendering"


def test_picker_hints_cover_every_command():
    assert set(panes.PICKER_HINTS) == set(panes.PICKER_COMMANDS), \
        "no command in the menu is left without a hint"
    assert panes.PICKER_COMMANDS.count("search") == 1


def test_picker_window_scrolls_the_cursor_into_view():
    """The picker is taller than the panel: the window slides so the cursor is
    always on screen, and the panel says when more commands exist above/below."""
    st = panes.State()
    panes.open_picker(st)
    assert len(panes.picker_items(st)) > 8, "the full menu should overflow a window of 8"
    shown, cur, total, above, below = panes.picker_window(st, 8)
    assert shown == list(panes.PICKER_COMMANDS[:8]) and cur == 0
    assert total == len(panes.PICKER_COMMANDS) and below and not above
    st.picker_idx = 12
    shown, cur, total, above, below = panes.picker_window(st, 8)
    assert shown[0] == panes.PICKER_COMMANDS[5], "the window slides to keep the cursor visible"
    assert cur == 7 and above and below
    st.picker_idx = 16
    shown, cur, total, above, below = panes.picker_window(st, 8)
    assert shown[-1] == panes.PICKER_COMMANDS[-1] and cur == 7 and above and not below


def test_wrap_never_exceeds_the_width(store):
    body = " ".join("wobble" for _ in range(200))
    for width in (10, 27, 61):
        for line in panes.wrap(body, width):
            assert len(line) <= width, (width, line)
    assert all(panes.wrap(body, 10)), "no empty line from a run of words"


def test_wrap_keeps_blank_paragraphs_blank(store):
    lines = panes.wrap("one\n\ntwo", 20)
    assert lines == ["one", "", "two"]


def test_transcript_follows_the_bottom_and_scrolls_back():
    """The transcript stays glued to the newest line, PgUp lets you leave it,
    and PgDn at the bottom puts it back."""
    st = panes.State()
    panes.clamp_view(st, 0, 10)
    assert st.view_top == 0
    panes.clamp_view(st, 40, 10)
    assert st.view_top == 30
    panes.scroll_transcript(st, -1, 10, 40)
    assert not st.follow and st.view_top == 20
    panes.scroll_transcript(st, 1, 10, 40)
    assert st.follow and st.view_top == 30


@conftest.needs_posix
def test_the_screen_draws_like_opencode_and_runs_commands(store, tmp_path):
    """Raw-screen proof: the ask box draws, a command typed into it runs
    in-process and paints its turn, `/` opens the picker even with text in the
    field, `o` opens the top hit of the last search, `q` is back to the line
    editor, and the whole thing exits 0."""
    import fcntl
    import pty
    import select
    import struct
    import termios
    import time

    home = tmp_path / "home"
    home.mkdir()

    pid, fd = pty.fork()
    if pid == 0:
        # Let the parent size the terminal before curses reads its size.
        time.sleep(0.3)
        os.chdir(store.parent)
        os.environ.update({"HOME": str(home), "USERPROFILE": str(home),
                           "PYTHONPATH": str(conftest.REPO / "src"),
                           "PAGELORE_NO_REFRESH": "1",
                           "TERM": "xterm-256color",
                           "PYTHONUTF8": "1"})
        os.execv(sys.executable, [sys.executable, "-m", "pagelore", "dev", "--panes"])

    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))

    seen = b""

    def wait_for(token: bytes, deadline: float = 30) -> bool:
        nonlocal seen
        end = time.time() + deadline
        while True:
            # curses redraws incrementally: it can emit CSI sequences (erase to
            # end of line, cursor moves) right between the bytes of one printed
            # word. Strip them so text tokens match across redraws.
            clean = re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]", b"", seen)
            if token in clean:
                return True
            if time.time() > end:
                return False
            if not select.select([fd], [], [], 0.2)[0]:
                continue
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                return False
            if not chunk:
                return False
            seen += chunk

    try:
        assert wait_for(b"Ask anything"), f"no ask box\n{seen[-400:]!r}"
        # a command typed into the box runs in-process, and the transcript
        # paints the listing an agent would see
        os.write(fd, b"list\r")
        assert wait_for(b"page(s) in"), f"the box did not run `list`\n{seen[-400:]!r}"
        assert wait_for(b"lore > list"), f"the command is not echoed\n{seen[-400:]!r}"
        # a search run makes `o` able to open the top hit without the slug
        os.write(fd, b"search zeta\r")
        assert wait_for(b"hit(s) in"), f"search did not run\n{seen[-400:]!r}"
        # `/` with text already in the field must still open the picker — it
        # once no-op'd into a literal slash; Esc closes the menu and clears
        os.write(fd, b"x/")
        assert wait_for(b"nothing matches"), \
            f"`/` with text showed no picker\n{seen[-400:]!r}"
        os.write(fd, b"\x1b")
        os.write(fd, b"o")
        assert wait_for(b"slug: zeta-page"), f"`o` did not open the top hit\n{seen[-400:]!r}"
        # a command that owns the terminal is refused from the field, not half-run
        os.write(fd, b"edit\r")
        assert wait_for(b"owns the terminal"), f"the guard did not answer\n{seen[-400:]!r}"
        # a bare `search` + Enter runs nothing and leaves the field as the query's
        # waiting room — no usage dump, no second screen: only the query is
        # missing, and it accepts Cyrillic, which curses delivers byte by byte
        os.write(fd, b"search\r")
        os.write(fd, "поиск".encode())
        assert wait_for("поиск".encode()), \
            f"cyrillic input was dropped\n{seen[-400:]!r}"
        os.write(fd, b"\r")
        assert wait_for(b"no matches"), \
            f"the cyrillic search did not run\n{seen[-400:]!r}"
        # Esc still clears the pending field, then q quits
        os.write(fd, b"search\x1b")
        # quit the screen: back to the line editor, then exit cleanly
        os.write(fd, b"q")
        assert wait_for(b"> "), f"no line-editor prompt after quit\n{seen[-400:]!r}"
        os.write(fd, b"exit\r")
        deadline = time.time() + 30
        while time.time() < deadline:
            if select.select([fd], [], [], 0.2)[0]:
                try:
                    if not os.read(fd, 4096):
                        break
                except OSError:
                    break
    finally:
        os.close(fd)
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass

    text = seen.decode("utf-8", "replace")
    assert "lore dev" in text, text[:300]
    assert "panes" in text, text[:300]