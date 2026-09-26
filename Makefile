# The local dev loop for this repository. Everything a change needs before it
# earns a tag: the editable environment, both retrieval paths, lint, and the
# install-smoke rehearsal that CI runs against the built wheel.
#
#   make dev     one command into the editable environment
#   make test    pytest on both retrieval paths, then ruff
#   make smoke   build the wheel, install it in isolation, run it end to end
#
# PYTHON picks the interpreter for `dev`; override with e.g. `make dev PYTHON=/opt/homebrew/bin/python3`.
PYTHON ?= python3
VENV := .venv

.PHONY: dev test lint smoke eval-panes clean

dev:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --quiet -e ".[dev]"
	@echo ""
	@echo "dev env ready. The 'lore' on your PATH may be a released build;"
	@echo "the one that tracks this tree is:"
	@echo "  $(abspath $(VENV))/bin/lore"
	@echo "  make test"

test:
	$(VENV)/bin/pytest
	PAGELORE_NO_FTS5=1 $(VENV)/bin/pytest
	$(VENV)/bin/ruff check .

lint:
	$(VENV)/bin/ruff check .

smoke:
	PYTHON="$(abspath $(VENV)/bin/python)" bash tools/smoke.sh

# The panes experiment's number: find + read a page against this store, in
# keystrokes, CLI round trip versus the opencode-shaped screen.
eval-panes:
	PYTHONPATH=src $(VENV)/bin/python evals/panes_keystrokes.py

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache