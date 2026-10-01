.. _tutorial:

=========================
Track a Jitsi Conference
=========================

This walks through setting up matrix-jitsi-bot to watch a conference in a chat of your own, from scratch.

.. _tutorial-invite-the-bot:

1. Get the bot into a chat
--------------------------

Either invite ``@jitsi-bot:chat.pycal.org`` into an existing chat (public or private), or open a direct chat with it. The bot accepts the invite automatically and joins - unless the chat's name contains "no-bot".

If the chat is brand new and nobody's configured anything in it yet, the bot says so as soon as it joins:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-bot sd-bg-primary sd-text-white sd-rounded-3

        This room isn't configured yet. Say "help" to see what a moderator can set up here.

.. _tutorial-moderators:

2. Only moderators can configure it
-----------------------------------

Tracking commands only take effect for a moderator of the chat (Matrix power level 50 or higher). If you created the chat, you're already one - Matrix grants the creator that power level automatically. In an existing chat, an existing moderator would need to promote you first.

Anyone who isn't a moderator gets turned away, with a ❌ reaction alongside the reply:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        @jitsi-bot: track status of https://meet.hosted.quelltext.eu/matrix-jitsi-bot

    .. grid-item-card::
        :class-card: chat-bot sd-bg-danger sd-text-white sd-rounded-3

        ❌ Sorry, only room moderators can do that.

.. _tutorial-start-tracking:

3. Start tracking
-----------------

As a moderator, start with a conference's full URL:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        @jitsi-bot: track status of https://meet.hosted.quelltext.eu/matrix-jitsi-bot

    .. grid-item-card::
        :class-card: chat-bot sd-bg-success sd-text-white sd-rounded-3

        ✅ Now tracking https://meet.hosted.quelltext.eu/matrix-jitsi-bot.

That alone reports when the conference starts and ends. To also see who's in it the moment it starts, layer on another command - once a conference is tracked, its hostname (``meet.hosted.quelltext.eu``) or short name (``matrix-jitsi-bot``, the last part of the URL) works as a shortcut for the full URL, as long as it's not ambiguous with another conference tracked in the same chat:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        @jitsi-bot: track who starts matrix-jitsi-bot

    .. grid-item-card::
        :class-card: chat-bot sd-bg-success sd-text-white sd-rounded-3

        ✅ Now tracking https://meet.hosted.quelltext.eu/matrix-jitsi-bot.

Every command, with how to say it in other ways and how to undo it, is on the :doc:`commands` page.
If only one conference is tracked in the chat at all, the reference can be left out entirely - ``track who starts`` alone means "that one". Everything that can be tracked:

.. list-table::
    :header-rows: 1

    *   -   Say "track ..."
        -   Reports
    *   -   ``status of <url>``
        -   Start **and** end.
    *   -   ``open status of <url>``
        -   Just the start.
    *   -   ``close status of <url>``
        -   Just the end.
    *   -   ``who is in <url>``
        -   Everyone who joins or leaves, continuously, while it is happening.
    *   -   ``who joins <url>``
        -   Just joins.
    *   -   ``who leaves <url>``
        -   Just leaves.
    *   -   ``who starts <url>``
        -   Who's already there at the start - a one-time snapshot, not continuous.

Each is independent, and adds to what's already tracked rather than replacing it.

.. _tutorial-show-active:

Show that a conference is active
--------------------------------

Like a voice channel on Discord, the chat can show whether a call is going on. A moderator says:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        @jitsi-bot: change avatar when matrix-jitsi-bot is active

While the conference is open, the bot draws a speaker over the chat's avatar. When it closes, the original avatar is back. The bot must be allowed to change the chat's avatar (a power level that allows it), otherwise it says so and does nothing. The original avatar is kept in the bot's database only while the speaker is shown. Undo it with ``don't change avatar when matrix-jitsi-bot is active``. ``change avatar of this chat when matrix-jitsi-bot is active`` and ``change avatar of this room when ...`` mean the same, only explicit.

To change the avatar of a Matrix space instead - e.g. the space of a community that lists your chat - name it by its alias:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        @jitsi-bot: change avatar of #jitsi-bot:chat.pycal.org when matrix-jitsi-bot is active

This works if

- you are allowed to change the avatar of the space yourself,
- the bot is allowed to change it, and
- the space lists this chat as one of its rooms.

The bot joins the space if it is not in it, and checks that. If it is neither in the space nor invited to it, it says so: invite it to the space first, then give it the power to change the space's avatar (in most spaces that is being a moderator), then ask again. If something else is not right, it tells you which. A space that does not list this chat is left again; otherwise the bot stays, so nobody has to invite it a second time after giving it the power. It accepts invitations to spaces automatically, and does not set a space up as a chat. While no conference is active, or when you undo it with ``don't change avatar of #jitsi-bot:chat.pycal.org when matrix-jitsi-bot is active``, the avatar of the space is back to what it was, and the bot leaves the space once no chat uses it.

.. _tutorial-undo:

4. Undo a setting, or stop entirely
-----------------------------------

Prefix any of the phrases above with "don't" (or "do not") to undo just that one, leaving the rest tracked:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        @jitsi-bot: don't track who starts matrix-jitsi-bot

    .. grid-item-card::
        :class-card: chat-bot sd-bg-success sd-text-white sd-rounded-3

        ✅ Updated tracking for https://meet.hosted.quelltext.eu/matrix-jitsi-bot.

Drop the phrase entirely to stop tracking a conference altogether, however it was being tracked:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        @jitsi-bot: don't track matrix-jitsi-bot

    .. grid-item-card::
        :class-card: chat-bot sd-bg-success sd-text-white sd-rounded-3

        ✅ Stopped tracking https://meet.hosted.quelltext.eu/matrix-jitsi-bot.

Or ``don't track any``, which resets the chat's configuration: it stops everything the bot does for every conference in the chat, reports and avatar changes alike.

If a reference doesn't match - a typo, or one that's ambiguous between two tracked conferences - the bot lists what's actually tracked and how each can be referenced, rather than guessing:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        @jitsi-bot: check standup

    .. grid-item-card::
        :class-card: chat-bot sd-bg-danger sd-text-white sd-rounded-3

        "standup" doesn't uniquely identify a tracked conference here. Currently tracked:
        
        - https://meet.hosted.quelltext.eu/matrix-jitsi-bot (meet.hosted.quelltext.eu, matrix-jitsi-bot)

From here, :doc:`try-it-out` shows what the reports themselves look like end to end, and the :doc:`command reference </reference/index>` covers every command in full, including the ones not shown here (``check``, ``status``, ``pause tracking``, ``leave``).
