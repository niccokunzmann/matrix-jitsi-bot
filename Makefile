
SPHINXOPTS      ?=
PYTHONVERSION   = >=3.12,<3.15
BUILDDIR	   = _build
DOCS_DIR	   = docs
RUFFPATH	   = .venv/bin/ruff
SPHINXBUILD     = .venv/bin/sphinx-build
SPHINXAUTOBUILD = .venv/bin/sphinx-autobuild
ALLSPHINXOPTS   = -W -d $(BUILDDIR)/doctrees $(SPHINXOPTS) .


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
init: clean clean-all .venv  ## Clean docs build directory and virtual environment, then set up a fresh one

.PHONY: clean
clean:  ## Clean the docs build directory
	cd $(DOCS_DIR) && rm -rf $(BUILDDIR)

.PHONY: clean-all
clean-all: clean  ## Clean the docs build directory and the virtual environment
	rm -rf .venv/
# /environment management


# development
.PHONY: dev
dev: .venv  ## Install required Python, create Python virtual environment, install package and development requirements

.PHONY: format
format: .venv  ## Format the code base with ruff
	$(RUFFPATH) format
	$(RUFFPATH) check --fix

.PHONY: test
test: .venv  ## Run the test suite
	@uv run pytest

.PHONY: dist
dist: .venv  ## Build the sdist and wheel into dist/
	@uv build

.PHONY: install
install:  ## Install this checkout as the matrix-jitsi-bot command, editable
	pipx install --editable --force .
# /development


# documentation builders
.PHONY: html
html: .venv  ## Build the documentation as HTML
	cd $(DOCS_DIR) && $(realpath $(SPHINXBUILD)) -b html $(ALLSPHINXOPTS) $(BUILDDIR)/html
	@echo
	@echo "Build finished. The HTML pages are in $(DOCS_DIR)/$(BUILDDIR)/html."

.PHONY: livehtml
livehtml: .venv  ## Rebuild the documentation on changes, with live-reload in the browser
	cd $(DOCS_DIR) && $(realpath $(SPHINXAUTOBUILD)) \
		--watch "../matrix_jitsi_bot/" \
		--ignore "../matrix_jitsi_bot/tests" \
		--ignore "*/migrations/*" \
		-b html . "$(BUILDDIR)/html" $(SPHINXOPTS)

.PHONY: linkcheck
linkcheck: .venv  ## Check the documentation for broken links
	cd $(DOCS_DIR) && $(realpath $(SPHINXBUILD)) -b linkcheck $(ALLSPHINXOPTS) $(BUILDDIR)/linkcheck
	@echo
	@echo "Link check complete; look for any errors in the above output " \
		"or in $(DOCS_DIR)/$(BUILDDIR)/linkcheck/ ."
# /documentation builders
