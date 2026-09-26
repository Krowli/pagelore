# Security policy

## Reporting a vulnerability

Please report security issues **privately**, through GitHub's private
vulnerability reporting:
<https://github.com/Krowli/pagelore/security/advisories/new>

Do not open a public issue for a vulnerability. Include what you found, how to
reproduce it, and the version (`lore --version`). A fix is released as a patch
version and credited in the advisory unless you prefer otherwise.

## Supported versions

Only the latest release receives fixes.

## Scope

pagelore reads and writes markdown files in a project's `.memory/` directory,
edits the agent configuration files `lore init` names, and runs `claude` or
`codex` for `mcp add`/`mcp remove` when you ask it to. It makes no network
requests. Relevant reports include, for example: a write escaping the store
directory, a page or query that makes `lore` execute something, `lore init` or
`lore uninstall` damaging content outside its fenced block, or the MCP server
answering on anything but stdio.

Pages are plain text you or your agent wrote. A store committed with
`--store tracked` is shared with everyone who can read the repository — do not
write secrets into it.
