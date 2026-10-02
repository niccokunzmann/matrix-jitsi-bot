"""A message that tells which conferences of a chat to click, and that the
bot edits when they start or end - for the chat to pin.

See :doc:`/reference/commands` for the command, and
:py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.update_status_messages` for
what keeps the message up to date.

The helpers are plain functions, not methods - see
:py:func:`~matrix_jitsi_bot.interactions.jitsi._track`.
"""

from __future__ import annotations

import logging

from matrix_jitsi_bot.db.models import CommandReply, Room, StatusMessage

from .base import BotInteraction, CommandError, Config

logger = logging.getLogger(__name__)

_CREATE_STATUS_MESSAGE = 208

#: What the bot says about the message it created, replying to it.
_NOTE = (
    "✅ This message will be edited with the status of the conferences. "
    "Feel free to pin this message to the chat. "
    "Delete the message to stop this."
)

#: Added to it when the chat had a status message before.
_REPLACED = " The previous status message was deleted."


def _delete_message(interaction: BotInteraction, room: Room, event_id: str) -> None:
    """Delete the message ``event_id`` of the bot in ``room``, logging if
    that does not work - the message is forgotten either way.
    """
    from asgiref.sync import async_to_sync

    client = interaction.matrix_client
    if client is None:
        return
    try:
        async_to_sync(client.delete_message)(room.room_id, event_id)
    except Exception:
        logger.exception("Could not delete the status message %s", event_id)


def forget_status_message(interaction: BotInteraction, room: Room) -> bool:
    """Stop editing the status message of ``room`` and delete it. Whether
    there was one.
    """
    message = StatusMessage.objects.filter(room=room).first()
    if message is None:
        return False
    event_id = message.event_id
    message.delete()
    _delete_message(interaction, room, event_id)
    return True


def _create_status_message(interaction: BotInteraction) -> CommandReply:
    """Post the status message as the reply to the command, remember it -
    replacing the message the chat had before, which is deleted - and
    answer it with what it is for.
    """
    from asgiref.sync import async_to_sync

    room = interaction.conversation.room
    conferences = StatusMessage.conferences_of(room)
    if not conferences:
        raise CommandError(
            "No conference is tracked in this chat yet, so there is nothing "
            "to list. Track one first, e.g. "
            "track status of https://meet.example.org/Room"
        )
    client = interaction.matrix_client
    if client is None:
        raise CommandError("I cannot post a message right now.")

    text = StatusMessage(room=room).current_text()
    response = async_to_sync(client.send_message)(
        room.room_id, text, reply_to=interaction.message.event_id
    )
    event_id = response.event_id
    old = StatusMessage.objects.filter(room=room).first()
    old_event_id = old.event_id if old else None
    StatusMessage.objects.update_or_create(
        room=room, defaults={"event_id": event_id, "text": text}
    )
    if old_event_id:
        _delete_message(interaction, room, old_event_id)
    note = _NOTE + (_REPLACED if old_event_id else "")
    return CommandReply(text=note, reply_to_event_id=event_id)


class StatusMessageInteraction(BotInteraction):
    """Lets a room's Moderators have the bot keep one message up to date
    that links the conferences of the chat.
    """

    title = "A message with the conferences of a chat"

    @Config(
        _CREATE_STATUS_MESSAGE,
        r"create (?:a )?conference status message$",
        (
            "Post a message that links the conferences tracked in this "
            "room to start - or, while some are running, only to join - and "
            "keep it up to date (moderators only). Pin it, or delete it to "
            "stop."
        ),
        ["create conference status message - posts the message to pin"],
    )
    def react_to_create_conference_status_message(self) -> CommandReply:
        """Create the one message of this room that the bot edits with the
        status of the conferences tracked in it - see
        :py:func:`~matrix_jitsi_bot.interactions.status_message._create_status_message`.
        """
        return _create_status_message(self)
