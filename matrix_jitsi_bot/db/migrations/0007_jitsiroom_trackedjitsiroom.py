import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("matrix_jitsi_bot", "0006_room_paused_remove_room_language"),
    ]

    operations = [
        migrations.CreateModel(
            name="JitsiRoom",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "url",
                    models.URLField(help_text="The Jitsi conference URL.", unique=True),
                ),
                ("is_open", models.BooleanField(default=False)),
                (
                    "participants",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Names last seen in the conference.",
                    ),
                ),
                (
                    "last_checked_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="When this was last checked at all.",
                        null=True,
                    ),
                ),
                (
                    "last_opened_at",
                    models.DateTimeField(
                        blank=True,
                        help_text=(
                            "When this was last seen open - picks the next "
                            "check interval."
                        ),
                        null=True,
                    ),
                ),
                (
                    "next_check_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
            ],
        ),
        migrations.CreateModel(
            name="TrackedJitsiRoom",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "track_status",
                    models.BooleanField(
                        default=True,
                        help_text="Report when the conference opens or closes.",
                    ),
                ),
                (
                    "track_participants",
                    models.BooleanField(
                        default=False,
                        help_text="Report who joins or leaves while it's open.",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "jitsi_room",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tracked_by",
                        to="matrix_jitsi_bot.jitsiroom",
                    ),
                ),
                (
                    "room",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tracked_jitsi_rooms",
                        to="matrix_jitsi_bot.room",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="trackedjitsiroom",
            constraint=models.UniqueConstraint(
                fields=("room", "jitsi_room"), name="unique_tracked_jitsi_room"
            ),
        ),
    ]
