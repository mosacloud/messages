"""Blob tiered storage + lifecycle FK hardening.

Adds ``encryption_key_id`` and ``storage_location`` to Blob, makes
``raw_content`` nullable for object-storage offload, and adds the
``blob_offload_scan_idx`` partial index used by the offload sweeper.

Drops ``Blob.mailbox`` / ``Blob.maildomain`` / ``blob_has_owner`` —
blob lifetime is now governed by the reference graph (Message,
Attachment, MessageTemplate) plus a Redis-backed upload reservation
window, with a periodic GC sweep (``gc_orphan_blobs_task``). See
``core/services/blob_gc.py`` and ``docs/tiered-storage.md``.

Switches ``Attachment.blob``, ``MessageTemplate.blob``,
``Message.blob`` and ``Message.draft_blob`` to ``on_delete=PROTECT``:
the GC is the only authorised deleter of a Blob and always clears
references first under ``select_for_update`` plus the per-sha
advisory lock; PROTECT turns any other code path that tries to
delete a referenced Blob into a loud, recoverable error rather
than a silent CASCADE that destroys an Attachment row, or a
SET_NULL that nulls out a MessageTemplate's body / a Message's
MIME pointer and leaves the operator with bodyless ghosts.

Dropping the FKs and flipping on_delete are both metadata-only on
Postgres ≥ 11 — RemoveConstraint, RemoveField for FKs, and
on_delete changes are catalog-only operations (Django enforces
on_delete in Python during ``.delete()``; the DB-level FK clause
stays at ``ON DELETE NO ACTION`` regardless).
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0025_alter_threadevent_type_userevent'),
    ]

    operations = [
        migrations.AddField(
            model_name='blob',
            name='encryption_key_id',
            field=models.SmallIntegerField(default=0, help_text='Encryption key ID (0 = no encryption, >=1 = encrypted with MESSAGES_BLOBS_ENCRYPT_KEYS[str(key_id)])', verbose_name='encryption key ID'),
        ),
        migrations.AddField(
            model_name='blob',
            name='storage_location',
            field=models.SmallIntegerField(choices=[(1, 'PostgreSQL'), (2, 'Object Storage')], default=1, help_text='Where the blob content is stored', verbose_name='storage location'),
        ),
        migrations.AlterField(
            model_name='blob',
            name='raw_content',
            field=models.BinaryField(blank=True, help_text='Compressed binary content of the blob (null if in object storage)', null=True, verbose_name='raw content'),
        ),
        migrations.AddIndex(
            model_name='blob',
            index=models.Index(condition=models.Q(('storage_location', 1)), fields=['created_at'], name='blob_offload_scan_idx'),
        ),
        migrations.RemoveConstraint(
            model_name='blob',
            name='blob_has_owner',
        ),
        migrations.RemoveField(
            model_name='blob',
            name='mailbox',
        ),
        migrations.RemoveField(
            model_name='blob',
            name='maildomain',
        ),
        migrations.AlterField(
            model_name='attachment',
            name='blob',
            field=models.ForeignKey(
                help_text='Reference to the blob containing the attachment data',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='attachments',
                to='core.blob',
            ),
        ),
        migrations.AlterField(
            model_name='messagetemplate',
            name='blob',
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    'Reference to the blob containing template content as JSON: '
                    '{html: str, text: str, raw: any}'
                ),
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='message_templates',
                to='core.blob',
            ),
        ),
        migrations.AlterField(
            model_name='message',
            name='blob',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='messages',
                to='core.blob',
            ),
        ),
        migrations.AlterField(
            model_name='message',
            name='draft_blob',
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='draft',
                to='core.blob',
            ),
        ),
    ]
