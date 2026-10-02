===============
Getting Started
===============

This chapter describes how to talk to a running matrix-jitsi-bot from a Matrix chat. Its examples use the bot hosted at ``@jitsi-bot:chat.pycal.org``, watching ``https://meet.hosted.quelltext.eu/matrix-jitsi-bot`` - if you're running your own instead (see :doc:`Self hosting <../hosting-a-bot/index>`), everything below works the same, just with your own bot's user ID and conference URLs.

.. toctree::

    try-it-out
    track-a-conference

.. _inviting-the-bot:

Inviting the bot
----------------

Invite the bot's Matrix account into a chat, the same way you'd invite any other user, e.g. by its user ID (``@jitsi-bot:chat.pycal.org``) in your Matrix client. The bot automatically accepts the invite and joins - unless the chat's name contains "no-bot", in which case it leaves right away instead. Once it's in, it says so - a message like "This chat isn't configured yet..." shows up if nobody has set anything up in it yet.

What the bot can then do in the chat is explained, command by command, in the :doc:`command reference </reference/commands>`.

.. _talking-to-the-bot:

Talking to the bot
------------------

The bot only reacts to messages addressed to it - mention it first - by its full user ID, as ``@`` and its name, or by its name with a colon - they all work the same way:

.. code-block:: text

    @jitsi-bot:chat.pycal.org: hello

.. code-block:: text

    @jitsi-bot: hello

.. code-block:: text

    jitsi-bot: hello

A bare ``hello`` with no mention at all is not addressed to the bot and gets no reply.

The short forms only work if nobody else in the chat has that name. If another member - on any server - is also called ``jitsi-bot``, the bot does nothing but asks to be mentioned by its full user ID, so that two bots with the same name never both react to one message.

It replies in kind:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        @jitsi-bot: hello

    .. grid-item-card::
        :class-card: chat-bot sd-bg-primary sd-text-white sd-rounded-3

        Hello!

Commands currently understood. Each has a section of its own in :doc:`/reference/commands`, with its structure, a description, an example, and how to stop it:

- :ref:`command-hello` - check that the bot is there and answering. Anyone.
- :ref:`command-track` - notify a chat when a Jitsi conference starts and ends. Moderators.
- :ref:`command-participants` - notify a chat who joins and leaves a Jitsi conference. Moderators.
- :ref:`command-check` - ask for the current state of a conference. Anyone.
- :ref:`command-status` - list the conferences a chat is set up for. Anyone.
- :ref:`command-change-avatar` - draw a speaker on the avatar of a chat while a conference is happening. Moderators.
- :ref:`command-change-space-avatar` - draw a speaker on the avatar of a space that lists the chat. Moderators.
- :ref:`command-status-message` - post a message with the conference links, for the chat to pin. Moderators.
- :ref:`command-pause` - stop the updates of a chat for a while. Moderators.
- :ref:`command-leave` - make the bot leave a chat and forget it. Moderators.
- :ref:`command-help` - show every command the bot understands. Anyone.

A command that sets something up can be undone: its section in :doc:`/reference/commands` has an *Undo this configuration* part.

.. _moderator-only-commands:

Moderator-only commands
-----------------------

Commands that change the bot's settings for a chat only take effect for a moderator of the chat (Matrix power level 50 or higher - the person who created the chat, or anyone since promoted). Every such command also gets a ✅ or ❌ reaction on the message that triggered it, on top of any reply - and so does a message the bot doesn't understand at all, always ❌.

As a Moderator:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        @jitsi-bot: pause tracking

    .. grid-item-card::
        :class-card: chat-bot sd-bg-success sd-text-white sd-rounded-3

        ✅ Tracking paused.

As anyone else:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        @jitsi-bot: pause tracking

    .. grid-item-card::
        :class-card: chat-bot sd-bg-danger sd-text-white sd-rounded-3

        ❌ Sorry, only room moderators can do that.

.. _paused-rooms:

While a chat is paused
----------------------

A paused chat keeps its configuration but stops reacting to anything except unpausing:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        @jitsi-bot: hello

    .. grid-item-card::
        :class-card: chat-bot sd-bg-primary sd-text-white sd-rounded-3

        This room is paused - tracking is off, but its configuration is kept. Say "unpause tracking" to resume.

Have a look at the :doc:`command reference </reference/commands>`.

Questions? See :ref:`get-in-touch`.
