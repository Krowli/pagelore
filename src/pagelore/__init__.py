"""pagelore: durable project memory as markdown pages on disk, searchable without a server."""

# The one place the version is written. The build backend AST-reads this literal,
# every other consumer imports it, and one test asserts nothing else declares a
# version of its own. It used to live in ten hand-edited files guarded by five
# drift tests; the fix was not a better guard, it was having one place to edit.
#
# Keep this file parseable by any Python 3: no `from __future__`, no annotations,
# nothing computed. It is read before the interpreter floor has been checked, and
# by a build backend that must not import it.
__version__ = "0.8.3"
