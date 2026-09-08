# matrix-jitsi-bot documentation build configuration file
import datetime
import os
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

import matrix_jitsi_bot  # noqa: E402

extensions = [
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
source_suffix = {".rst": "restructuredtext"}
master_doc = "index"

project = "matrix-jitsi-bot"
this_year = datetime.date.today().year  # noqa: DTZ011
copyright = f"{this_year}, Nicco Kunzmann"  # noqa: A001
release = matrix_jitsi_bot.__version__
version = release

# -- Options for HTML output -------------------------------------------------

templates_path = []
exclude_patterns = [
    "reference/api/modules.rst",
]
html_theme = "pydata_sphinx_theme"
html_theme_options = {
    "icon_links": [
        {
            "name": "GitHub",
            "url": "https://github.com/pycalendar/matrix-jitsi-bot",
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
    "github_user": "pycalendar",
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
        },
    }
]
autoclass_content = "both"

# -- sphinx.ext.autodoc options -------------------------------------------------
autodoc_default_options = {
    "members": True,
    "show-inheritance": True,
    "undoc-members": True,
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
    "install": "installation.html",
    "usage": "using-a-bot.html",
    "cli": "hosting-a-bot.html",
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
