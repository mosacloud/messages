# Generated migration for mime_id index

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_threadaccess_origin'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='message',
            index=models.Index(fields=['mime_id'], name='idx_message_mime_id'),
        ),
    ]
