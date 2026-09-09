=========================
Track a Jitsi Conference
=========================

This walks through setting up matrix-jitsi-bot to watch a conference in a room of your own, from scratch.

1. Get the bot into a room
----------------------------

Either invite ``@jitsi-bot:chat.pycal.org`` into an existing room (public or private), or open a direct chat with it. The bot accepts the invite automatically and joins - unless the room's name contains "no-bot".

If the room is brand new and nobody's configured anything in it yet, the bot says so as soon as it joins:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-bot sd-bg-primary sd-text-white sd-rounded-3

        This room isn't configured yet. Say "help" to see what a moderator can set up here.

2. Only moderators can configure it
--------------------------------------

Tracking commands only take effect for a room Moderator (Matrix power level 50 or higher). If you created the room, you're already one - Matrix grants the creator that power level automatically. In an existing room, an existing moderator would need to promote you first.

Anyone who isn't a moderator gets turned away, with a ❌ reaction alongside the reply:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        jitsi-bot: track status of https://meet.hosted.quelltext.eu/matrix-jitsi-bot

    .. grid-item-card::
        :class-card: chat-bot sd-bg-danger sd-text-white sd-rounded-3

        ❌ Sorry, only room moderators can do that.

3. Start tracking
-------------------

As a moderator, start with a conference's full URL:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        jitsi-bot: track status of https://meet.hosted.quelltext.eu/matrix-jitsi-bot

    .. grid-item-card::
        :class-card: chat-bot sd-bg-success sd-text-white sd-rounded-3

        ✅ Now tracking https://meet.hosted.quelltext.eu/matrix-jitsi-bot.

That alone reports when the conference opens and closes. To also see who's in it the moment it opens, layer on another command - once a conference is tracked, its hostname (``meet.hosted.quelltext.eu``) or short name (``matrix-jitsi-bot``, the last part of the URL) works as a shortcut for the full URL, as long as it's not ambiguous with another conference tracked in the same room:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        jitsi-bot: track who starts matrix-jitsi-bot

    .. grid-item-card::
        :class-card: chat-bot sd-bg-success sd-text-white sd-rounded-3

        ✅ Now tracking https://meet.hosted.quelltext.eu/matrix-jitsi-bot.

If only one conference is tracked in the room at all, the reference can be left out entirely - ``track who starts`` alone means "that one". Everything that can be tracked:

.. list-table::
    :header-rows: 1

    *   -   Say "track ..."
        -   Reports
    *   -   ``status of <url>``
        -   Open **and** close.
    *   -   ``open status of <url>``
        -   Just open.
    *   -   ``close status of <url>``
        -   Just close.
    *   -   ``who is in <url>``
        -   Everyone who joins or leaves, continuously, while it's open.
    *   -   ``who joins <url>``
        -   Just joins.
    *   -   ``who leaves <url>``
        -   Just leaves.
    *   -   ``who starts <url>``
        -   Who's already there the moment the conference is noticed open - a one-time snapshot, not continuous.

Each is independent, and adds to what's already tracked rather than replacing it.

4. Undo a setting, or stop entirely
--------------------------------------

Prefix any of the phrases above with "don't" (or "do not") to undo just that one, leaving the rest tracked:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        jitsi-bot: don't track who starts matrix-jitsi-bot

    .. grid-item-card::
        :class-card: chat-bot sd-bg-success sd-text-white sd-rounded-3

        ✅ Updated tracking for https://meet.hosted.quelltext.eu/matrix-jitsi-bot.

Drop the phrase entirely to stop tracking a conference altogether, however it was being tracked:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        jitsi-bot: don't track matrix-jitsi-bot

    .. grid-item-card::
        :class-card: chat-bot sd-bg-success sd-text-white sd-rounded-3

        ✅ Stopped tracking https://meet.hosted.quelltext.eu/matrix-jitsi-bot.

Or ``don't track any`` to clear everything tracked in the room at once.

If a reference doesn't match - a typo, or one that's ambiguous between two tracked conferences - the bot lists what's actually tracked and how each can be referenced, rather than guessing:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        jitsi-bot: check standup

    .. grid-item-card::
        :class-card: chat-bot sd-bg-danger sd-text-white sd-rounded-3

        "standup" doesn't uniquely identify a tracked conference here. Currently tracked:
        
        - https://meet.hosted.quelltext.eu/matrix-jitsi-bot (meet.hosted.quelltext.eu, matrix-jitsi-bot)

From here, :doc:`try-it-out` shows what the reports themselves look like end to end, and the :doc:`command reference </reference/index>` covers every command in full, including the ones not shown here (``check``, ``status``, ``pause tracking``, ``leave``).
