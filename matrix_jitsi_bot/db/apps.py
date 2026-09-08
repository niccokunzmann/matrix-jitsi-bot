from django.apps import AppConfig


class DbConfig(AppConfig):
    name = "matrix_jitsi_bot.db"
    label = "matrix_jitsi_bot"
    default_auto_field = "django.db.models.BigAutoField"
