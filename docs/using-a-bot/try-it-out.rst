.. _try-it-out:

============
Try it out
============

The quickest way to see matrix-jitsi-bot in action is the space it's already tracking a conference in - no setup required.

1.  Join the space `#jitsi-bot:chat.pycal.org <https://matrix.to/#/%23jitsi-bot:chat.pycal.org>`_ with your Matrix account, the same way you'd join any other chat. Its avatar shows the speaker while the conference is open.
2.  Open the Jitsi conference the space is already tracking, ``https://meet.hosted.quelltext.eu/matrix-jitsi-bot``, in your browser - or create it, if nobody's in it yet.
3.  Watch the space's chat. The bot notices within moments (it checks more often the more recently the conference was open) and posts about it, without anyone having to ask:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-bot sd-bg-primary sd-text-white sd-rounded-3

        Alice started the conference at https://meet.hosted.quelltext.eu/matrix-jitsi-bot

If someone else joins while it's open, and the chat tracks who joins, a line like this follows:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-bot sd-bg-primary sd-text-white sd-rounded-3

        Bob joined https://meet.hosted.quelltext.eu/matrix-jitsi-bot

You can also ask for the current status yourself, any time, without waiting:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        @jitsi-bot: status

    .. grid-item-card::
        :class-card: chat-bot sd-bg-primary sd-text-white sd-rounded-3

        https://meet.hosted.quelltext.eu/matrix-jitsi-bot: open, with Alice, Bob

Leaving the conference closes the loop:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-bot sd-bg-primary sd-text-white sd-rounded-3

        Conference https://meet.hosted.quelltext.eu/matrix-jitsi-bot ended

From here, :doc:`track-a-conference` shows how to set this up for a chat of your own, and the :doc:`command reference </reference/commands>` covers every command the bot understands.
