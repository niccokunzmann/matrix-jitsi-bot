============
Installation
============

This chapter describes how to install matrix-jitsi-bot. Pick whichever of the following matches how you plan to run it.

Docker
------

The bot is published as a Docker image on the GitHub Container Registry. This is the recommended way to run it as a service - see :doc:`hosting-a-bot` for how to configure and run the container.

.. code-block:: shell

    docker pull ghcr.io/pycalendar/matrix-jitsi-bot:latest

A :file:`docker-compose.yml` is also provided in the repository, which builds the image locally and persists the database in a named volume:

.. code-block:: shell

    git clone https://github.com/pycalendar/matrix-jitsi-bot
    cd matrix-jitsi-bot
    docker compose up -d

Python package
--------------

Alternatively, install matrix-jitsi-bot as a Python package.

.. tab-set::

    .. tab-item:: pipx

        Since matrix-jitsi-bot is primarily a command line tool, `pipx <https://pipx.pypa.io/>`_ is the recommended way - it installs ``matrix-jitsi-bot`` into its own isolated environment and puts it on your ``PATH``, without affecting any other Python project:

        .. code-block:: shell

            pipx install matrix-jitsi-bot

    .. tab-item:: pip

        Plain ``pip`` works too, e.g. into a virtual environment - useful if you're using matrix-jitsi-bot as a library (see :doc:`reference/index`) rather than just its CLI:

        .. code-block:: shell

            pip install matrix-jitsi-bot

Either way, confirm it is on your ``PATH``:

.. code-block:: shell

    matrix-jitsi-bot --version

Requires Python 3.12 or newer.

From source
-----------

To install the latest development version from source, using `uv <https://docs.astral.sh/uv/>`_:

.. code-block:: shell

    git clone https://github.com/pycalendar/matrix-jitsi-bot
    cd matrix-jitsi-bot
    uv sync

See :doc:`development` for setting up a full development environment, including tests and documentation.
