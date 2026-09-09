==============
Python package
==============

Install matrix-jitsi-bot as a Python package. Requires Python 3.12 or newer.

.. tab-set::

    .. tab-item:: pipx

        Since matrix-jitsi-bot is primarily a command line tool, `pipx <https://pipx.pypa.io/>`_ is the recommended way - it installs ``matrix-jitsi-bot`` into its own isolated environment and puts it on your ``PATH``, without affecting any other Python project:

        .. code-block:: shell

            pipx install matrix-jitsi-bot

    .. tab-item:: pip

        Plain ``pip`` works too, e.g. into a virtual environment - useful if you're using matrix-jitsi-bot as a library (see :doc:`../reference/index`) rather than just its CLI:

        .. code-block:: shell

            pip install matrix-jitsi-bot

Either way, confirm it is on your ``PATH``:

.. code-block:: shell

    matrix-jitsi-bot --version

Running
-------

Unlike the Docker image, nothing applies database migrations for you - do that once before first use, and again after every upgrade that changes the database schema:

.. code-block:: shell

    matrix-jitsi-bot db migrate

Then create the bot's account (see :doc:`index`) and start it:

.. code-block:: shell

    matrix-jitsi-bot account create @bot:example.org
    matrix-jitsi-bot run

``run`` logs in and runs the bot's main loop until interrupted (:kbd:`Ctrl-C`) - wrap it in a process supervisor (systemd, supervisord, ...) to keep it running as a service. See :doc:`../reference/cli` for every command.
