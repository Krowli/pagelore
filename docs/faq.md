# FAQ

**Why markdown files instead of a database?**
Because they survive everything else: they are greppable, diffable, reviewable in
a pull request, readable by any agent or person, and they outlive the tool that
wrote them. The SQLite FTS5 index is only a cache, outside the store and never in
git; delete it whenever you like. It rebuilds itself, and if it cannot be used at
all — no `sqlite3` in this Python, a read-only checkout, a sibling process
rebuilding it — the pages are read and ranked directly instead. The markdown is
always the source of truth.

**Do I need a server, an API key, or an embedding model?**
No. `lore` is a command that runs and exits; the runtime is the Python standard
library. `lore mcp` is a stdio server your agent starts and stops itself.

**Why BM25F and not embeddings?**
Measured. A transformer hybrid was better by +0.046 nDCG@10 but cost about a
second and a gigabyte per search; static embeddings did not clear zero. The
numbers are in [measurements](measurements.md#embeddings-measured-and-refused).

**Which agents does it work with?**
Anything that can run a shell command or an MCP stdio server. `lore init` sets up
Claude Code, Gemini CLI, Codex CLI and Cursor; see [connecting agents](agents.md).

**Instruction file or MCP?**
The file is the default because it is the arm that has never missed on Claude
Code; MCP alone at default settings searched 0/15, later 3/5 and 4/10, and 10/10
once the server sent its own instructions (0.5.1). You can have both.
See [MCP](mcp.md#file-mcp-or-both).

**Does the agent use it without being told?**
Only if something tells it the memory exists. With the instruction line, 15/15;
with nothing connected, 0/15. That is why `lore doctor` calls an unconnected
install a failure.

**Should the pages be committed?**
Your choice, per project: private and gitignored (the default), committed and
reviewed (`--store tracked`), or outside the repository (`--store home`). The
log, which holds every query, is never committed.

**Can I edit a page by hand?**
`lore edit <slug>` opens it in your editor and warns if the result fell under the
search floor. Hand-edited frontmatter is the one input the parser cannot
round-trip, so prefer re-running `lore write` with the same slug: it replaces
same-header sections and appends new ones.

**How do I record that a decision was reversed?**
Write the new page with `--supersedes <old-slug>`. The old page stays searchable
but is scored at half, marked `⚠ superseded by <slug>`, and `lore show` points to
the replacement.

**Why is the package `pagelore` and the command `lore`?**
`project-memory` and `pm` were both already taken on PyPI and npm by unrelated
products in the same niche. `pagelore` is also installed as a command, for a
machine where something else already owns `lore`; every message names whichever
you ran. Since 0.6.0 everything else carries the same name: the repository, the
MCP server, `~/.pagelore` and the `PAGELORE_*` variables; see
[upgrading to 0.6.0](installation.md#upgrading-to-060-one-name).

**I used 0.3.x.**
It installed a skill directory that is gone now; see
[upgrading from 0.3.x](installation.md#upgrading-from-03x).

**Does it phone home?**
No. It makes no network requests; the log stays in the store, out of git.

**Why is every rule so specific?**
Because no proposal lands without a number from `evals/` or a failing test it
fixes. The reasoning behind each decision is a page in this repository's own
`.memory/`.
