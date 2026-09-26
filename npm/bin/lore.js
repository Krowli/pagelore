#!/usr/bin/env node
"use strict";
/*
 * `lore`, for people who have npm and would rather not think about Python.
 *
 * This is a shim, not a port. It finds an interpreter and hands it the vendored
 * package; every decision about ranking, the write gate and the store lives in
 * that Python and nowhere here, so the two install routes cannot drift.
 *
 * Three things here are deliberate and were each paid for:
 *
 * 1. No `pip`, and no `postinstall`. A postinstall script that installs packages
 *    is the thing corporate npm mirrors and `--ignore-scripts` both break, and it
 *    fails at install time in a way the user cannot act on. The Python is copied
 *    into the tarball at pack time and imported from there.
 * 2. The first candidate is spawned with the real arguments rather than probed
 *    first with a throwaway `--version`. A cold search is around 86 ms, and a
 *    probe process would roughly double the figure the README publishes.
 * 3. Exit 69 (EX_UNAVAILABLE) from `python -m pagelore` means "this interpreter
 *    is older than the floor". The package prints nothing in that case, because a
 *    message there would print once per candidate; the message below prints once,
 *    after every candidate has been tried.
 */
const { spawnSync } = require("child_process");
const path = require("path");

const VENDOR = path.join(__dirname, "..", "vendor");
// The name the user actually typed. npm installs both `lore` and `pagelore` as
// links to this file, and node keeps the invoked link in argv[1], so the Python
// can put the right one in its messages and — the part that matters — in the
// instruction block it writes. Without this, someone whose machine already has a
// different `lore` installs pagelore, runs `pagelore init`, and the block tells
// their agent to run `lore`: the other program. That is the exact failure the
// second name exists to prevent.
const INVOKED_AS = path.basename(process.argv[1] || "lore").replace(/\.js$/, "");
const FLOOR = "3.9";
const TOO_OLD = 69;

// Order is platform-specific because Windows has no `python3`: its installer puts
// `py`, `python` and `pymanager` on PATH, and `python3` only as an optional
// versioned alias such as `python3.14.exe`. A shim that only knew `python3` was a
// real bug in the installer this replaces.
const CANDIDATES = process.platform === "win32"
  ? [["py", ["-3"]], ["python", []], ["python3", []]]
  : [["python3", []], ["python", []]];

// PROJECT_MEMORY_PYTHON is the pre-0.6.0 name. It is still read, with a warning
// on stderr, until 0.7.0 removes it.
function namedPython() {
  if (process.env.PAGELORE_PYTHON) return process.env.PAGELORE_PYTHON;
  const old = process.env.PROJECT_MEMORY_PYTHON;
  if (old && !namedPython.warned) {
    namedPython.warned = true;
    process.stderr.write("pagelore: PROJECT_MEMORY_PYTHON is deprecated, use PAGELORE_PYTHON; " +
                         "the old name stops working in 0.7.0\n");
  }
  return old || "";
}

function candidates() {
  const named = namedPython();
  // Exclusive, not first-in-list: someone who names an interpreter and gets a
  // different one silently has been given the wrong answer by a helpful default.
  return named ? [[named, []]] : CANDIDATES;
}

function run() {
  const args = process.argv.slice(2);
  const env = Object.assign({}, process.env, {
    PYTHONPATH: VENDOR + (process.env.PYTHONPATH ? path.delimiter + process.env.PYTHONPATH : ""),
    // Vendored source in a global npm prefix is often not writable, and a failed
    // write of a .pyc is a warning nobody can act on.
    PYTHONDONTWRITEBYTECODE: "1",
    PAGELORE_INVOKED_AS: INVOKED_AS,
  });

  const tried = [];
  for (const [command, prefix] of candidates()) {
    const result = spawnSync(command, prefix.concat(["-m", "pagelore"], args),
                             { stdio: "inherit", env: env });
    if (result.error && result.error.code === "ENOENT") {
      tried.push(command + ": not installed");
      continue;
    }
    if (result.error) {
      tried.push(command + ": " + result.error.message);
      continue;
    }
    if (result.status === TOO_OLD) {
      tried.push(command + ": older than Python " + FLOOR);
      continue;
    }
    if (result.signal) {
      process.kill(process.pid, result.signal);
      return 1;
    }
    return result.status === null ? 1 : result.status;
  }

  const named = namedPython();
  process.stderr.write(
    "lore needs Python " + FLOOR + " or newer and could not find it.\n" +
    tried.map(function (line) { return "  tried " + line + "\n"; }).join("") +
    (named
      ? "PAGELORE_PYTHON is set to " + named + ", so nothing else was tried.\n" +
        "FIX: unset PAGELORE_PYTHON, or point it at a working Python " + FLOOR + "+.\n"
      : "FIX: install Python from https://python.org/downloads, or set " +
        "PAGELORE_PYTHON to one you already have.\n" +
        "     Already have pipx? `pipx install pagelore` needs no Node at all.\n")
  );
  return 1;
}

process.exit(run());
