import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# How a subprocess test runs the program. `-m` rather than a console script so the
# suite works in a bare clone with nothing installed, which is the same reason
# pyproject keeps `pythonpath = ["src"]`.
LORE = [sys.executable, "-m", "pagelore"]


def lore_env(**extra) -> dict:
    """A child that can import the package and will not touch the user's home."""
    return {**os.environ, "PYTHONPATH": str(REPO / "src"),
            "PAGELORE_NO_REFRESH": "1", **extra}


@pytest.fixture()
def store(tmp_path):
    """An empty memory store in a temp dir."""
    d = tmp_path / ".memory"
    d.mkdir()
    return d


# Pages under MIN_BODY are skipped by search on purpose, so every fixture page
# that has to be found carries enough body to be a page the writer would accept.
FILLER = ("\n\nRecorded so the next agent does not rediscover it: the cause sits far "
          "from the symptom, the fix is two lines, and the alternative was rejected "
          "for a reason that is not visible in the code.\n")


@pytest.fixture()
def populated(store):
    from pagelore import write as memory_write
    memory_write.write_page(
        store, "webgl-context-loss", "xterm WebGL context loss on display sleep",
        "bug", ["src/terminal/renderer.ts"],
        "## Cause\n\nThe WebGL renderer loses its context when the display sleeps." + FILLER)
    memory_write.write_page(
        store, "command-palette-highlight", "Command palette match highlighting",
        "concept", [],
        "## Context\n\nFuzzy match ranges are highlighted in the palette." + FILLER)
    # Bilingual page: the corpus mixes Russian and English.
    memory_write.write_page(
        store, "sqlite-writer-ownership", "Кто пишет в coordination.db",
        "decision", ["src-tauri/src/database.rs"],
        "## Решение\n\nТолько MCP сервер пишет в базу. Frontend uses Tauri commands." + FILLER)
    return store


WINDOWS = sys.platform == "win32"

# `os.geteuid` and `os.mkfifo` do not exist on Windows, and file modes there do not
# mean what chmod means on POSIX — a 0o500 directory stays writable. Tests that
# depend on either are skipped rather than faked, so the Windows run reports what
# it actually covered.
needs_posix = pytest.mark.skipif(WINDOWS, reason="POSIX-only: file modes, mkfifo, euid")


def is_root() -> bool:
    return not WINDOWS and os.geteuid() == 0
