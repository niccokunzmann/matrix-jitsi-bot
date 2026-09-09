"""Django settings for the bot's SQLite database.

Django is only used here for its ORM and migrations - this is not a web project.
"""

import os
from pathlib import Path

os.environ.setdefault("MJB_DB", str(Path.cwd() / "matrix-jitsi-bot.sqlite3"))
# Defaults next to the database, not the current directory, so it lands in
# the same persistent volume/location without needing its own configuration
# (e.g. Docker's /data) - see `matrix_jitsi_bot.django.crypto_store_path`.
os.environ.setdefault(
    "MJB_CRYPTO_STORE",
    str(Path(os.environ["MJB_DB"]).parent / "matrix-jitsi-bot.crypto-store"),
)

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

#: Directory holding the end-to-end encryption store (Olm/Megolm
#: sessions and keys, managed by `nio`/`niobot`, not Django) - see
#: `matrix_jitsi_bot.django.crypto_store_path`.
CRYPTO_STORE_PATH = os.environ["MJB_CRYPTO_STORE"]

INSTALLED_APPS = [
    "matrix_jitsi_bot.db",
]

#: A conversation's oldest messages are pruned once it holds more than
#: this many - see `matrix_jitsi_bot.bot._prune_conversation`.
MAX_CONVERSATION_MESSAGES = int(os.environ.get("MJB_MAX_HISTORY", "100"))

USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
