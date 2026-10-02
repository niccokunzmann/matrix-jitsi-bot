"""The message of a chat that lists the conferences one can click to start
or join - edited by the bot whenever they change.

See :py:mod:`matrix_jitsi_bot.interactions.status_message` for the command
that creates it, and
:py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.update_status_messages` for
how it is kept up to date.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import models

from .jitsi import JitsiRoom, TrackedJitsiRoom
from .room import Room

if TYPE_CHECKING:
    from .account import Account


def no_conference_text() -> str:
    """Said when nothing is tracked in the chat anymore: what to read to
    set one up.
    """
    from matrix_jitsi_bot.version import documentation_url

    url = documentation_url("using-a-bot/track-a-conference")
    return (
        "No Jitsi conference is set up in this chat. "
        f"Here is how to set one up: <{url}>"
    )


def conference_status_text(conferences: list[JitsiRoom]) -> str:
    """The text of the status message for ``conferences``: if none is
    running, a link to start each one; if some are, only a link to join
    each of those - so nobody clicks a conference that is not active and
    starts it, to wonder why they are alone.
    """
    if not conferences:
        return no_conference_text()
    running = [conference for conference in conferences if conference.is_open]
    if running:
        urls = [conference.url for conference in running]
        if len(urls) == 1:
            return f"Click <{urls[0]}> to join the Audio/Video conference."
        head = "Click a link to join the Audio/Video conferences:"
    else:
        urls = [conference.url for conference in conferences]
        if len(urls) == 1:
            return f"Click <{urls[0]}> to start the Audio/Video conference."
        head = "Click a link to start the Audio/Video conference:"
    return head + "\n" + "\n".join(f"- <{url}>" for url in urls)


class StatusMessage(models.Model):
    """The one message in a chat that shows the conferences tracked there.

    A chat has at most one: creating another replaces it. It is forgotten
    when somebody deletes the message, when the chat is reset and when the
    bot leaves the chat.
    """

    room = models.OneToOneField(
        Room, on_delete=models.CASCADE, related_name="status_message"
    )
    event_id = models.CharField(
        max_length=255, unique=True, help_text="The Matrix event of the message."
    )
    text = models.TextField(help_text="What the message says now.")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        """Which chat the message is in."""
        return f"status message of {self.room.room_id}"

    @staticmethod
    def conferences_of(room: Room) -> list[JitsiRoom]:
        """The conferences tracked in ``room``, in the order they were
        added.
        """
        return [
            tracked.jitsi_room
            for tracked in TrackedJitsiRoom.objects.filter(room=room)
            .select_related("jitsi_room")
            .order_by("id")
        ]

    def current_text(self) -> str:
        """What the message should say now."""
        return conference_status_text(self.conferences_of(self.room))

    @classmethod
    def outdated(cls, account: Account) -> list[tuple[StatusMessage, str]]:
        """The messages of the chats of ``account`` that are not paused
        and do not say what they should, each with the new text.
        """
        result = []
        for message in cls.objects.filter(
            room__account=account, room__paused=False
        ).select_related("room"):
            text = message.current_text()
            if text != message.text:
                result.append((message, text))
        return result
