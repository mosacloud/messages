"""Tighten ``Attachment.message`` to NOT NULL once 0028's backfill has
committed.

Companion to 0027 (which renamed the legacy M2M ``Attachment.messages``
→ ``Attachment._deprecated_messages`` and added ``Attachment.message``
as a nullable FK with its final ``related_name='attachments'``) and
0028 (data backfill).

The NOT NULL flip lives in its own migration — and not in 0028 — to
sidestep Postgres' ``cannot ALTER TABLE because it has pending trigger
events`` error: 0028's ``RunPython`` empties pending FK trigger events
into the transaction, and ``ALTER TABLE messages_attachment`` in the
same transaction would be rejected at COMMIT. With the schema step in
its own migration, 0028's triggers fire at COMMIT first, then this
migration runs cleanly in a fresh transaction.

The M2M rename happened in 0027 (no pending-trigger conflict because
0027 is schema-only), so this file is now reduced to a single
metadata-only ALTER on Postgres ≥ 11.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0028_split_attachment_messages'),
    ]

    operations = [
        migrations.AlterField(
            model_name='attachment',
            name='message',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='attachments',
                to='core.message',
                help_text='The draft Message this attachment belongs to',
            ),
        ),
    ]
