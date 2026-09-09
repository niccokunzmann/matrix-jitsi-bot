===========
From source
===========

Installing from a git checkout is mainly useful for developing matrix-jitsi-bot itself - to just run a release, prefer :doc:`docker`, :doc:`docker-compose`, or :doc:`python-package`.

.. code-block:: shell

    git clone https://github.com/niccokunzmann/matrix-jitsi-bot
    cd matrix-jitsi-bot
    make install

This installs matrix-jitsi-bot as the ``matrix-jitsi-bot`` command, editable - code changes in this checkout take effect immediately, no reinstall needed. See :doc:`../development/index` for the full development workflow, including tests and building the documentation.

From here on, every command runs exactly as described in :doc:`index` and :doc:`../reference/cli`:

.. code-block:: shell

    matrix-jitsi-bot db migrate
    matrix-jitsi-bot account create @bot:example.org
    matrix-jitsi-bot run
