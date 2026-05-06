"""Blob tiered storage + drop of Blob.mailbox / Blob.maildomain / blob_has_owner.

Adds ``encryption_key_id`` and ``storage_location`` to Blob, makes
``raw_content`` nullable for object-storage offload, and adds the
``blob_offload_scan_idx`` partial index used by the offload sweeper.

Blob lifetime is now governed by the reference graph (Message,
Attachment, MessageTemplate) plus a Redis-backed upload reservation
window. The old FK-based cascade is replaced by a periodic GC sweep
(``gc_orphan_blobs_task``). See ``core/services/blob_gc.py`` and
``docs/tiered-storage.md``.

Dropping the FKs is metadata-only on Postgres ≥ 11 — RemoveConstraint
and RemoveField for FKs are catalog-only operations.
"""

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
    ]
