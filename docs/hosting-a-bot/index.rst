============
Self hosting
============

This chapter describes how to install and run matrix-jitsi-bot as a service. Pick whichever installation method matches your setup - each covers installing, running, and creating the bot's Matrix account:

.. toctree::
    :maxdepth: 1

    docker
    docker-compose
    python-package
    from-source

See :doc:`../using-a-bot/index` for what the bot does once it's running, and :doc:`../reference/cli` for the full reference of every ``matrix-jitsi-bot`` command and option.

The database
------------

matrix-jitsi-bot keeps all of its state - accounts, rooms, and conversation history - in a single SQLite database file. Its location is controlled by the ``MJB_DB`` environment variable, and defaults to :file:`matrix-jitsi-bot.sqlite3` in the current directory.

Its database uses SQLite's WAL journal mode, which lets the running bot and a CLI command (``account``, ``db``, ...) read and write the same database file concurrently - there's no need to stop the bot to manage accounts.

Back up and restore the database at any time, e.g. before an upgrade:

.. code-block:: shell

    matrix-jitsi-bot db backup matrix-jitsi-bot.sqlite3.bak
    matrix-jitsi-bot db restore matrix-jitsi-bot.sqlite3.bak

Relative paths are resolved next to the configured database file. See :doc:`../reference/cli` for every ``db`` subcommand.

Creating a Matrix account
--------------------------

The bot needs its own Matrix account to log in as. Create one on your homeserver first (or reuse an existing one), then register its credentials with the bot - each installation method's page shows the exact command for that setup:

.. code-block:: shell

    matrix-jitsi-bot account create @bot:example.org

This prompts for a password, verifies it against the homeserver, and saves the resulting access token and device ID - the password itself is not required for subsequent logins. To skip the verification step (e.g. for scripting), pass ``--no-test``.

``--homeserver`` defaults to ``https://<server name>``, guessed from the user ID - ``https://example.org`` above. Pass it explicitly if your homeserver delegates its client-server API to a different host, e.g. via `.well-known/matrix/client <https://spec.matrix.org/latest/client-server-api/#well-known-uri>`_:

.. code-block:: shell

    matrix-jitsi-bot account create @bot:example.org --homeserver https://matrix.example.org

An account can also be registered directly from an access token, without a password:

.. code-block:: shell

    matrix-jitsi-bot account create @bot:example.org --access-token <token>

See :doc:`../reference/cli` for every ``account`` subcommand, including listing, checking, removing, and updating accounts.
