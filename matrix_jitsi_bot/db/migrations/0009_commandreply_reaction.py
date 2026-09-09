from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("matrix_jitsi_bot", "0008_trackedjitsiroom_track_flags"),
    ]

    operations = [
        migrations.AddField(
            model_name="commandreply",
            name="reaction",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "An emoji to react to the triggering message with, e.g. "
                    "✅/❌ for a Config command's success/failure - empty for none."
                ),
                max_length=8,
            ),
        ),
    ]
