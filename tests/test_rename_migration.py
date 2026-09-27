"""0.6.0 renamed everything `project-memory` to `pagelore`: the home directory, the
environment variables and the MCP server. An upgrade has to arrive without the
person editing anything, and without a single store or agent going quiet — the
failure every part of this product is shaped against is the one with no error.
"""
import io
import json
import shutil
import subprocess

import conftest
import pytest

from pagelore import cli, doctor, init, instructions, lib, uninstall


@pytest.fixture()
def machine(tmp_path, monkeypatch):
    """A throwaway home with no home override, so the default paths are live."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("HOMEDRIVE", raising=False)
    monkeypatch.delenv("HOMEPATH", raising=False)
    for name in ("HOME", "NO_REFRESH", "DIR"):
        monkeypatch.delenv(lib.ENV_PREFIX + name, raising=False)
        monkeypatch.delenv(lib.LEGACY_ENV_PREFIX + name, raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.chdir(project)
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None)
    monkeypatch.setattr(lib, "_warned_env", set())
    return home, project


def old_install(home, project):
    """What 0.5 left: the block, a `--store home` store with a page in it, the
    project's `.memory` symlinked into it, and an include in the global CLAUDE.md."""
    old = home / ".project-memory"
    (old / project.name).mkdir(parents=True)
    (old / "AGENT.md").write_text("old block\n", encoding="utf-8")
    (old / project.name / "a-page.md").write_text("page\n", encoding="utf-8")
    (project / ".memory").symlink_to(old / project.name)
    claude = home / ".claude" / "CLAUDE.md"
    claude.write_text(f"# Mine\n\n@{old}/AGENT.md is what I used to include\n\n"
                      + instructions.fenced(f"@{old / 'AGENT.md'}"), encoding="utf-8")
    return old, claude


def test_the_old_home_moves_once_and_nothing_goes_dark(machine):
    home, project = machine
    old, claude = old_install(home, project)
    new = home / ".pagelore"

    assert init.migrate_legacy_home() == new
    assert (new / "AGENT.md").read_text(encoding="utf-8") == "old block\n"
    assert old.is_symlink() and old.resolve() == new.resolve()
    # The store symlink points at the old path, in a repository no program can
    # enumerate; it still reaches the page through the link left behind.
    assert (project / ".memory" / "a-page.md").read_text(encoding="utf-8") == "page\n"
    text = claude.read_text(encoding="utf-8")
    assert f"@{new / 'AGENT.md'}" in text, "the managed include was not repointed"
    assert f"@{old}/AGENT.md is what I used to include" in text, "a line outside the block changed"

    assert init.migrate_legacy_home() is None, "a second run moved something again"


def test_a_command_moves_it_and_init_reports_it(machine, monkeypatch):
    home, project = machine
    old_install(home, project)
    assert cli.main(["list"]) == 0
    assert (home / ".pagelore").is_dir() and (home / ".project-memory").is_symlink()

    home2 = home.parent / "home2"
    (home2 / ".project-memory").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home2))
    monkeypatch.setenv("USERPROFILE", str(home2))
    out = io.StringIO()
    init.main(["--print"], stdin=io.StringIO(""), stdout=out, interactive=False)
    assert "moved" in out.getvalue() and ".pagelore" in out.getvalue()


def test_no_refresh_leaves_the_old_home_where_it_is(machine, monkeypatch):
    home, project = machine
    old_install(home, project)
    monkeypatch.setenv(instructions.NO_REFRESH_ENV, "1")
    assert cli.main(["list"]) == 0
    assert not (home / ".pagelore").exists()


def test_two_homes_are_not_merged_and_doctor_says_so(machine):
    home, project = machine
    old_install(home, project)
    (home / ".pagelore").mkdir()
    assert init.migrate_legacy_home() is None
    assert not (home / ".project-memory").is_symlink()
    rows = {row["check"]: row for row in doctor.findings()}
    assert rows["home"]["ok"] is False
    assert "both" in rows["home"]["detail"]


def test_an_explicit_home_is_never_moved(machine, monkeypatch, tmp_path):
    home, project = machine
    old_install(home, project)
    monkeypatch.setenv(instructions.HOME_ENV, str(tmp_path / "chosen"))
    assert init.migrate_legacy_home() is None
    assert (home / ".project-memory").is_dir() and not (home / ".pagelore").exists()


# --- Environment ----------------------------------------------------------------


