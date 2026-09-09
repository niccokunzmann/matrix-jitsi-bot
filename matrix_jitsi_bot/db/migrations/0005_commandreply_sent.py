from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("matrix_jitsi_bot", "0004_alter_message_event_id_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="commandreply",
            name="sent",
            field=models.BooleanField(
                default=False,
                help_text="Whether this reply was sent to Matrix successfully.",
            ),
        ),
    ]
