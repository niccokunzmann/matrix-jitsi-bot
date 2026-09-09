from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("matrix_jitsi_bot", "0007_jitsiroom_trackedjitsiroom"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="trackedjitsiroom",
            name="track_participants",
        ),
        migrations.RemoveField(
            model_name="trackedjitsiroom",
            name="track_status",
        ),
        migrations.AddField(
            model_name="trackedjitsiroom",
            name="track_open",
            field=models.BooleanField(
                default=False, help_text="Report when the conference opens."
            ),
        ),
        migrations.AddField(
            model_name="trackedjitsiroom",
            name="track_close",
            field=models.BooleanField(
                default=False, help_text="Report when the conference closes."
            ),
        ),
        migrations.AddField(
            model_name="trackedjitsiroom",
            name="track_starts",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Report who's in the conference the moment it's noticed open."
                ),
            ),
        ),
        migrations.AddField(
            model_name="trackedjitsiroom",
            name="track_joins",
            field=models.BooleanField(
                default=False, help_text="Report individual joins while it's open."
            ),
        ),
        migrations.AddField(
            model_name="trackedjitsiroom",
            name="track_leaves",
            field=models.BooleanField(
                default=False, help_text="Report individual leaves while it's open."
            ),
        ),
    ]
