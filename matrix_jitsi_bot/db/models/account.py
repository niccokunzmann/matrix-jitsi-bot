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
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        """This account's Matrix user ID."""
        return self.user_id
