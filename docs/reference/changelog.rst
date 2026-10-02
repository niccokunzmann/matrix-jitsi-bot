=========
Changelog
=========

All notable changes to ``matrix-jitsi-bot`` are documented here, following the `Keep a Changelog <https://keepachangelog.com/>`_ conventions.

An entry starts with a tag where one applies: **CLI** for the ``matrix-jitsi-bot`` command, **API** for the Python package. Entries without a tag are about what the bot does in a chat, its deployment, or its documentation.

Unreleased
==========

Added
-----

- **API**: :py:func:`~matrix_jitsi_bot.version.is_development` tells a development version (``0.2.1.dev3``) from a release (``0.2.0``), and :py:func:`~matrix_jitsi_bot.version.documentation_url` gives the address of a page of the documentation of this version.
- **API**: :py:attr:`~matrix_jitsi_bot.interactions.base.BotInteraction.ambiguous_names` holds the short names of the bot that somebody else in the chat has too, which therefore are not in :py:attr:`~matrix_jitsi_bot.interactions.base.BotInteraction.bot_names`.
- **API**: The conference status message: :py:class:`~matrix_jitsi_bot.db.models.status_message.StatusMessage` (a chat has one at most) and :py:func:`~matrix_jitsi_bot.db.models.status_message.conference_status_text`; :py:class:`~matrix_jitsi_bot.interactions.status_message.StatusMessageInteraction` is part of :py:class:`~matrix_jitsi_bot.interactions.all.AllInteractions` as ``status_message``; :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.update_status_messages` edits the messages that are out of date, after every poll. :py:class:`~matrix_jitsi_bot.db.models.conversation.CommandReply` has ``reply_to_event_id`` for a reply to a message the bot sent itself. Run ``matrix-jitsi-bot db migrate`` to update.
- ``create conference status message`` (moderators only) posts a message that links the conferences tracked in the chat - to start them while none is running, and only the running ones, to join, while some are, marked with a 🔊 at the start - and answers it with a note that it is edited and may be pinned. The bot edits it within seconds of a conference opening or closing, or being tracked or untracked, but not while the chat is paused. A chat has one such message: a new one deletes the old, and the bot says so. When the last conference is untracked, the message links how to set one up. Deleting the message, or ``don't track any``, stops it. ``status`` says if the chat has one.
- The bot also answers a message that starts with ``@`` and its name, e.g. ``@jitsi-bot hello`` or ``@jitsi-bot: hello`` - the way the documentation writes its commands - not only a mention picked from the client's list, the full user ID or the bare name. A short name only counts if nobody else in the chat - joined or invited, on any server - has it as their name or user name: otherwise the bot does not run the command but asks to be mentioned by its full user ID, so two bots with the same name never both act on one message.
- The ``help`` reply links the page of the documentation that explains every command: ``latest`` for a development version of the bot, ``stable`` for a release.
- ``status`` also lists the avatars that change for each conference - the avatar of the chat and of its spaces - and says where the speaker is shown right now.
- The documentation has a page :doc:`commands` with a section for every command, each one linkable, with the same parts: the command, an *Explanation* that tells an example conversation step by step, *Other ways to say it*, and *Undo this configuration* with what is specific to the command and links to what applies to every command. A field at the top of the page puts the reader's own conference URL into every command and message on it. The example avatars on it are drawn by :file:`docs/generate_avatar_examples.py` (``make avatar-examples``) with the code the bot uses. A test fails when a command of the bot is not documented there.
- The documentation shows the logo next to its name.

Changed
-------

- **API**: :py:class:`~matrix_jitsi_bot.icon.merge.RoomSpeaker` places the speaker at ``center-left`` instead of ``center-right``.
- The speaker on the avatar of a chat is at the left, in the middle of the height, instead of at the right. The speaker on a space avatar stays at the bottom right.
- ``don't track any`` is described as what it is: it resets the chat's configuration, avatar changes and the conference status message included.

0.2.0 - 2026-10-01
==================

Added
-----

- **API**: The avatar the bot shows when it joins a Jitsi conference: :py:meth:`~matrix_jitsi_bot.db.models.account.Account.jitsi_avatar_of` is the Matrix profile avatar of the account (stored shrunk as ``avatar_data_uri``, with its content URI ``avatar_mxc``, by :py:meth:`~matrix_jitsi_bot.db.models.account.Account.update_avatar`) or else the logo; :py:func:`~matrix_jitsi_bot.jitsi.check_jitsi_room` and :py:func:`~matrix_jitsi_bot.jitsi.monitor_jitsi_room` take ``avatar_url``; :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.sync_own_avatar` follows the profile; :py:func:`~matrix_jitsi_bot.image.shrink_avatar`, :py:func:`~matrix_jitsi_bot.image.avatar_data_uri` and :py:func:`~matrix_jitsi_bot.image.logo_avatar_url` prepare it. :py:func:`~matrix_jitsi_bot.matrix_login.set_avatar` returns the content URI of the uploaded image. Run ``matrix-jitsi-bot db migrate`` to update.
- **API**: The logo (:file:`matrix_jitsi_bot/icon/logo.svg` and :file:`logo.png`, see :py:data:`~matrix_jitsi_bot.icon.LOGO_SVG`) is a file of the package, so it is installed with it and part of the Docker image; the documentation uses it as its favicon. The Docker image now includes the ``cairo`` library, without which SVG icons and the logo cannot be drawn into an avatar.
- **API**: New modules :py:mod:`matrix_jitsi_bot.icon.merge` (drawing an icon into an image: :py:class:`~matrix_jitsi_bot.icon.merge.IconMerge` and its subclasses), :py:mod:`matrix_jitsi_bot.space` (looking at a space: joining it, what it lists and who may change its avatar), :py:mod:`matrix_jitsi_bot.image` (downloading an image) and :py:mod:`matrix_jitsi_bot.interactions.avatar` (:py:class:`~matrix_jitsi_bot.interactions.avatar.AvatarInteraction`); new models :py:class:`~matrix_jitsi_bot.db.models.avatar.Space` and the fields ``speaker_shown``, ``original_avatar`` and ``original_avatar_type`` of :py:class:`~matrix_jitsi_bot.db.models.room.Room`, ``show_speaker`` and ``avatar_spaces`` of :py:class:`~matrix_jitsi_bot.db.models.jitsi.TrackedJitsiRoom`; :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.update_speaker_avatars` shows and restores the avatars. :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.set_account_avatar` takes ``image`` - a path or a web address - instead of ``image_path``.
- **API**: Two new database tables, :py:class:`~matrix_jitsi_bot.db.models.process.BotProcess` (the running bot process, with its process ID and a random secret) and :py:class:`~matrix_jitsi_bot.db.models.process.JitsiMonitor` (a conference the bot is in right now, deleted when it leaves). Run ``matrix-jitsi-bot db migrate`` to update.
- **CLI**: ``matrix-jitsi-bot account set avatar`` also sets the avatar the bot shows in Jitsi conferences.
- **CLI**: ``matrix-jitsi-bot account set avatar`` takes a web address as well as a file: an ``http://`` or ``https://`` image is downloaded first (at most 10 MB, 30 seconds). Its ``<user_id>`` and the file path are completed in the shell - paths by the bot itself, as Typer's own path completion does not work in every shell.
- **CLI**: ``matrix-jitsi-bot status`` now shows how many processes run and which conferences are monitored. Only one ``run`` process is allowed per database, guaranteed by a lock on a file next to the database that the operating system releases however the process ends, so an interrupted bot never blocks the next one, and a second lock per Matrix account stops two databases on one machine from running as the same account. ``run`` refuses to start where the file system can't lock files. ``run`` clears out what it left behind, and ``run --once`` refuses to run while ``run`` does, and the other way around - see :doc:`../hosting-a-bot/index`.
- When the bot joins a Jitsi conference it shows the Matrix profile avatar of its account - shrunk to 128 pixels, read from the profile at startup and whenever it changes - or the logo if the account has none; it logs which of the two it uses.
- ``change avatar when <conference> is active`` (moderators only, and only if the bot may change the room's avatar): while the conference is open, the room's avatar gets a speaker overlay - the whole speaker at the right, in the middle of the height, half as wide as the avatar; a room without an avatar gets the whole speaker as its avatar. The original avatar is downloaded and cached in the database, and restored and removed from the database when the conference closes. ``don't change avatar when <conference> is active`` undoes it. ``change avatar of this chat|this room when <conference> is active`` is the same, explicit. ``change avatar of <space> when <conference> is active`` (e.g. ``#space:example.org``) does it for a Matrix space instead, with the speaker at the bottom right: you and the bot must be allowed to change the space's avatar, and the space must list the chat. The bot joins the space if needed, reports what is wrong - asking for an invitation first, then for the power to change the avatar - and leaves a space that does not list the chat, and accepts space invitations automatically. Spaces are never set up as chats: as an invitation does not tell what kind of room it is, the bot looks at the room's state to find out. A space keeps what chats asked for when the bot leaves and rejoins it. New database tables and fields: run ``matrix-jitsi-bot db migrate`` to update.
- The ``help`` reply shows the bot's version next to the URL of the source code.

Fixed
-----

- **CLI**: ``matrix-jitsi-bot run --once`` now also shows and restores the speaker on avatars, as ``run`` does - it only checked the conferences before, so a conference that ended left the speaker on.
- **CLI**: ``matrix-jitsi-bot account set avatar`` failed with a ``TypeError`` for every image: the upload was given a path, but ``nio`` wants a file object.
- A bot that was stopped while it showed the speaker on an avatar and started again after the conference ended did not always put the avatar of a space back. The avatar of a space - its power levels and its current picture - is now asked of the homeserver instead of what the client holds, and the bot waits for its first sync before it changes avatars, instead of failing and waiting a minute.

Changed
-------

- **API**: ``inspect-jitsi`` 0.3.0 or newer is required: it lets the bot disclose an avatar when it joins a conference.
- **API**: ``JitsiInteraction`` is now :py:class:`~matrix_jitsi_bot.interactions.chat_notification.ChatNotificationInteraction`, in :py:mod:`matrix_jitsi_bot.interactions.chat_notification`, and no longer exported by :py:mod:`matrix_jitsi_bot.db.models`; the helpers its commands share (``_track``, ``_untrack``, ``_resolve_tracked_room``, ...) moved from :py:mod:`matrix_jitsi_bot.db.models.jitsi` to :py:mod:`matrix_jitsi_bot.interactions.jitsi`. :py:class:`~matrix_jitsi_bot.interactions.all.AllInteractions` has ``chat_notification`` instead of ``jitsi``, and ``avatar``. The models no longer import the interactions, so :py:mod:`matrix_jitsi_bot.interactions` needs Django to be set up (:py:func:`~matrix_jitsi_bot.django.setup_django`) before it is imported.
- **CLI**: When the Matrix server does not let the bot start - e.g. it answers ``500`` - ``run`` and ``run --once`` say what the server answered and exit with status 1 instead of printing a traceback, and the client's HTTP session is closed.
- **CLI**: A command that fails because the database is out of date (``OperationalError: no such column: ...``, after updating the bot without migrating) now prints that error and suggests ``matrix-jitsi-bot db migrate`` instead of a traceback.
- While a conference is open and a room tracks who joins or leaves it, the bot now stays in it, using ``inspect-jitsi``'s monitoring mode (:py:func:`~matrix_jitsi_bot.jitsi.monitor_jitsi_room`), instead of joining briefly every second to poll the participant list. Joins and leaves are reported as they happen (a manual ``check`` of a conference the bot is in answers from the database, without joining it a second time), and the bot leaves again once the conference closes (including when it's the only one left in it) or nobody tracks joins and leaves of it anymore - see :doc:`../hosting-a-bot/index`. Closed conferences, and conferences only tracked for open/close/starts, are checked at intervals as before, without joining.
- Updated the pinned dependencies in :file:`uv.lock` (``uv lock --upgrade``), notably ``inspect-jitsi`` 0.1.0 to 0.2.0, ``filelock`` 3.32.7 to 4.0.6, ``starlette`` 1.6.0 to 1.7.0, ``uvicorn`` 0.53.0 to 0.54.0, ``tox`` 4.61.5 to 4.64.4 and ``pydata-sphinx-theme`` 0.21.0 to 0.22.0.
- Documented how to update dependencies in :doc:`../development/index`.
- The test suite runs in seconds instead of minutes: it migrates a database once and every test works on a copy, and tests that never use the database are marked ``no_database``. Tests that change avatars of a real room only run with ``MJB_LIVE=1`` - see :doc:`../development/index`.

