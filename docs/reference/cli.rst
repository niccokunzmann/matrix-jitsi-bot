=============
CLI reference
=============

Full reference for the ``matrix-jitsi-bot`` command - every subcommand, argument, and option - generated from its own ``--help`` output. See :doc:`../hosting-a-bot/index` for a task-oriented walkthrough instead.

Checking it's installed
--------------------------

Every command below can be run the same way, whichever installation method you used - substitute the command shown after ``matrix-jitsi-bot`` here for any of the ones further down this page.

.. tab-set::

    .. tab-item:: pip / pipx

        .. code-block:: shell

            matrix-jitsi-bot --version

    .. tab-item:: Docker

        .. code-block:: shell

            docker run --rm ghcr.io/niccokunzmann/matrix-jitsi-bot:latest --version

    .. tab-item:: Docker Compose

        .. code-block:: shell

            docker compose run --rm bot --version

See :doc:`../hosting-a-bot/docker` or :doc:`../hosting-a-bot/docker-compose` for getting a shell inside the container instead of prefixing every command like this.

.. include:: _generated/cli.md
   :parser: myst_parser.sphinx_
