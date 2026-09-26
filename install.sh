#!/usr/bin/env sh
# project-memory is now `pagelore`, installed with a package manager.
#
#   pipx install pagelore        # or: npm install -g pagelore
#   lore init
#
# This file stays because the one-liner that fetches it is published and cannot be
# recalled. Deleting it would pipe GitHub's 404 page into a shell. It installs
# nothing, prints what to run instead, and exits 1 so a pipeline fails loudly
# rather than continuing as if something had been installed.
#
# It still does one thing, because nothing else can: remove what the old installer
# left on this machine. `pipx` and `npm` know nothing about a block that this
# script wrote into an agent's instruction file, so this is the only code that can
# take it back out.
#
#   sh install.sh --uninstall
#
# Your pages are not touched, here or by anything else. Scheduled for deletion in
# 0.6.0.
set -eu

NAME="project-memory"
UNINSTALL=0
DEST=""
SCOPE="user"

# The exact fences the old installer wrote. They have to match byte for byte or
# the block it left cannot be found, so they are copied rather than reworded.
MARK_BEGIN="<!-- project-memory: installed by install.sh — delete to this file's matching end marker to disconnect -->"
MARK_END="<!-- project-memory: end -->"
AGENT_FILES="$HOME/.claude/CLAUDE.md $HOME/.gemini/GEMINI.md $HOME/.codex/AGENTS.md"

while [ $# -gt 0 ]; do
  case "$1" in
    --uninstall) UNINSTALL=1; shift ;;
    --project)   SCOPE="project"; shift ;;
    --dest)      DEST="${2:?--dest needs a path}"; shift 2 ;;
    -h|--help)   UNINSTALL=0; break ;;
    *)           shift ;;          # every other old flag is ignored, not an error
  esac
done

if [ -z "$DEST" ]; then
  if [ "$SCOPE" = "project" ]; then DEST="$PWD/.agents/skills"; else DEST="$HOME/.agents/skills"; fi
fi

if [ "$UNINSTALL" = "1" ]; then
  target="$DEST/$NAME"
  removed=0

  # Claude Code read the skill through a symlink the install made. Only a link
  # that resolves to the directory being removed is ours; one pointing anywhere
  # else belongs to someone, and guessing by name would delete their work.
  if [ -d "$target" ]; then
    real="$(cd "$target" && pwd -P)"
    for link in "$HOME/.claude/skills/$NAME" "$PWD/.claude/skills/$NAME"; do
      if [ -L "$link" ] && [ -d "$link" ] && [ "$(cd "$link" && pwd -P)" = "$real" ]; then
        rm -f "$link"
        echo "removed:   $link"
        removed=1
      fi
    done
    rm -rf "$target"
    echo "removed:   $target"
    removed=1
  fi

  # The block the install wrote into an agent's instruction file, and only that
  # block: it is fenced by markers, so everything the user wrote around it stays.
  for f in $AGENT_FILES; do
    [ -f "$f" ] || continue
    if grep -qF "$MARK_BEGIN" "$f" 2>/dev/null; then
      MARK_BEGIN="$MARK_BEGIN" MARK_END="$MARK_END" TARGET="$f" python3 - <<'PY' || continue
import os, re
from pathlib import Path
target = Path(os.environ["TARGET"])
pattern = re.compile(re.escape(os.environ["MARK_BEGIN"]) + r".*?"
                     + re.escape(os.environ["MARK_END"]) + r"\n?", re.S)
text = target.read_text(encoding="utf-8")
target.write_text(pattern.sub("", text).rstrip("\n") + "\n", encoding="utf-8")
PY
      echo "removed:   the $NAME block in $f"
      removed=1
    fi
  done

  [ "$removed" = "1" ] || echo "nothing to remove: no skill at $target"

  cat <<'MSG'

Left alone on purpose:
  .memory/ in your projects     your pages — delete a store yourself if you mean to
  anything you wrote yourself   an agent definition, or a line you added by hand

If you also installed it as a plugin or extension, that install is separate:
  Claude Code   /plugin uninstall project-memory
  Gemini CLI    gemini extensions uninstall project-memory
  Codex, Cursor, Kimi   remove the directory you pointed them at

The program itself, if you have already installed it:
  pipx uninstall pagelore        # or: npm uninstall -g pagelore
  lore uninstall                 # takes out the 0.4.0 block; run it before the above
MSG
  exit 0
fi

cat <<'MSG'
This installer is retired. The program is a package now, and the command is `lore`.

  pipx install pagelore          # Python, no Node needed
  npm install -g pagelore        # Node, no pip needed — it vendors the Python
  lore init                      # writes the instruction block, asks before touching your config

Then, in any project:

  lore search "terminal freeze webgl context lost"
  lore write --slug some-slug --title "One line" --kind decision --source path/to/file --body -

Why: the command an agent had to run used to be an absolute path that differed per
install mode, and it was wrong for two of the three. `lore search` has no path in
it. Updates now arrive with `pipx upgrade pagelore`.

Your pages are safe. `.memory/` did not change and `lore search` finds every page.

Upgrading from 0.3.x? Do this first, in this order:

  sh install.sh --uninstall      # this file, once — takes out the old block
  pipx install pagelore
  lore init

If you skip the first step you get two instruction blocks, and the older one
points at a directory that is gone. Nothing errors: an agent that cannot load an
`@path` simply stops searching, silently.

  https://github.com/Krowli/pagelore
MSG
exit 1
