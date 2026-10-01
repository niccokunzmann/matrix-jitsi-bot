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
    avatar_mxc = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=(
            "The Matrix content URI of this account's profile avatar, as last "
            "observed - empty if it has none. See `avatar_data_uri`."
        ),
    )
    avatar_data_uri = models.TextField(
        blank=True,
        default="",
        help_text=(
            "This account's profile avatar, shrunk, as a data: URI - what is "
            "disclosed as its avatar when it joins a Jitsi conference. Empty "
            "if it has none: the logo is disclosed then."
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

    def update_avatar(self, mxc: str | None, data_uri: str | None) -> None:
        """Store the Matrix content URI ``mxc`` of this account's profile
        avatar and ``data_uri``, the avatar to disclose in a Jitsi
        conference made from it. ``None`` for an account without one.
        """
        mxc, data_uri = mxc or "", data_uri or ""
        if (mxc, data_uri) != (self.avatar_mxc, self.avatar_data_uri):
            self.avatar_mxc, self.avatar_data_uri = mxc, data_uri
            self.save(update_fields=["avatar_mxc", "avatar_data_uri"])

    @classmethod
    def jitsi_avatar_of(cls, user_id: str) -> str:
        """The avatar the account ``user_id`` runs as discloses when it
        joins a Jitsi conference: its Matrix profile avatar if it has one
        - read fresh from the database every call, like
        :py:meth:`~matrix_jitsi_bot.db.models.account.Account.display_name_of`
        - else the logo, see
        :py:func:`~matrix_jitsi_bot.image.logo_avatar_url`.
        """
        from matrix_jitsi_bot.image import logo_avatar_url

        stored = (
            cls.objects.filter(user_id=user_id)
            .values_list("avatar_data_uri", flat=True)
            .first()
        )
        return stored or logo_avatar_url()
