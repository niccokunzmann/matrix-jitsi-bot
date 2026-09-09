from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("matrix_jitsi_bot", "0005_commandreply_sent"),
    ]

    operations = [
        migrations.AddField(
            model_name="room",
            name="paused",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "While paused, the bot ignores everything except unpausing."
                ),
            ),
        ),
        migrations.AddField(
            model_name="room",
            name="should_leave",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Set by the `leave` command; `bot.py` acts on it (calling "
                    "the Matrix API to actually leave) once the reply "
                    "announcing it has been sent, then deletes this row."
                ),
            ),
        ),
        migrations.RemoveField(
            model_name="room",
            name="language",
        ),
    ]
