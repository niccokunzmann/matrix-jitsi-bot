=========
Changelog
=========

All notable changes to ``matrix-jitsi-bot`` are documented here, following the `Keep a Changelog <https://keepachangelog.com/>`_ conventions.

Unreleased
==========

Added
-----

- ``change avatar when <conference> is active`` (moderators only, and only if the bot may change the room's avatar): while the conference is open, the room's avatar gets a speaker overlay (merged in by :py:class:`~matrix_jitsi_bot.icon.merge.SpeakerTopRight`). The original avatar is downloaded and cached in the database (new fields on :py:class:`~matrix_jitsi_bot.db.models.room.Room`), and restored and removed from the database when the conference closes. ``don't change avatar when <conference> is active`` undoes it. Run ``matrix-jitsi-bot db migrate`` to update.
- Two new database tables, :py:class:`~matrix_jitsi_bot.db.models.process.BotProcess` (the running bot process, with its process ID and a random secret) and :py:class:`~matrix_jitsi_bot.db.models.process.JitsiMonitor` (a conference the bot is in right now, deleted when it leaves). ``matrix-jitsi-bot status`` now shows how many processes run and which conferences are monitored. Only one ``run`` process is allowed per database, guaranteed by a lock on a file next to the database that the operating system releases however the process ends, so an interrupted bot never blocks the next one, and a second lock per Matrix account stops two databases on one machine from running as the same account. ``run`` refuses to start where the file system can't lock files. ``run`` clears out what it left behind, and ``run --once`` refuses to run while ``run`` does, and the other way around - see :doc:`../hosting-a-bot/index`. Run ``matrix-jitsi-bot db migrate`` to update.

Changed
-------

- A command that fails because the database is out of date (``OperationalError: no such column: ...``, after updating the bot without migrating) now prints that error and suggests ``matrix-jitsi-bot db migrate`` instead of a traceback.
- While a conference is open and a room tracks who joins or leaves it, the bot now stays in it, using ``inspect-jitsi``'s monitoring mode (:py:func:`~matrix_jitsi_bot.jitsi.monitor_jitsi_room`), instead of joining briefly every second to poll the participant list. Joins and leaves are reported as they happen (a manual ``check`` of a conference the bot is in answers from the database, without joining it a second time), and the bot leaves again once the conference closes (including when it's the only one left in it) or nobody tracks joins and leaves of it anymore - see :doc:`../hosting-a-bot/index`. Closed conferences, and conferences only tracked for open/close/starts, are checked at intervals as before, without joining.
- Updated the pinned dependencies in :file:`uv.lock` (``uv lock --upgrade``), notably ``inspect-jitsi`` 0.1.0 to 0.2.0, ``filelock`` 3.32.7 to 4.0.6, ``starlette`` 1.6.0 to 1.7.0, ``uvicorn`` 0.53.0 to 0.54.0, ``tox`` 4.61.5 to 4.64.4 and ``pydata-sphinx-theme`` 0.21.0 to 0.22.0.
- Documented how to update dependencies in :doc:`../development/index`.

0.1.0 - 2026-09-17
==================

Added
-----

- The bot's own Matrix account display name (:py:attr:`~matrix_jitsi_bot.db.models.account.Account.display_name`, set via ``matrix-jitsi-bot account set display-name``) is now disclosed as its own display name while briefly joining a Jitsi conference to read its participants (:py:func:`~matrix_jitsi_bot.jitsi.check_jitsi_room`) - it previously joined anonymously. Refreshed from the account's actual Matrix profile at startup, and kept live for the rest of the run whenever that profile's display name changes.
- Pushing a ``v*`` git tag now also creates a GitHub release for it, with the built sdist and wheel attached, alongside the existing PyPI and Docker publishing - see :doc:`../maintenance/index`.

0.0.1 - 2024-09-15
==================

Initial release of ``matrix-jitsi-bot``.

Fixed
-----

- A conference's "ended" message could be reported twice for what looked like a single continuous session. This happened when the conference briefly reopened (e.g. someone rejoined for a moment) between two checks, and that reopening's participant snapshot came back empty - such a reopening was never itself announced, so the close that followed it looked like a duplicate of the previous one. :py:meth:`~matrix_jitsi_bot.jitsi.JitsiChange.messages_for` now always announces ``Conference <url> started`` for a tracker with ``track_starts`` set, even when that particular check's participant snapshot came back empty - so every "ended" is now paired with a visible "started".

Added
-----

- Each Matrix room's display name is now tracked (:py:attr:`~matrix_jitsi_bot.db.models.room.Room.name`), kept in sync as it's invited into, as it renames, and as membership changes recompute it, and shown alongside the room ID wherever a room is reported (:py:meth:`~matrix_jitsi_bot.db.models.room.Room.label`) - e.g. ``"pycal"(!kbdVNZeuYWqpMIiXAg:chat.pycal.org)``, with any control characters (including newlines) in the name escaped.
- ``matrix-jitsi-bot status`` now shows each room by that label instead of its bare room ID, and lists what each tracked conference is configured to report there (``open``, ``close``, ``starts``, ``joins``, ``leaves``).
- Pushing a ``v*`` git tag now builds and publishes the package to PyPI automatically, via `trusted publishing <https://docs.pypi.org/trusted-publishers/>`_ (no stored API token), and pushes a Docker image tagged ``X.Y.Z``, ``X.Y``, ``X``, and ``stable`` - see :doc:`../maintenance/index` and :doc:`../hosting-a-bot/docker`.

