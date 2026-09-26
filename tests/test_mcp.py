"""`lore mcp` speaks MCP over stdio, and lands every call in the code the CLI runs.

Two things are tested and they are different. `handle()` is the protocol: what a
client gets back for each method, including the errors. The subprocess tests are the
transport: that stdout carries JSON-RPC lines and nothing else — not the usage
text, not a refresh notice, not a `\\r\\n` from a Windows text stream — because one
stray byte on stdout breaks the client and produces no error anyone reads.
"""
import json
import subprocess

import conftest
import pytest

import pagelore
from pagelore import instructions, mcp, write

BODY = ("## Cause\n\nThe renderer drops its context when the display sleeps, which is "
        "invisible from the code and cost a day to find; recorded so the next agent "
        "reads this page instead of rediscovering it from the symptom.\n")


def rpc(method, params=None, mid=1):
    message = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        message["params"] = params
    return message


def call(name, arguments, mid=1):
    return rpc("tools/call", {"name": name, "arguments": arguments}, mid)


@pytest.fixture()
def project(tmp_path, monkeypatch):
    """A git repo with one source file and one page, and the cwd inside it.

    Both store environment variables are cleared, so each test states exactly how
    the server is meant to find the store.
    """
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    store = root / ".memory"
    store.mkdir()
    write.write_page(store, "display-sleep-context-loss", "Context loss on display sleep",
                     "bug", ["src/a.py"], BODY)
    monkeypatch.chdir(root)
    monkeypatch.delenv(mcp.STORE_ENV, raising=False)
    monkeypatch.delenv(mcp.PROJECT_ENV, raising=False)
    return root


def test_initialize_names_the_protocol_and_the_server(project):
    result = mcp.handle(rpc("initialize", {}))["result"]
    assert result["protocolVersion"] == mcp.PROTOCOL
    assert result["serverInfo"]["name"] == mcp.SERVER_NAME == "pagelore"
    assert result["serverInfo"]["version"] == pagelore.__version__


def test_initialize_tells_the_agent_when_to_use_each_tool(project):
    """An agent with only the server connected has no instruction file; the
    `instructions` of the initialize result are what tell it when to search and when
    to write. Kept short: a client sets this beside every other server's."""
    text = mcp.handle(rpc("initialize", {}))["result"]["instructions"]
    assert "search first with `memory_search`" in text
    assert "write the page with `memory_write`" in text
    assert "Before stating anything about this project" in text
    assert 500 < len(text) <= 2500
    assert "lore " not in text and "```" not in text, "a shell command reached a tool user"


def test_the_instructions_are_read_from_the_block_not_written_twice():
    """Two copies of one contract drift. Changing a marked paragraph of the block
    changes what the server says; an unmarked one does not reach it."""
    block = instructions.packaged()
    changed = block.replace("Treat them as the record", "Treat them as the ledger", 1)
    assert changed != block
    assert "the ledger" in instructions.mcp_instructions(changed)
    assert "the ledger" not in instructions.mcp_instructions(block)
    assert "Open a full page" in block
    assert "Open a full page" not in instructions.mcp_instructions(block)
    assert "<!-- mcp" not in instructions.render(), "a marker leaked into the file"


def test_tools_list_is_the_two_measured_tools(project):
    tools = mcp.handle(rpc("tools/list"))["result"]["tools"]
    assert [t["name"] for t in tools] == ["memory_search", "memory_write"]
    assert all(t["inputSchema"]["type"] == "object" for t in tools)


def test_search_finds_the_page_in_the_store_under_cwd(project):
    result = mcp.handle(call("memory_search", {"query": "display sleep context"}))["result"]
    text = result["content"][0]["text"]
    assert result["isError"] is False
    assert "display-sleep-context-loss" in text
    assert str(project / ".memory") in text


