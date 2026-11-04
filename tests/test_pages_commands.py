"""`lore list`, `lore rm <slug>`, `lore edit <slug>` — the store as a thing a person
can look over and tidy, not only a thing an agent searches.

Until these existed, listing meant `ls .memory`, which shows filenames and not what
is superseded; deleting meant `rm`, which the store's log never saw; editing meant
opening the file and hoping the frontmatter survived.
"""
import stat
import sys

import pytest

from pagelore import edit, listing, remove, write
from pagelore.lib import LOG_NAME

# --- list ----------------------------------------------------------------------

def test_list_names_every_page_with_its_kind_and_date(populated, capsys):
    assert listing.main(["--store", str(populated)]) == 0
    out = capsys.readouterr().out
    for slug, kind in (("webgl-context-loss", "bug"), ("command-palette-highlight", "concept"),
                       ("sqlite-writer-ownership", "decision")):
        row = next(line for line in out.splitlines() if slug in line)
        assert kind in row, row
        assert "2" in row and "-" in row, "no date on the row"
    assert "3 page(s)" in out


def test_list_marks_a_superseded_page_on_its_row(populated, capsys):
    write.stamp_superseded(populated, "webgl-context-loss", "webgl-context-loss-v2")
    listing.main(["--store", str(populated)])
    # The marker, not the word: pytest puts this test's name, "superseded" included,
    # into the store path the header line prints.
    row = next(line for line in capsys.readouterr().out.splitlines()
               if "\u26a0 superseded by" in line)
    assert "webgl-context-loss" in row and "superseded by webgl-context-loss-v2" in row


def test_an_empty_store_says_so_and_is_not_an_error(store, capsys):
    assert listing.main(["--store", str(store)]) == 0
    assert "no pages" in capsys.readouterr().err


# --- rm ------------------------------------------------------------------------

def test_rm_deletes_the_page_and_logs_it(populated, capsys):
    assert remove.main(["webgl-context-loss", "--store", str(populated)]) == 0
    assert not (populated / "webgl-context-loss.md").exists()
    assert "removed" in capsys.readouterr().out
    assert '"event": "remove"' in (populated / LOG_NAME).read_text(encoding="utf-8")
    assert '"slug": "webgl-context-loss"' in (populated / LOG_NAME).read_text(encoding="utf-8")


def test_rm_of_a_slug_that_is_not_there_is_refused_with_the_search_as_the_fix(populated, capsys):
    assert remove.main(["nope", "--store", str(populated)]) == 2
    assert "FIX: lore search" in capsys.readouterr().err
    assert len(list(populated.glob("*.md"))) == 3, "it deleted something else"


# --- confirm -------------------------------------------------------------------

def test_confirm_stamps_checked_and_leaves_updated_and_body_alone(populated, capsys):
    import datetime

    from pagelore import confirm
    from pagelore.lib import parse_page
    path = populated / "command-palette-highlight.md"
    before = parse_page(path)
    assert confirm.main(["command-palette-highlight", "--store", str(populated)]) == 0
    after = parse_page(path)
    checked = after.meta["checked"]
    datetime.datetime.fromisoformat(checked)
    assert checked.endswith("+00:00")
    assert after.meta["updated"] == before.meta["updated"]
    assert after.body == before.body
    assert "confirmed" in capsys.readouterr().out
    log = (populated / LOG_NAME).read_text(encoding="utf-8")
    assert '"event": "confirm"' in log and '"slug": "command-palette-highlight"' in log


def test_confirm_of_a_slug_that_is_not_there_is_refused_with_the_search_as_the_fix(
        populated, capsys):
    from pagelore import confirm
    assert confirm.main(["nope", "--store", str(populated)]) == 2
    assert "FIX: lore search" in capsys.readouterr().err


def test_confirm_refuses_a_page_whose_source_is_gone(populated, capsys):
    from pagelore import confirm
    path = populated / "webgl-context-loss.md"
    raw = path.read_bytes()
    assert confirm.main(["webgl-context-loss", "--store", str(populated)]) == 1
    err = capsys.readouterr().err
    assert "REJECTED:" in err and "src/terminal/renderer.ts" in err
    assert "FIX: lore edit webgl-context-loss" in err
    assert path.read_bytes() == raw
    log = populated / LOG_NAME
    assert not log.exists() or '"event": "reject"' not in log.read_text(encoding="utf-8")


# --- edit ----------------------------------------------------------------------

@pytest.fixture()
def editor(tmp_path, monkeypatch):
    """An $EDITOR that appends one line to whatever it is handed, and records the
    path it was given. Real editors block on a terminal; this one does the one
    thing the command has to survive, which is the file changing under it."""
    if sys.platform == "win32":
        pytest.skip("the fake editor is a shell script")
    script = tmp_path / "ed.sh"
    script.write_text("#!/bin/sh\nprintf '%s\\n' \"$1\" > \"$(dirname \"$0\")/seen\"\n"
                      "printf '\\nAppended by the editor.\\n' >> \"$1\"\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("VISUAL", "")
    monkeypatch.setenv("EDITOR", str(script))
    return tmp_path / "seen"


def test_edit_opens_the_page_in_the_editor_and_reports_the_change(populated, editor, capsys):
    before = (populated / "webgl-context-loss.md").read_text(encoding="utf-8")
    assert edit.main(["webgl-context-loss", "--store", str(populated)]) == 0
    assert editor.read_text(encoding="utf-8").strip() == str(populated / "webgl-context-loss.md")
    after = (populated / "webgl-context-loss.md").read_text(encoding="utf-8")
    assert after.startswith(before) and "Appended by the editor." in after
    out = capsys.readouterr().out
    assert "edited" in out and "webgl-context-loss" in out


def test_edit_that_leaves_the_page_thin_says_it_will_be_skipped(populated, tmp_path,
                                                                 monkeypatch, capsys):
    """The one way a hand edit goes wrong silently: a page cut below the floor is
    not refused, it is skipped by every search from then on. The editor cannot
    know the floor, so the command says it as the editor closes."""
    if sys.platform == "win32":
        pytest.skip("the fake editor is a shell script")
    script = tmp_path / "cut.sh"
    script.write_text("#!/bin/sh\nprintf -- '---\\nslug: webgl-context-loss\\n---\\n\\nshort\\n' "
                      "> \"$1\"\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("VISUAL", "")
    monkeypatch.setenv("EDITOR", str(script))
    assert edit.main(["webgl-context-loss", "--store", str(populated)]) == 0
    assert "skip" in capsys.readouterr().err


def test_edit_with_no_editor_configured_says_which_variable_to_set(populated, monkeypatch, capsys):
    monkeypatch.setenv("VISUAL", "")
    monkeypatch.setenv("EDITOR", "")
    monkeypatch.setattr(edit, "FALLBACK", None)
    assert edit.main(["webgl-context-loss", "--store", str(populated)]) == 2
    assert "EDITOR" in capsys.readouterr().err
