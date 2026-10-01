"""What the bot remembers while it changes an avatar, and the Matrix
spaces whose avatar it changes.

See :py:class:`~matrix_jitsi_bot.interactions.avatar.AvatarInteraction`
for the commands and
:py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.update_speaker_avatars`
for the changing itself.
"""

from __future__ import annotations

from django.db import models

from .account import Account


class AvatarCache(models.Model):
    """A Matrix room - a chat or a space - whose avatar the bot
    changes while a conference is active, and the original avatar it
    keeps until it is restored.
    """

    speaker_shown = models.BooleanField(
        default=False,
        help_text=(
            "Whether the room's avatar currently has the speaker "
            "overlay. While set, `original_avatar` holds what to restore."
        ),
    )
    original_avatar = models.BinaryField(
        null=True,
        blank=True,
        help_text=(
            "The avatar image the room had before the speaker overlay, "
            "cached only while `speaker_shown`. Empty: it had none."
        ),
    )
    original_avatar_type = models.CharField(
        max_length=255, blank=True, default="", help_text="Its content type."
    )

    class Meta:
        abstract = True

    def cache_avatar(self, image: bytes | None, content_type: str = "") -> None:
        """Remember ``image`` (``None``: there is none) as the avatar to
        restore, and that the speaker is shown.
        """
        self.original_avatar = image
        self.original_avatar_type = content_type
        self.speaker_shown = True
        self.save(
            update_fields=["original_avatar", "original_avatar_type", "speaker_shown"]
        )

    def uncache_avatar(self) -> None:
        """Remove the cached avatar from the database - it is restored."""
        self.original_avatar = None
        self.original_avatar_type = ""
        self.speaker_shown = False
        self.save(
            update_fields=["original_avatar", "original_avatar_type", "speaker_shown"]
        )


class Space(AvatarCache):
    """A Matrix space the bot is in to change its avatar, for the chats
    that list it - see
    :py:attr:`~matrix_jitsi_bot.db.models.jitsi.TrackedJitsiRoom.avatar_spaces`.
    """

    room_id = models.CharField(
        max_length=255, unique=True, help_text="The space's room ID."
    )
    alias = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="The alias it was asked for, e.g. #space:example.org.",
    )
    account = models.ForeignKey(
        Account,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="spaces",
        help_text="Which bot account is in this space.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        """The alias it was asked for, or else its room ID."""
        return self.alias or self.room_id

    def wants_speaker(self) -> bool:
        """Whether the space's avatar should show the speaker now: a
        chat that is not paused lists it for a conference that is open.
        """
        return self.tracked_by.filter(
            room__paused=False, jitsi_room__is_open=True
        ).exists()

    def is_used(self) -> bool:
        """Whether any chat is set up to change this space's avatar."""
        return self.tracked_by.exists()

    @classmethod
    def with_speaker_work(cls, account: Account) -> list[Space]:
        """The spaces of ``account`` that show a speaker or are used to."""
        from django.db.models import Q

        return list(
            cls.objects.filter(account=account)
            .filter(Q(speaker_shown=True) | Q(tracked_by__isnull=False))
            .distinct()
        )

    @classmethod
    def unused(cls, account: Account) -> list[Space]:
        """The spaces of ``account`` that no chat changes the avatar of
        anymore and that show no speaker: the bot leaves them.
        """
        return list(
            cls.objects.filter(
                account=account, speaker_shown=False, tracked_by__isnull=True
            )
        )
