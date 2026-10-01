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
        -   How often ``matrix-jitsi-bot run`` checks whether any tracked Jitsi conference is due a check - see :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.run`. While a conference is being monitored (see `Staying in Jitsi conferences`_), it isn't checked at all. Ignored by ``run --once``.
    *   -   ``MJB_MAX_HISTORY``
        -   ``100`` (messages)
        -   How many recent messages of a room's conversation history are kept at most, per room - see ``settings.MAX_CONVERSATION_MESSAGES``.

.. _staying-in-conferences:

Staying in Jitsi conferences
----------------------------

While a tracked conference is closed, ``matrix-jitsi-bot run`` only checks at intervals whether it exists, without joining it. Once it is open and some room tracks who joins or leaves it, the bot instead **stays in the conference**, using ``inspect-jitsi``'s monitoring mode (:py:func:`~matrix_jitsi_bot.jitsi.monitor_jitsi_room`), and reports joins and leaves the moment they happen. It leaves again when the conference closes - which includes everyone else having left, since the bot's own presence would otherwise keep it open - or when nobody tracks who joins or leaves it anymore (untracked, or the room paused), and it reconnects by itself if the connection drops. The bot's Matrix display name is shown to the conference's participants while it's in there. ``run --once`` and ``check`` never stay - they only join briefly.

While it is in a conference, a :py:class:`~matrix_jitsi_bot.db.models.process.JitsiMonitor` row records that in the database, and deletes it again when the bot leaves. ``matrix-jitsi-bot status`` lists these as *Monitored conferences*.

.. _name-and-avatar-in-a-conference:

Name and avatar in a conference
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Whenever the bot joins a conference - to read who is in it, or to stay in it - the others see it as a participant. It shows the display name and the avatar of the Matrix account it runs as. The avatar is the account's Matrix profile avatar, shrunk to at most 128 pixels, and the logo if the account has none. It is read from the profile when the bot starts and whenever it changes, and stored in the database (:py:meth:`~matrix_jitsi_bot.db.models.account.Account.jitsi_avatar_of`). ``matrix-jitsi-bot account set avatar`` changes both the profile avatar and this one.

Running processes
~~~~~~~~~~~~~~~~~

Only one bot can work on a database: two would both check every conference and announce every change twice. This is guaranteed by an operating system lock (:py:class:`~matrix_jitsi_bot.db.models.process.RunLock`) on a lock file next to the database (:file:`matrix-jitsi-bot.sqlite3.lock`), which ``run`` and ``run --once`` hold while they work. Whoever starts second refuses with "The bot is already running for this database". Taking the lock is atomic - two starting at the same moment cannot both get it - and the kernel releases it however the process ends: a crash, ``kill -9``, the container being removed, the machine losing power. So an interrupted bot never blocks the next one, and there is nothing to clean up by hand. Keep the lock file next to the database, in the same volume, when using Docker. A second lock, per Matrix account, in the temporary directory (:file:`matrix-jitsi-bot-<hash>.lock`) also stops two databases on the same machine from running as the same account. It doesn't reach across machines or containers that don't share that directory - never run one account from two hosts. The file system must support ``flock``: if it doesn't (some network file systems), the bot refuses to start and says so, instead of running unprotected.

A running bot also records itself in the database as a :py:class:`~matrix_jitsi_bot.db.models.process.BotProcess` (its process ID and a random secret), and starting ``run`` clears out what an interrupted one left behind - including the monitored conferences. ``matrix-jitsi-bot status`` asks the lock whether a bot really runs, and shows how many processes that is, so it never reports a dead one.

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
