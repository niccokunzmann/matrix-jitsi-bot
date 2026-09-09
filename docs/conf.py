# matrix-jitsi-bot documentation build configuration file
import datetime
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))  # update docs from source for livehtml

# Django models (matrix_jitsi_bot.db.models) need the app registry populated
# before autodoc/apidoc can import them.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "matrix_jitsi_bot.settings")
import django  # noqa: E402

django.setup()

# The CLI reference (docs/reference/cli.rst) includes this file rather than
# documenting the command line interface by hand - regenerated on every
# build straight from the `matrix-jitsi-bot` command's own `--help` output,
# the same way sphinx.ext.apidoc regenerates reference/api/ from docstrings.
import subprocess  # noqa: E402

import matrix_jitsi_bot  # noqa: E402

_CLI_REFERENCE = HERE / "reference" / "_generated" / "cli.md"
_CLI_REFERENCE.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(  # noqa: S603
    [
        sys.executable,
        "-m",
        "typer",
        "matrix_jitsi_bot.cli",
        "utils",
        "docs",
        "--name",
        "matrix-jitsi-bot",
        "--output",
        str(_CLI_REFERENCE),
    ],
    check=True,
    cwd=ROOT,
)
# Demote headings by one level - the generated file starts at `#`, but it's
# included under this page's own top-level heading, not standalone.
_CLI_REFERENCE.write_text(re.sub(r"(?m)^(#+)", r"#\1", _CLI_REFERENCE.read_text()))

extensions = [
    "myst_parser",
    "notfound.extension",
    "sphinx.ext.apidoc",
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx_autodoc_typehints",  # must be loaded after sphinx.ext.napoleon
    "sphinx_copybutton",
    "sphinx_design",
    "sphinx_reredirects",
]
source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
master_doc = "index"
# False positive: myst_parser checks every title in a document that
# includes MyST content, including the host RST document's own top-level
# title - which is correctly at "H1", not the "H2" it expects nested
# content to start at.
suppress_warnings = ["myst.header"]

project = "matrix-jitsi-bot"
this_year = datetime.date.today().year  # noqa: DTZ011
copyright = f"{this_year}, Nicco Kunzmann"  # noqa: A001
release = matrix_jitsi_bot.__version__
version = release

# -- Options for HTML output -------------------------------------------------

templates_path = []
exclude_patterns = [
    "reference/api/modules.rst",
    # Included by reference/cli.rst, not a standalone document.
    "reference/_generated/cli.md",
]
html_theme = "pydata_sphinx_theme"
html_theme_options = {
    "icon_links": [
        {
            "name": "GitHub",
            "url": "https://github.com/niccokunzmann/matrix-jitsi-bot",
            "icon": "fa-brands fa-square-github",
            "type": "fontawesome",
            "attributes": {"target": "_blank", "rel": "noopener me"},
        },
    ],
    "footer_end": ["theme-version", "sphinx-version"],
    "logo": {"text": "matrix-jitsi-bot"},
    "navigation_with_keys": True,
    "show_nav_level": 2,
    "show_toc_level": 2,
    "secondary_sidebar_items": ["edit-this-page", "page-toc", "sourcelink"],
    "use_edit_page_button": True,
}
html_context = {
    "github_user": "niccokunzmann",
    "github_repo": "matrix-jitsi-bot",
    "github_version": "main",
    "doc_path": "docs",
}
html_static_path = ["_static"]
html_css_files = ["custom.css"]
pygments_style = "sphinx"
smartquotes_action = "De"

# -- linkcheck builder configuration ----------------------------------
linkcheck_ignore = [
    r"https://matrix\.org",
]
linkcheck_anchors = True
linkcheck_timeout = 5
linkcheck_retries = 1

# -- sphinx.ext.apidoc options -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/extensions/apidoc.html
apidoc_modules = [
    {
        "path": "../matrix_jitsi_bot",
        "destination": "reference/api",
        "exclude_patterns": [
            "**/tests*",
            "**/migrations*",
        ],
        "separate_modules": True,
        "automodule_options": {
            "members",
            "show-inheritance",
            "undoc-members",
            "private-members",
            "special-members",
        },
    }
]
autoclass_content = "both"

# -- sphinx.ext.autodoc options -------------------------------------------------
# private-members/special-members: every function is documented
# (enforced by tests/test_docstrings.py), including module-private
# helpers and dunder methods - and docstrings cross-reference each
# other by fully qualified name, which needs a documented target to
# resolve, private/dunder methods included.
autodoc_default_options = {
    "members": True,
    "show-inheritance": True,
    "undoc-members": True,
    "private-members": True,
    "special-members": True,
}

# -- sphinx.ext.intersphinx configuration ----------------------------------
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "django": (
        "https://docs.djangoproject.com/en/stable/",
        "https://docs.djangoproject.com/en/stable/_objects/",
    ),
    "sphinx": ("https://www.sphinx-doc.org/en/master/", None),
}

# -- sphinx.ext.napoleon configuration ----------------------------------
napoleon_use_param = True
napoleon_google_docstring = True
napoleon_attr_annotations = True

# -- sphinx_copybutton configuration ----------------------------------
copybutton_exclude = ".linenos, .gp, .go"

# -- sphinx_reredirects configuration ----------------------------------
redirects = {
    "install": "hosting-a-bot/index.html",
    "installation": "hosting-a-bot/index.html",
    "usage": "using-a-bot/index.html",
    "using-a-bot": "using-a-bot/index.html",
    "hosting-a-bot": "hosting-a-bot/index.html",
    "cli": "reference/cli.html",
    "development": "development/index.html",
    "maintenance": "maintenance/index.html",
}

man_pages = [
    (
        "index",
        "matrix-jitsi-bot",
        "matrix-jitsi-bot Documentation",
        ["Nicco Kunzmann"],
        1,
    )
]

htmlhelp_basename = "matrix-jitsi-botdoc"
