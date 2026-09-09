===========
Development
===========

This chapter describes how to set up a local development environment for matrix-jitsi-bot and the ``make`` targets available while working on it.

Setup
-----

matrix-jitsi-bot uses `uv <https://docs.astral.sh/uv/>`_ to manage its Python environment, and a :file:`Makefile` to wrap the common commands.

.. code-block:: shell

    git clone https://github.com/niccokunzmann/matrix-jitsi-bot
    cd matrix-jitsi-bot
    make init

``make init`` installs the required Python version, creates a virtual environment in :file:`.venv/`, installs matrix-jitsi-bot together with its ``dev`` dependency group (tests, formatting, and docs), and installs the project's `pre-commit <https://pre-commit.com/>`_ hooks - so linting runs automatically on every commit.

Makefile targets
-----------------

.. list-table::
    :header-rows: 1

    *   -   Target
        -   Description
    *   -   ``make init``
        -   Clean the docs build directory and virtual environment, then set up a fresh one.
    *   -   ``make dev``
        -   Set up the virtual environment (alias for the default dependency, same as ``make init`` without the cleaning).
    *   -   ``make format``
        -   Format the code base with ``ruff``.
    *   -   ``make test``
        -   Run the test suite with ``pytest``.
    *   -   ``make dist``
        -   Build the sdist and wheel into :file:`dist/`.
    *   -   ``make install``
        -   Install this checkout as the ``matrix-jitsi-bot`` command, editable, with bash completion.
    *   -   ``make clean``
        -   Clean the docs build directory.
    *   -   ``make clean-all``
        -   Clean the docs build directory and the virtual environment.
    *   -   ``make html``
        -   Build the documentation as HTML into :file:`docs/_build/html/`.
    *   -   ``make livehtml``
        -   Rebuild the documentation on changes, with live-reload in the browser.
    *   -   ``make linkcheck``
        -   Check the documentation for broken links.

Trying the CLI on your machine
---------------------------------

``uv run matrix-jitsi-bot ...`` (or ``uv run --`` in front of any command) always runs against this checkout, but only from inside the repository. To get a ``matrix-jitsi-bot`` command anywhere on your system that stays in sync with your local changes - without publishing anything - install it editable with `uv tool install <https://docs.astral.sh/uv/concepts/tools/>`_:

.. code-block:: shell

    make install

This is the development equivalent of the ``pipx install matrix-jitsi-bot`` from :doc:`../hosting-a-bot/python-package`, pointed at this checkout instead of a release: it installs matrix-jitsi-bot into its own isolated environment, on your ``PATH``, but editable - so code changes you make take effect the next time you run the command, no reinstall needed. Re-run ``make install`` only when dependencies change (e.g. after editing :file:`pyproject.toml`).

It also installs bash completion for the ``matrix-jitsi-bot`` command (restart your terminal, or ``source`` the printed path, for it to take effect).

Running the tests
------------------

.. code-block:: shell

    make test

Equivalent to ``uv run pytest``. The test suite exercises the database models and the bot's ``@MessageReaction`` interactions (see :doc:`../reference/index`) against a real, temporary SQLite database - Django's test runner takes care of creating and migrating it.

To check for lint issues without fixing them (e.g. what CI runs):

.. code-block:: shell

    uv run ruff check .

Building the documentation
----------------------------

This documentation is built with `Sphinx <https://www.sphinx-doc.org/>`_. To build it once as static HTML:

.. code-block:: shell

    make html

The output is written to :file:`docs/_build/html/index.html`.

While editing the documentation, run a live-reloading local server instead - it rebuilds and refreshes your browser automatically as you save changes to any ``.rst`` file or docstring:

.. code-block:: shell

    make livehtml

This serves the documentation at http://127.0.0.1:8000 by default.

To check for broken links across the documentation:

.. code-block:: shell

    make linkcheck

The API reference under :doc:`../reference/index` is generated automatically from docstrings in the source code via ``sphinx.ext.apidoc``, and the CLI reference from the ``matrix-jitsi-bot`` command's own ``--help`` output via ``typer utils docs`` - there's nothing to keep in sync by hand in either case; just document new modules, classes, functions, and CLI options as you write them.

Building the Docker image
----------------------------

The published image (see :doc:`../hosting-a-bot/docker` and :doc:`../hosting-a-bot/docker-compose`) is built by CI on every push to ``main`` and pushed to the GitHub Container Registry - see :doc:`../maintenance/index`. To build it yourself instead, e.g. to test a local change:

.. code-block:: shell

    docker build -t matrix-jitsi-bot .

The repository's own :file:`docker-compose.yml` does the same thing via ``build: .``, which is what ``docker compose up -d --build`` uses from a checkout - unlike :doc:`../hosting-a-bot/docker-compose`'s example, which points ``image:`` at the published registry image instead.

Adding a new bot interaction
-------------------------------

Chat-room commands live in :mod:`matrix_jitsi_bot.interactions`, one module per topic (e.g. :mod:`matrix_jitsi_bot.interactions.greeting`, :mod:`matrix_jitsi_bot.interactions.room`). To add a new one:

1.  Create a new module in :file:`matrix_jitsi_bot/interactions/`, with a class subclassing :class:`~matrix_jitsi_bot.interactions.base.BotInteraction`.
2.  Decorate the methods that should react to a message with :class:`~matrix_jitsi_bot.interactions.base.Mention` (or :class:`~matrix_jitsi_bot.interactions.base.Config` for a moderator-only command), giving it a unique-enough ``id`` (an integer - lower ids are tried first) and a regular expression to match against the message, after its leading mention of the bot is stripped. Named groups in the pattern are passed to the method as keyword arguments. Pass ``description`` and ``examples`` too, so the fallback help message can describe the command.
3.  Export the new class from :mod:`matrix_jitsi_bot.interactions`, and add it to :class:`~matrix_jitsi_bot.interactions.all.AllInteractions`.
4.  Add tests alongside the existing ones in :file:`matrix_jitsi_bot/tests/`.

See :doc:`../using-a-bot/index` for the commands this produces from a room member's perspective, and the :mod:`matrix_jitsi_bot.interactions.base` module documentation in :doc:`../reference/index` for how ``@Mention``/``@Config`` and ``BotInteraction`` fit together.

Contributing
------------

Pull requests are welcome on `GitHub <https://github.com/niccokunzmann/matrix-jitsi-bot>`_. Please make sure ``make test`` and ``uv run ruff check .`` pass before opening one - the same checks run in CI.
