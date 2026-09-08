=============
Hosting a bot
=============

This chapter describes how to set up and run matrix-jitsi-bot as a service: creating the Matrix account it logs in as, managing its database, and running it long-term. See :doc:`installation` first if you haven't installed it yet, and :doc:`using-a-bot` for what the bot does once it's running.

The database
------------

matrix-jitsi-bot keeps all of its state - accounts, rooms, and conversation history - in a single SQLite database file. Its location is controlled by the ``MJB_DB`` environment variable, and defaults to :file:`matrix-jitsi-bot.sqlite3` in the current directory.

Before running the bot for the first time, apply its database migrations:

.. code-block:: shell

    matrix-jitsi-bot db migrate

Run this again after every upgrade that changes the database schema. If you ever change the bot's own models (only relevant if you're developing an interaction), regenerate migrations with ``matrix-jitsi-bot db makemigrations`` instead - see :doc:`development`.

Back up and restore the database at any time, e.g. before an upgrade:

.. code-block:: shell

    matrix-jitsi-bot db backup matrix-jitsi-bot.sqlite3.bak
    matrix-jitsi-bot db restore matrix-jitsi-bot.sqlite3.bak

Relative paths are resolved next to the configured database file.

Creating a Matrix account
--------------------------

The bot needs its own Matrix account to log in as. Create one on your homeserver first (or reuse an existing one), then register its credentials with the bot:

.. code-block:: shell

    matrix-jitsi-bot account create @bot:example.org

This prompts for a password, verifies it against the homeserver, and saves the resulting access token and device ID - the password itself is not required for subsequent logins. To skip the verification step (e.g. for scripting), pass ``--no-test``.

``--homeserver`` defaults to ``https://<server name>``, guessed from the user ID - ``https://example.org`` above. Pass it explicitly if your homeserver delegates its client-server API to a different host, e.g. via `.well-known/matrix/client <https://spec.matrix.org/latest/client-server-api/#well-known-uri>`_:

.. code-block:: shell

    matrix-jitsi-bot account create @bot:example.org --homeserver https://matrix.example.org

An account can also be registered directly from an access token, without a password:

.. code-block:: shell

    matrix-jitsi-bot account create @bot:example.org --access-token <token>

Managing accounts
------------------

.. code-block:: shell

    matrix-jitsi-bot account list
    matrix-jitsi-bot account show @bot:example.org
    matrix-jitsi-bot account check @bot:example.org
    matrix-jitsi-bot account remove @bot:example.org

``account check`` verifies the saved credentials can still log in, without changing anything - useful after a homeserver password reset or token revocation.

Individual attributes of an existing account can be updated with ``account set``:

.. code-block:: shell

    matrix-jitsi-bot account set password @bot:example.org
    matrix-jitsi-bot account set access-token @bot:example.org
    matrix-jitsi-bot account set homeserver @bot:example.org https://example.org
    matrix-jitsi-bot account set device-id @bot:example.org DEVICEID

Running the bot
----------------

.. code-block:: shell

    matrix-jitsi-bot run

Logs in and runs the bot's main loop until interrupted (:kbd:`Ctrl-C`). If only one account is configured, it's used automatically; otherwise pass the Matrix user ID to run as:

.. code-block:: shell

    matrix-jitsi-bot run @bot:example.org

Running with Docker
--------------------

The provided :file:`docker-compose.yml` builds the image, persists the database in a named volume, and restarts the bot automatically:

.. code-block:: yaml

    services:
      bot:
        build: .
        restart: unless-stopped
        volumes:
          - bot-data:/data
        environment:
          MJB_DB: /data/matrix-jitsi-bot.sqlite3

    volumes:
      bot-data:

Bring it up with:

.. code-block:: shell

    docker compose up -d

The container's entrypoint applies database migrations automatically on every start, so there's no separate migration step to run. Use ``docker compose run --rm bot account create ...`` (and the other ``account``/``db`` commands above) to manage the same database the running container uses:

.. code-block:: shell

    docker compose run --rm bot account create @bot:example.org --homeserver https://example.org

.. note::

    matrix-jitsi-bot's database uses SQLite's WAL journal mode, which lets the running bot and a ``docker compose run`` command read and write the same database file concurrently. There's no need to stop the bot to manage accounts.