0.1.0 - 2026-09-17
==================

Added
-----

- **CLI, API**: The bot's own Matrix account display name (:py:attr:`~matrix_jitsi_bot.db.models.account.Account.display_name`, set via ``matrix-jitsi-bot account set display-name``) is now disclosed as its own display name while briefly joining a Jitsi conference to read its participants (:py:func:`~matrix_jitsi_bot.jitsi.check_jitsi_room`) - it previously joined anonymously. Refreshed from the account's actual Matrix profile at startup, and kept live for the rest of the run whenever that profile's display name changes.
- Pushing a ``v*`` git tag now also creates a GitHub release for it, with the built sdist and wheel attached, alongside the existing PyPI and Docker publishing - see :doc:`../maintenance/index`.

0.0.1 - 2024-09-15
==================

Initial release of ``matrix-jitsi-bot``.

Fixed
-----

- **API**: A conference's "ended" message could be reported twice for what looked like a single continuous session. This happened when the conference briefly reopened (e.g. someone rejoined for a moment) between two checks, and that reopening's participant snapshot came back empty - such a reopening was never itself announced, so the close that followed it looked like a duplicate of the previous one. :py:meth:`~matrix_jitsi_bot.jitsi.JitsiChange.messages_for` now always announces ``Conference <url> started`` for a tracker with ``track_starts`` set, even when that particular check's participant snapshot came back empty - so every "ended" is now paired with a visible "started".

Added
-----

- **API**: Each Matrix room's display name is now tracked (:py:attr:`~matrix_jitsi_bot.db.models.room.Room.name`), kept in sync as it's invited into, as it renames, and as membership changes recompute it, and shown alongside the room ID wherever a room is reported (:py:meth:`~matrix_jitsi_bot.db.models.room.Room.label`) - e.g. ``"pycal"(!kbdVNZeuYWqpMIiXAg:chat.pycal.org)``, with any control characters (including newlines) in the name escaped.
- **CLI**: ``matrix-jitsi-bot status`` now shows each room by that label instead of its bare room ID, and lists what each tracked conference is configured to report there (``open``, ``close``, ``starts``, ``joins``, ``leaves``).
- Pushing a ``v*`` git tag now builds and publishes the package to PyPI automatically, via `trusted publishing <https://docs.pypi.org/trusted-publishers/>`_ (no stored API token), and pushes a Docker image tagged ``X.Y.Z``, ``X.Y``, ``X``, and ``stable`` - see :doc:`../maintenance/index` and :doc:`../hosting-a-bot/docker`.

