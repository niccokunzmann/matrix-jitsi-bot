from __future__ import annotations

from django.db import models


class Account(models.Model):
    """A Matrix account the bot can log in and run as.

    Holds everything nio-bot needs to log in: either a password, or a
    device ID and access token from a previous login.
    """

    homeserver = models.URLField(
        help_text="The Matrix homeserver URL, e.g. https://matrix.org"
    )
    user_id = models.CharField(
        max_length=255,
        unique=True,
        help_text="The bot's Matrix user ID, e.g. @bot:matrix.org",
    )
    device_id = models.CharField(max_length=255, blank=True, default="")
    access_token = models.CharField(max_length=1024, blank=True, default="")
    password = models.CharField(max_length=255, blank=True, default="")
    display_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=(
            "This account's Matrix profile display name, as last observed - "
            "see matrix_jitsi_bot.bot.MatrixJitsiBot._sync_own_display_name "
            "and _sync_room_members."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        """This account's Matrix user ID."""
        return self.user_id

    def update_display_name(self, display_name: str | None) -> None:
        """Update this account's stored
        :py:attr:`~matrix_jitsi_bot.db.models.account.Account.display_name`
        to ``display_name``, saving only if it actually changed.

        ``display_name`` is ``None`` for an account with no Matrix
        profile display name set - treated the same as ``""``.
        """
        display_name = display_name or ""
        if display_name != self.display_name:
            self.display_name = display_name
            self.save(update_fields=["display_name"])

    @classmethod
    def display_name_of(cls, user_id: str) -> str | None:
        """The stored Matrix profile display name for the account
        ``user_id`` runs as, read fresh from the database every call -
        deliberately not cached in this process, so a display name
        changed by some other means (another process, a direct
        database edit) takes effect on the very next check.

        ``None`` if no such account is configured, or it has no
        display name stored.
        """
        display_name = (
            cls.objects.filter(user_id=user_id)
            .values_list("display_name", flat=True)
            .first()
        )
        return display_name or None
