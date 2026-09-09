"""Django settings for the bot's SQLite database.

Django is only used here for its ORM and migrations - this is not a web project.
"""

import os
from pathlib import Path

os.environ.setdefault("MJB_DB", str(Path.cwd() / "matrix-jitsi-bot.sqlite3"))

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ["MJB_DB"],
        "OPTIONS": {
            # WAL lets the running bot and CLI commands (account, db, ...) read
            # and write the same database file concurrently without locking
            # each other out - the bot is meant to be reconfigured live.
            "init_command": "PRAGMA journal_mode=wal; PRAGMA busy_timeout=5000;",
        },
    }
}

INSTALLED_APPS = [
    "matrix_jitsi_bot.db",
]

#: A conversation's oldest messages are pruned once it holds more than
#: this many - see `matrix_jitsi_bot.bot._prune_conversation`.
MAX_CONVERSATION_MESSAGES = int(os.environ.get("MJB_MAX_HISTORY", "100"))

USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
