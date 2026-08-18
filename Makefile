
PYTHONVERSION   = >=3.12,<3.15


# environment management
.venv:  ## Install required Python, create Python virtual environment, and install package requirements
	@uv python install "$(PYTHONVERSION)"
	@uv venv --python "$(PYTHONVERSION)"
	@uv sync --group dev
	@uv run pre-commit install

.PHONY: sync
sync:  ## Sync package requirements
	@uv sync

.PHONY: init
init: clean clean-python .venv  ## Clean docs build directory, Python virtual environment, and initialize Python virtual environment

.PHONY: clean
clean:  ## Clean docs build directory
	cd $(DOCS_DIR) && rm -rf $(BUILDDIR)/

.PHONY: clean-python
clean-python: clean
	rm -rf .venv/


# development
.PHONY: dev
dev: .venv  ## Install required Python, create Python virtual environment, install package and development requirements

.PHONY: format
format: .venv  ## Format the code base with ruff
	$(RUFFPATH) format
	$(RUFFPATH) check --fix
# /development
