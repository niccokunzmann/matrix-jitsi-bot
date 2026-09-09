======
Docker
======

matrix-jitsi-bot is published as a Docker image on the GitHub Container Registry.

.. code-block:: shell

    docker pull ghcr.io/niccokunzmann/matrix-jitsi-bot:latest

.. seealso::

    This always uses the pre-built image from the registry. See :doc:`../development/index` for building the image yourself from a local checkout instead.

Running
-------

Run it as a long-lived container, persisting its database in a named volume:

.. code-block:: shell

    docker run -d \
        --name matrix-jitsi-bot \
        --restart unless-stopped \
        -v matrix-jitsi-bot-data:/data \
        ghcr.io/niccokunzmann/matrix-jitsi-bot:latest

The container's entrypoint applies database migrations automatically on every start.

Running a one-off command
----------------------------

Any ``matrix-jitsi-bot`` command (see :doc:`../reference/cli`) can be run once, without starting the long-lived container, by passing it after the image name - the container's entrypoint runs it the same way it runs the bot itself:

.. code-block:: shell

    docker run --rm ghcr.io/niccokunzmann/matrix-jitsi-bot:latest --version

Getting a shell inside the container
----------------------------------------

To run several commands - e.g. creating the bot's account (see :doc:`index`) - open a shell inside the running container instead of repeating ``docker run`` for each one:

.. code-block:: shell

    docker exec -it matrix-jitsi-bot bash

The image includes bash completion for the ``matrix-jitsi-bot`` command, so pressing :kbd:`Tab` completes subcommands, options, and already-configured account user IDs.

From there, run any command straight from :doc:`../reference/cli`:

.. code-block:: shell

    matrix-jitsi-bot account create @bot:example.org