def test_an_old_variable_still_works_and_says_it_is_going(machine, monkeypatch, capsys):
    monkeypatch.setenv("PROJECT_MEMORY_DIR", "/old")
    assert lib.env(lib.STORE_ENV) == "/old"
    assert lib.env(lib.STORE_ENV) == "/old"
    err = capsys.readouterr().err
    assert err.count("PROJECT_MEMORY_DIR is deprecated, use PAGELORE_DIR") == 1
    # Old names keep working until a release removes them; the warning must not
    # promise a version that has already shipped with them still working.
    assert "a future release" in err and "0.7.0" not in err

    monkeypatch.setenv("PAGELORE_DIR", "/new")
    assert lib.env(lib.STORE_ENV) == "/new"


def test_the_warning_stays_off_json_stdout(machine, tmp_path):
    store = tmp_path / "s" / ".memory"
    store.mkdir(parents=True)
    env = conftest.lore_env(PROJECT_MEMORY_DIR=str(store))
    env.pop("PAGELORE_DIR", None)
    proc = subprocess.run([*conftest.LORE, "search", "anything", "--json"], env=env,
                          capture_output=True, text=True)
    json.loads(proc.stdout)
    assert "PROJECT_MEMORY_DIR is deprecated" in proc.stderr


# --- MCP ------------------------------------------------------------------------


def mcp_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


OLD_ENTRY = {"type": "stdio", "command": "lore", "args": ["mcp"]}


def test_init_replaces_an_old_entry_it_wrote(machine):
    _, project = machine
    (project / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"project-memory": OLD_ENTRY, "other": {"command": "x"}}}),
        encoding="utf-8")
    init.main(["--scope", "project", "--agent", "claude", "--via", "mcp", "--yes"],
              stdin=io.StringIO(""), stdout=io.StringIO(), interactive=False)
    servers = mcp_json(project / ".mcp.json")["mcpServers"]
    assert "project-memory" not in servers
    assert servers["pagelore"] == OLD_ENTRY and servers["other"] == {"command": "x"}


def test_init_leaves_an_old_entry_someone_edited(machine):
    _, project = machine
    edited = {**OLD_ENTRY, "env": {"PROJECT_MEMORY_DIR": "/somewhere"}}
    (project / ".mcp.json").write_text(json.dumps({"mcpServers": {"project-memory": edited}}),
                                       encoding="utf-8")
    init.main(["--scope", "project", "--agent", "claude", "--via", "mcp", "--yes"],
              stdin=io.StringIO(""), stdout=io.StringIO(), interactive=False)
    servers = mcp_json(project / ".mcp.json")["mcpServers"]
    assert servers["project-memory"] == edited and "pagelore" in servers
    rows = {row["check"]: row for row in doctor.findings()}
    assert rows["mcp-legacy:claude"]["ok"] is False


def test_init_removes_the_old_user_entry_through_the_harness(machine, monkeypatch):
    home, project = machine
    (home / ".claude.json").write_text(json.dumps(
        {"mcpServers": {"project-memory": {**OLD_ENTRY, "env": {}}}}), encoding="utf-8")
    ran = []
    monkeypatch.setattr(init, "_project_root", lambda: project)
    monkeypatch.setattr(init.subprocess, "run", lambda argv, *a, **k: ran.append(list(argv))
                        or subprocess.CompletedProcess(argv, 0, "", ""))
    monkeypatch.setattr(shutil, "which",
                        lambda name, *a, **k: "/fake/claude" if name == "claude" else None)
    init.main(["--agent", "claude", "--via", "mcp", "--yes"],
              stdin=io.StringIO(""), stdout=io.StringIO(), interactive=False)
    assert ran == [["/fake/claude", "mcp", "remove", "--scope", "user", "project-memory"],
                   ["/fake/claude", "mcp", "add", "--transport", "stdio", "--scope", "user",
                    "pagelore", "--", "lore", "mcp"]]


def test_uninstall_removes_both_names(machine, capsys):
    home, project = machine
    (project / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"project-memory": OLD_ENTRY, "pagelore": OLD_ENTRY}}), encoding="utf-8")
    (home / ".codex").mkdir()
    (home / ".codex" / "config.toml").write_text(
        '[mcp_servers.project-memory]\ncommand = "lore"\n', encoding="utf-8")
    assert uninstall.main([]) == 0
    assert not (project / ".mcp.json").exists()
    assert "codex mcp remove project-memory" in capsys.readouterr().out


def test_doctor_names_an_old_registration(machine):
    home, _ = machine
    (home / ".gemini").mkdir()
    (home / ".gemini" / "settings.json").write_text(json.dumps(
        {"mcpServers": {"project-memory": {"command": "lore", "args": ["mcp"]}}}),
        encoding="utf-8")
    rows = {row["check"]: row for row in doctor.findings()}
    assert rows["mcp-legacy:gemini"]["ok"] is False
    assert "lore init --via mcp" in rows["mcp-legacy:gemini"]["detail"]
