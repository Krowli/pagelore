#!/usr/bin/env bash
# Local rehearsal of the release path, without publishing anything.
#
# CI's install-smoke job proves a freshly built distribution works as a user
# would use it. This script is that same job run from the repo: it builds the
# wheel, installs it into an isolated environment (pipx when present, else a
# throwaway venv), and runs the same steps — write, search, --touching, stats,
# doctor, the refused-write FIX: line, and the whole MCP route. Everything lives
# under one temp dir and the run gets a throwaway HOME, so nothing on this
# machine is touched: not the real `lore`, not a store, not a config file.
#
#   bash tools/smoke.sh                 # uses python3
#   PYTHON=.venv/bin/python bash tools/smoke.sh
#
# The one thing this cannot rehearse is the act of publishing itself; that has
# its own rehearsal, TestPyPI, wired into the release workflow's dry-run.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/pagelore-smoke.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
step() { echo; echo "== $* =="; }

cd "$ROOT"
step "build the wheel"
"$PYTHON" -m pip wheel --quiet --no-deps --wheel-dir "$TMP/dist" .
wheel="$(ls "$TMP"/dist/*.whl)"
echo "   built $(basename "$wheel")"

step "install it as a user would"
mkdir -p "$TMP/bin"
if command -v pipx >/dev/null 2>&1; then
    PIPX_HOME="$TMP/pipx-home" PIPX_BIN_DIR="$TMP/bin" pipx install --quiet --force "$wheel"
else
    "$PYTHON" -m venv "$TMP/venv"
    "$TMP/venv/bin/pip" install --quiet "$wheel"
    ln -s "$TMP/venv/bin/lore" "$TMP/bin/lore"
fi
LORE="$TMP/bin/lore"
"$LORE" --version

# A fresh project, and a HOME that is nowhere near the machine's real one, so
# init/doctor/uninstall are safe to run for real. PATH leads with the bin dir
# exactly as pipx's own ensurepath does: `lore doctor` proves the MCP handshake
# by running `lore mcp` from PATH, and a stale `lore` anywhere else on this
# machine must not be the one it finds — that is the two-lores trap this script
# exists to rehearse against.
HOME_DIR="$TMP/home"; mkdir -p "$HOME_DIR"
WORK="$TMP/project"; mkdir -p "$WORK/src" "$WORK/.memory"
( cd "$WORK" && git init -q && echo 'export {}' > src/a.ts )

run() { ( cd "$WORK" && PATH="$TMP/bin:$PATH" HOME="$HOME_DIR" "$@" ); }

step "write a page, find it again"
run "$LORE" write --slug probe --title "Probe" --kind bug --source src/a.ts --body - <<'PMEOF'
## Cause

Enough body to clear the floor the write gate applies, so the page is
actually written and the command after this one has something to find.
A shorter body is refused, which is the behaviour being relied on here.
PMEOF
run "$LORE" search "probe floor" | grep -q probe \
    || fail "the page was written but search cannot find it"
run "$LORE" search --touching src/a.ts | grep -q "touches src/a.ts" \
    || fail "--touching did not name the page"
run "$LORE" stats
( cd "$WORK" && HOME="$HOME_DIR" "$LORE" doctor >/dev/null 2>&1 ) || true
echo "   (doctor exits non-zero with nothing connected, which is correct here)"

step "a refused write says how to fix it, and exits non-zero"
if run "$LORE" write --slug thin --title "Thin" --kind bug --body "too short" 2>"$TMP/err.txt"; then
    fail "a page with no source and no body was accepted"
fi
grep -q "FIX:" "$TMP/err.txt" || fail "a refusal printed no FIX: line"

step "bare invocation exits 0, an unknown command exits 2"
run "$LORE" >/dev/null || fail "a probe of the command must not read failure"
if run "$LORE" nonsense 2>"$TMP/err.txt"; then
    fail "an unknown command exited 0"
fi
grep -q "FIX:" "$TMP/err.txt" || fail "an unknown command printed no FIX: line"

step "the MCP server answers tools/list, and init, doctor and uninstall know it"
( cd "$WORK" && HOME="$HOME_DIR" \
    printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
                  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
    | "$LORE" mcp > "$TMP/out.jsonl" )
"$PYTHON" - "$TMP/out.jsonl" <<'PY'
import json, sys
ls = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
assert len(ls) == 2, ls
assert {t['name'] for t in ls[1]['result']['tools']} == {'memory_search', 'memory_write'}, ls
print(f"   tools/list answered {sorted(t['name'] for t in ls[1]['result']['tools'])}")
PY

run "$LORE" init --scope project --agent claude --via mcp --yes
grep -q '"pagelore"' "$WORK/.mcp.json" || fail "init did not register the MCP server"
run "$LORE" doctor --json > "$TMP/doctor.json"
"$PYTHON" - "$TMP/doctor.json" <<'PY'
import json, sys
f = {r['check']: r for r in json.load(open(sys.argv[1]))['findings']}
assert f['mcp:claude']['ok'] is True, f['mcp:claude']
assert f['mcp:handshake']['ok'] is True, f['mcp:handshake']
print("   doctor saw the MCP registration and the handshake answered")
PY
run "$LORE" doctor
run "$LORE" uninstall
test ! -f "$WORK/.mcp.json" || fail "uninstall left .mcp.json behind"
echo "   uninstall took the MCP registration back out"

echo
echo "smoke passed: the wheel installs and works end to end."