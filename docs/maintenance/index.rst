===========
Maintenance
===========

This chapter describes how matrix-jitsi-bot is maintained: versioning, releases, and dependency upkeep.

Versioning
----------

The package version is derived from git tags via `hatch-vcs <https://github.com/ofek/hatch-vcs>`_ - there's no version number to bump by hand anywhere in the source. Between tags, the version includes the commit distance and hash (e.g. ``0.1.dev2``); an exact tag like ``v0.2.0`` produces exactly that version.

Continuous integration
------------------------

Every push and pull request runs the test suite (on Python 3.12, 3.13, and 3.14) and ``ruff check`` - see :file:`.github/workflows/tests.yml`. Both must pass before a pull request is merged.

On every push to ``main``, once tests pass, the Docker image is rebuilt and published to the GitHub Container Registry as ``ghcr.io/niccokunzmann/matrix-jitsi-bot:latest`` and ``ghcr.io/niccokunzmann/matrix-jitsi-bot:<commit-sha>``. There is currently no separate tagged-release process - ``main`` is always the deployable version - and no automated PyPI publish.

Cutting a release
------------------

To mark a released version:

.. code-block:: shell

    git tag v0.2.0
    git push --tags

This only affects the version string reported by ``matrix-jitsi-bot --version`` and embedded in built packages (see Versioning above); it doesn't itself trigger a build or publish.

Dependencies
------------

Dependencies are pinned in :file:`uv.lock`. To update them:

.. code-block:: shell

    uv lock --upgrade
    make test

Review the diff to :file:`uv.lock`, and check that nothing broke before committing it.

The pinned ``ruff`` version in :file:`pyproject.toml`'s ``formatting`` dependency group must be kept in sync with the one in :file:`.pre-commit-config.yaml` - update both together.

Maintainer
----------

matrix-jitsi-bot is maintained by Nicco Kunzmann. See the `repository <https://github.com/niccokunzmann/matrix-jitsi-bot>`_ for issues and pull requests.
