=========
Changelog
=========

All notable changes to ``matrix-jitsi-bot`` are documented here, following the `Keep a Changelog <https://keepachangelog.com/>`_ conventions.

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

