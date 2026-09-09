==============
Docker Compose
==============

Docker Compose manages the container, its restart policy, and its data volume together from one file. Create a :file:`docker-compose.yml`:

.. code-block:: yaml

    services:
      matrix-jitsi-bot:
        image: ghcr.io/niccokunzmann/matrix-jitsi-bot:latest
        restart: unless-stopped
        volumes:
          - matrix-jitsi-bot-data:/data

    volumes:
      matrix-jitsi-bot-data:

.. seealso::

    This always uses the pre-built image from the registry. See :doc:`../development/index` for building the image yourself from a local checkout instead - the repository's own :file:`docker-compose.yml` does exactly that.

Running
-------

.. code-block:: shell

    docker compose up -d

The container's entrypoint applies database migrations automatically on every start.

Running a one-off command
----------------------------

Any ``matrix-jitsi-bot`` command (see :doc:`../reference/cli`) can be run once, in its own short-lived container, via ``docker compose run``:

.. code-block:: shell

    docker compose run --rm matrix-jitsi-bot --version

Getting a shell inside the container
----------------------------------------

To run several commands - e.g. creating the bot's account (see :doc:`index`) - open a shell inside the already-running ``matrix-jitsi-bot`` service instead of repeating ``docker compose run`` for each one:

.. code-block:: shell

    docker compose exec matrix-jitsi-bot bash

The image includes bash completion for the ``matrix-jitsi-bot`` command, so pressing :kbd:`Tab` completes subcommands, options, and already-configured account user IDs.

From there, run any command straight from :doc:`../reference/cli`:

.. code-block:: shell

    matrix-jitsi-bot account create @bot:example.org