def test_a_refused_write_is_an_error_with_a_fix_line(project):
    result = mcp.handle(call("memory_write", {
        "slug": "thin", "title": "Thin", "kind": "bug", "sources": [], "body": "too short",
    }))["result"]
    assert result["isError"] is True
    assert "FIX:" in result["content"][0]["text"]
    assert not (project / ".memory" / "thin.md").exists()


def test_a_write_lands_in_the_store_claude_code_names_not_in_cwd(project, tmp_path, monkeypatch):
    """Claude Code promises no working directory to a stdio server; it names the
    project in CLAUDE_PROJECT_DIR instead. A server that trusted cwd would write the
    page into whatever directory it happened to be started from."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(mcp.PROJECT_ENV, str(project))
    result = mcp.handle(call("memory_write", {
        "slug": "from-elsewhere", "title": "Written from elsewhere", "kind": "decision",
        "sources": ["src/a.py"], "body": BODY,
    }))["result"]
    assert result["isError"] is False, result["content"][0]["text"]
    assert (project / ".memory" / "from-elsewhere.md").is_file()
    assert not (tmp_path / ".memory").exists()


def test_pagelore_dir_wins_over_claude_project_dir(project, tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere" / ".memory"
    elsewhere.mkdir(parents=True)
    monkeypatch.setenv(mcp.STORE_ENV, str(elsewhere))
    monkeypatch.setenv(mcp.PROJECT_ENV, str(project))
    result = mcp.handle(call("memory_write", {
        "slug": "explicit-store", "title": "Explicit store", "kind": "decision",
        "sources": ["src/a.py"], "body": BODY,
    }))["result"]
    assert result["isError"] is False, result["content"][0]["text"]
    assert (elsewhere / "explicit-store.md").is_file()
    assert not (project / ".memory" / "explicit-store.md").exists()


def test_an_unknown_tool_is_invalid_params(project):
    reply = mcp.handle(call("memory_delete", {}))
    assert reply["error"]["code"] == -32602


def test_an_unknown_method_is_method_not_found(project):
    reply = mcp.handle(rpc("resources/list"))
    assert reply["error"]["code"] == -32601


def test_a_notification_gets_no_reply(project):
    assert mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert mcp.handle({"jsonrpc": "2.0", "method": "notifications/cancelled"}) is None


def test_a_tool_crash_reaches_the_model_not_the_process(project, monkeypatch):
    def boom(args, store):
        raise RuntimeError("boom")
    monkeypatch.setattr(mcp, "do_search", boom)
    result = mcp.handle(call("memory_search", {"query": "x"}))["result"]
    assert result["isError"] is True
    assert "RuntimeError: boom" in result["content"][0]["text"]


def serve(project, feed: bytes):
    return subprocess.run([*conftest.LORE, "mcp"], input=feed, capture_output=True,
                          timeout=30, cwd=project,
                          env=conftest.lore_env(PAGELORE_DIR=str(project / ".memory")))


def test_stdout_carries_json_lines_and_nothing_else(project):
    """Bytes, not text: `text=True` would translate a Windows `\\r\\n` into `\\n`
    and hide the one transport defect this test exists to catch. The blank line
    and the junk line must be skipped, and the router's housekeeping after the
    server exits must print nothing."""
    feed = (json.dumps(rpc("initialize", {}, 1)) + "\n" + json.dumps(rpc("tools/list", None, 2))
            + "\n\nnot json\n").encode("utf-8")
    proc = serve(project, feed)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert b"\r" not in proc.stdout
    lines = [line for line in proc.stdout.decode("utf-8").split("\n") if line]
    assert len(lines) == 2, proc.stdout
    assert [json.loads(line)["id"] for line in lines] == [1, 2]
    assert {t["name"] for t in json.loads(lines[1])["result"]["tools"]} == \
        {"memory_search", "memory_write"}


def test_startup_says_which_store_it_serves_on_stderr(project):
    proc = serve(project, b"")
    assert proc.returncode == 0
    assert proc.stdout == b""
    assert str(project / ".memory") in proc.stderr.decode("utf-8", "replace")
