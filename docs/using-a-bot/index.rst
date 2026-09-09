=================
Bot configuration
=================

This chapter describes how to talk to a running matrix-jitsi-bot from a Matrix chat room, once it has been :doc:`hosted <../hosting-a-bot/index>`.

Inviting the bot
-----------------

Invite the bot's Matrix account into a room, the same way you'd invite any other user, e.g. by its user ID (``@bot:example.org``) in your Matrix client. The bot automatically accepts the invite and joins.

Talking to the bot
--------------------

Once it's in a room, the bot reacts to messages matching certain commands. A command can be addressed to the bot directly, or prefixed with a mention of its name - both of the following work the same way:

.. code-block:: text

    hello

.. code-block:: text

    @bot:example.org: hello

.. code-block:: text

    bot: hello

It replies in kind:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        hello

    .. grid-item-card::
        :class-card: chat-bot sd-bg-primary sd-text-white sd-rounded-3

        hello

Commands currently understood:

.. list-table::
    :header-rows: 1

    *   -   You say
        -   The bot replies
    *   -   ``hello``
        -   ``hello``
    *   -   ``list languages``
        -   A comma-separated list of languages the bot can speak.
    *   -   ``set language to <lang>``
        -   Changes the language the bot speaks in this room to ``<lang>``, if it's supported and you're a room Moderator.

Changing the bot's settings
------------------------------

``set language to <lang>`` only takes effect for a room Moderator (Matrix power level 50 or higher) - anyone else asking gets told so instead of the setting being changed. This is the general rule for anything that reconfigures the bot for a room, as more such settings are added.

As a Moderator:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        set language to de

    .. grid-item-card::
        :class-card: chat-bot sd-bg-success sd-text-white sd-rounded-3

        Language set to de.

As anyone else:

.. grid:: 1
    :gutter: 1

    .. grid-item-card::
        :class-card: chat-you sd-bg-light sd-rounded-3

        set language to de

    .. grid-item-card::
        :class-card: chat-bot sd-bg-danger sd-text-white sd-rounded-3

        Sorry, only room moderators can change my settings.

.. note::

    Watching and reporting on Jitsi conference status - the bot's original purpose, see the project's `README <https://github.com/niccokunzmann/matrix-jitsi-bot#readme>`_ - is planned but not yet implemented. This chapter will grow to cover those commands once they land.
