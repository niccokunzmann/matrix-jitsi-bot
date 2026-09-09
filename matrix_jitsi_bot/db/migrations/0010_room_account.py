import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("matrix_jitsi_bot", "0009_commandreply_reaction"),
    ]

    operations = [
        migrations.AddField(
            model_name="room",
            name="account",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Which bot account is in this room - set when the bot "
                    "joins it (or reconciles finding itself already "
                    "joined) while running as that account. `null` for a "
                    "room from before this field existed, until the bot "
                    "next joins/reconciles it."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="rooms",
                to="matrix_jitsi_bot.account",
            ),
        ),
    ]
