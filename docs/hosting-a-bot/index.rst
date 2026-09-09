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

Environment variables
----------------------

.. list-table::
    :header-rows: 1

    *   -   Variable
        -   Default
        -   Meaning
    *   -   ``MJB_DB``
        -   :file:`matrix-jitsi-bot.sqlite3` in the current directory
        -   Path to the SQLite database holding all of the bot's state - accounts, rooms, and conversation history. See `The database`_.
    *   -   ``MJB_CRYPTO_STORE``
        -   A ``matrix-jitsi-bot.crypto-store`` directory next to ``MJB_DB``
        -   Directory holding the end-to-end encryption store (Olm/Megolm sessions and keys, managed by ``nio``, not the SQLite database). See `End-to-end encryption`_.
    *   -   ``MJB_POLL_INTERVAL``
        -   ``1`` (seconds)
        -   How often ``matrix-jitsi-bot run`` checks whether any tracked Jitsi conference is due a check - see :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.run`. Ignored by ``run --once``.
    *   -   ``MJB_MAX_HISTORY``
        -   ``100`` (messages)
        -   How many recent messages of a room's conversation history are kept at most, per room - see ``settings.MAX_CONVERSATION_MESSAGES``.

The database
------------

matrix-jitsi-bot keeps all of its state - accounts, rooms, and conversation history - in a single SQLite database file. Its location is controlled by the ``MJB_DB`` environment variable, and defaults to :file:`matrix-jitsi-bot.sqlite3` in the current directory.

Its database uses SQLite's WAL journal mode, which lets the running bot and a CLI command (``account``, ``db``, ...) read and write the same database file concurrently - there's no need to stop the bot to manage accounts.

Back up and restore the database at any time, e.g. before an upgrade:

.. code-block:: shell

    matrix-jitsi-bot db backup matrix-jitsi-bot.sqlite3.bak
    matrix-jitsi-bot db restore matrix-jitsi-bot.sqlite3.bak

Relative paths are resolved next to the configured database file. See :doc:`../reference/cli` for every ``db`` subcommand.

End-to-end encryption
----------------------

The bot supports encrypted rooms out of the box - no setup needed. Its Olm/Megolm session store (managed by ``nio``, separately from the SQLite database above) lives next to it by default, so it's covered by the same backups and the same persistent volume in a container setup. Override its location with the ``MJB_CRYPTO_STORE`` environment variable if needed.

Losing this store (e.g. restoring only the SQLite database from a backup, but not it) doesn't stop the bot working, but it can no longer decrypt messages sent before the loss, and re-establishes fresh encryption sessions with everyone from scratch.

Other users may see the bot's messages marked as sent by an "Encrypted device not verified by its owner". This is normal, and not something the bot can fix on its own - it means the account has no `cross-signing <https://spec.matrix.org/latest/client-server-api/#cross-signing>`_ identity set up at all yet, which has to be done once from an ordinary Matrix client logged in as the bot's account (e.g. Element's Settings > Security & Privacy > "Set up encryption") - the ``nio``/``niobot`` libraries the bot is built on don't support cross-signing themselves. ``matrix-jitsi-bot account check`` warns if this hasn't been done.

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
