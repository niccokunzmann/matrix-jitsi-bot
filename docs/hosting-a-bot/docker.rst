======
Docker
======

matrix-jitsi-bot is published as a Docker image on the `GitHub Container Registry <https://github.com/niccokunzmann/matrix-jitsi-bot/pkgs/container/matrix-jitsi-bot>`_.

.. code-block:: shell

    docker pull ghcr.io/niccokunzmann/matrix-jitsi-bot:latest

.. seealso::

    This always uses the pre-built image from the registry. See :doc:`../development/index` for building the image yourself from a local checkout instead.

Image tags
----------

- ``latest`` - the tip of the ``main`` branch, rebuilt on every push to it. Whatever's newest, including unreleased changes.
- ``<commit-sha>`` - the exact commit a ``main`` build came from, e.g. ``ghcr.io/niccokunzmann/matrix-jitsi-bot:a1b2c3d``. Pin to one of these for a reproducible build from ``main`` older than the current ``latest``.
- ``stable`` - the most recently tagged release, e.g. ``v0.2.0`` - the same image as ``0.2.0`` below, just always pointing at whichever release is newest. Use this if you want releases only, not everything that lands on ``main``.
- ``X.Y.Z``, ``X.Y``, and ``X`` - a specific tagged release and its rolling major/minor aliases, e.g. release ``v0.2.0`` publishes ``0.2.0``, ``0.2`` (latest patch of the ``0.2`` line), and ``0`` (latest release of the ``0`` line). Pin to ``X.Y.Z`` for a release that never moves; ``X.Y`` or ``X`` for one that picks up compatible fixes.

See :doc:`../maintenance/index` for how these are cut.

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
