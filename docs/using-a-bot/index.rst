===============
Getting Started
===============

This chapter describes how to talk to a running matrix-jitsi-bot from a Matrix chat room. Its examples use the bot hosted at ``@jitsi-bot:chat.pycal.org``, watching ``https://meet.hosted.quelltext.eu/matrix-jitsi-bot`` - if you're running your own instead (see :doc:`Self hosting <../hosting-a-bot/index>`), everything below works the same, just with your own bot's user ID and conference URLs.

.. toctree::
    :hidden:

    try-it-out
    track-a-conference

Inviting the bot
-----------------

Invite the bot's Matrix account into a room, the same way you'd invite any other user, e.g. by its user ID (``@jitsi-bot:chat.pycal.org``) in your Matrix client. The bot automatically accepts the invite and joins - unless the room's name contains "no-bot", in which case it leaves right away instead. Once it's in, it says so - a message like "This room isn't configured yet..." shows up if nobody has set anything up in it yet.

Talking to the bot
--------------------

The bot only reacts to messages addressed to it - mention it first, either by its full user ID or a shorter name, both work the same way:

.. code-block:: text

    @jitsi-bot:chat.pycal.org: hello

.. code-block:: text

    jitsi-bot: hello

A bare ``hello`` with no mention at all is not addressed to the bot and gets no reply.

It replies in kind:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        jitsi-bot: hello

    .. grid-item-card::
        :class-card: chat-bot sd-bg-primary sd-text-white sd-rounded-3

        Hello!

Commands currently understood - each one links to its full reference, including any implementation notes:

.. list-table::
    :header-rows: 1

    *   -   You say
        -   The bot replies
        -   Who
    *   -   :py:meth:`hello <matrix_jitsi_bot.interactions.greeting.GreetingInteraction.react_to_hello>`
        -   ``Hello!``
        -   anyone
    *   -   :py:meth:`track status of / open status of / close status of / who is in / who joins / who leaves / who starts <matrix_jitsi_bot.db.models.jitsi.JitsiInteraction.react_to_track>` a URL
        -   Starts tracking that aspect of a conference.
        -   moderators
    *   -   :py:meth:`don't track / do not track <flag> <matrix_jitsi_bot.db.models.jitsi.JitsiInteraction.react_to_untrack_flag>` a URL
        -   Stops tracking just that one aspect, keeping the rest.
        -   moderators
    *   -   :py:meth:`don't track / do not track <matrix_jitsi_bot.db.models.jitsi.JitsiInteraction.react_to_untrack_one>` a URL
        -   Stops tracking one conference entirely.
        -   moderators
    *   -   :py:meth:`don't track any / do not track any <matrix_jitsi_bot.db.models.jitsi.JitsiInteraction.react_to_untrack_any>`
        -   Stops tracking every conference in this room.
        -   moderators
    *   -   :py:meth:`check <matrix_jitsi_bot.db.models.jitsi.JitsiInteraction.react_to_check>`
        -   Checks a tracked conference (or all of them) now and reports its status.
        -   anyone
    *   -   :py:meth:`status <matrix_jitsi_bot.db.models.jitsi.JitsiInteraction.react_to_status>`
        -   Lists tracked conferences and their last-known status (no network check).
        -   anyone
    *   -   :py:meth:`pause tracking <matrix_jitsi_bot.interactions.room.RoomInteraction.react_to_pause>`
        -   Pauses tracking, keeping the room's configuration.
        -   moderators
    *   -   :py:meth:`unpause tracking <matrix_jitsi_bot.interactions.room.RoomInteraction.react_to_unpause>`
        -   Resumes tracking after a pause.
        -   moderators
    *   -   :py:meth:`leave <matrix_jitsi_bot.interactions.room.RoomInteraction.react_to_leave>`
        -   The bot leaves the room and forgets it.
        -   moderators
    *   -   :py:meth:`help <matrix_jitsi_bot.interactions.help.HelpInteraction.react_to_help>`
        -   Lists every command, always in full.
        -   anyone
    *   -   :py:meth:`anything else <matrix_jitsi_bot.interactions.help.HelpInteraction.react_to_anything_else>`
        -   ❌ and a short reminder to say "help" - never the full listing, so a busy room isn't flooded with the same wall of text for every typo.
        -   anyone

A URL in any of these can also be a hostname or short name - see :doc:`track-a-conference` for what that means and how it saves typing once a conference is already being tracked.

Moderator-only commands
--------------------------

Commands that change the bot's settings for a room only take effect for a room Moderator (Matrix power level 50 or higher - the person who created the room, or anyone since promoted). Every such command also gets a ✅ or ❌ reaction on the message that triggered it, on top of any reply - and so does a message the bot doesn't understand at all, always ❌.

As a Moderator:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        jitsi-bot: pause tracking

    .. grid-item-card::
        :class-card: chat-bot sd-bg-success sd-text-white sd-rounded-3

        ✅ Tracking paused.

As anyone else:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        jitsi-bot: pause tracking

    .. grid-item-card::
        :class-card: chat-bot sd-bg-danger sd-text-white sd-rounded-3

        ❌ Sorry, only room moderators can do that.

While a room is paused
-------------------------

A paused room keeps its configuration but stops reacting to anything except unpausing:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        jitsi-bot: hello

    .. grid-item-card::
        :class-card: chat-bot sd-bg-primary sd-text-white sd-rounded-3

        This room is paused - tracking is off, but its configuration is kept. Say "unpause tracking" to resume.

Next steps
-----------

Two how-tos walk through the bot end to end:

-   :doc:`try-it-out` - join the bot's own public room and watch it report a Jitsi conference live.
-   :doc:`track-a-conference` - invite the bot into your own room and configure what it tracks.

Both link back to the full :doc:`command reference </reference/index>` at the end.
