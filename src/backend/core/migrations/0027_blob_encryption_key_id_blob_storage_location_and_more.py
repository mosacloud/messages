"""Blob tiered storage + lifecycle FK hardening + ``Message.draft_blob``
OneToOneField → ForeignKey + nullable ``Attachment.message`` + ``MailboxBlob``
model.

Schema-only first half of a 3-part change. The remaining steps are split
to avoid Postgres ``cannot ALTER TABLE because it has pending trigger
events``: combining ``RunPython`` row modifications with later
``ALTER TABLE`` on ``messages_attachment`` in the same transaction
makes deferred FK trigger checks block the trailing schema ops on
COMMIT.

  - 0027 (this file): all schema changes, including the rename of
    the legacy M2M ``Attachment.messages`` → ``_deprecated_messages``
    and the addition of ``Attachment.message`` as nullable FK with
    its final ``related_name='attachments'``.
  - 0028: data migration that backfills ``Attachment.message_id`` from
    the (renamed) M2M and splits multi-message rows.
  - 0029: tightens the FK to NOT NULL (must run in a separate
    transaction from 0028's RunPython; see the docstring of 0028 /
    0029 for the Postgres pending-trigger constraint).

Adds ``encryption_key_id`` and ``storage_location`` to Blob, makes
``raw_content`` nullable for object-storage offload, and adds the
``blob_offload_scan_idx`` partial index used by the offload sweeper.

Renames ``Blob.mailbox`` → ``Blob._deprecated_mailbox`` and
``Blob.maildomain`` → ``Blob._deprecated_maildomain`` (with
``on_delete=SET_NULL`` to stay compatible with the new ``PROTECT``
constraints on incoming blob FKs) rather than dropping them outright.
The historical owner data is preserved as a rollback safety net; the
real ``DROP COLUMN`` is deferred to a follow-up migration. Drops the
``blob_has_owner`` CHECK constraint — blob lifetime is now governed by
the reference graph (Message, Attachment, MessageTemplate, MailboxBlob),
with a periodic GC sweep (``gc_orphan_blobs_task``). See
``core/services/blob_gc.py`` and ``docs/tiered-storage.md``.

Adds ``MailboxBlob``: the JMAP upload reservation row that protects
a freshly-uploaded blob from GC during the upload-then-attach
window, and proves provenance for the attach-by-id authz check.
Replaces a pre-existing Redis ``SETEX`` reservation primitive with
a real DB row carrying an explicit ``expires_at`` timestamp; the
GC walks ``MailboxBlob`` like any other reference (with the extra
``expires_at > now()`` filter to exclude stale rows) and deletes
expired rows inline before the blob delete (under ``PROTECT``).

Switches ``Attachment.blob``, ``MessageTemplate.blob``,
``Message.blob`` and ``Message.draft_blob`` to ``on_delete=PROTECT``:
the GC is the only authorised deleter of a Blob and always clears
references first under ``select_for_update`` plus the per-sha
advisory lock; PROTECT turns any other code path that tries to
delete a referenced Blob into a loud, recoverable error rather
than a silent CASCADE that destroys an Attachment row, or a
SET_NULL that nulls out a MessageTemplate's body / a Message's
MIME pointer and leaves the operator with bodyless ghosts.

Demotes ``Message.draft_blob`` from ``OneToOneField`` to
``ForeignKey`` (drops the UNIQUE constraint on the
``draft_blob_id`` column). The OneToOne combined badly with
sha-based blob dedup: ``BlobManager.create_blob`` returns the
same Blob row for two drafts with identical content, then
OneToOne's uniqueness rejected the second draft's INSERT with an
IntegrityError — easily reproduced by two drafts that share an
empty body. The reverse-relation rename
``Blob.draft`` (single Message) → ``Blob.drafts`` (queryset) is
also encoded; the only consumer is the
``mailbox_usage_metrics`` storage subquery, updated to walk
``drafts__`` instead of ``draft__``.

Also renames the legacy M2M ``Attachment.messages`` to
``Attachment._deprecated_messages`` (with ``related_name``
``_deprecated_attachments`` on Message). Doing the rename here — in
the schema-only migration, before 0028's RunPython — frees the
``attachments`` reverse name on Message so the new
``Attachment.message`` FK can claim it directly, and avoids the
Postgres pending-trigger conflict that prevents combining schema
ops with the data step in 0028. The renamed M2M and its through
table (now ``messages_attachment__deprecated_messages``) are kept
intact as a frozen snapshot of pre-migration links — rollback
safety net, to be dropped in a follow-up migration.

Dropping the FKs, flipping on_delete, and the OneToOne→FK swap are
all metadata-only on Postgres ≥ 11 (Django enforces on_delete in
Python; the DB-level FK clause stays at ``ON DELETE NO ACTION``
regardless). The OneToOne→FK swap drops a UNIQUE constraint, also
catalog-only.

Rollback notes
==============

This migration's reverse is best-effort. Two known data-dependent
issues block ``migrate core 0026`` after the new code has run in
production for any non-trivial time:

1. ``blob_has_owner`` CHECK constraint. New blobs are created
   without an owner (the new model does not populate
   ``_deprecated_mailbox`` / ``_deprecated_maildomain``), so re-
   adding the CHECK at rollback would fail. Mitigated below via
   ``SeparateDatabaseAndState`` — the DB-level DROP is one-way
   (reverse is a no-op) while Django state cleanly reverts. The
   cost: after rollback the DB no longer enforces the CHECK; the
   ``main`` code path still satisfies it functionally, just without
   the safety net. To restore the DB-level CHECK post-rollback, an
   operator must first reconcile orphan blobs (assign or delete)
   then ``ALTER TABLE messages_blob ADD CONSTRAINT blob_has_owner
   CHECK (mailbox_id IS NOT NULL OR maildomain_id IS NOT NULL);``.

2. ``Message.draft_blob`` UNIQUE constraint (from the OneToOne).
   Sha-based blob dedup means two drafts with identical body content
   (e.g. both empty — BlockNote's default empty state serializes
   deterministically) share the same blob row. Re-adding UNIQUE at
   rollback fails the moment ≥ 2 such drafts exist, which is
   essentially "any production usage past the first draft created".
   Not mitigated in this migration because the auto-generated UNIQUE
   constraint name is fragile to reach across schema-editor
   versions. **Manual cleanup required before rollback**: pick one
   Message per duplicate ``draft_blob_id`` and null out the others.
   Example::

       UPDATE messages_message
       SET    draft_blob = NULL
       WHERE  id IN (
         SELECT id FROM (
           SELECT id, ROW_NUMBER() OVER (
                   PARTITION BY draft_blob_id ORDER BY created_at DESC
                 ) AS rn
           FROM   messages_message
           WHERE  draft_blob_id IS NOT NULL
         ) ranked
         WHERE rn > 1
       );

   Then ``migrate core 0026`` succeeds. The dropped drafts can be
   re-created from the kept one (they share content by definition);
   alternatively, take a fresh PG snapshot before rollback if recent
   draft activity must be preserved verbatim.

For other rollback flavours (full DB restore from snapshot, partial
data restore) neither of these limits apply — they are specific to
the Django ``migrate`` chain.
"""

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0026_userevent_usrevt_user_thread_assign_uniq'),
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
        # Asymmetric drop of ``blob_has_owner``: forward drops the
        # constraint at the DB level; reverse is a no-op. Re-adding the
        # CHECK at rollback would fail systematically — the new code
        # path creates blobs without populating either
        # ``_deprecated_mailbox`` or ``_deprecated_maildomain``, so any
        # blob created post-deploy violates the constraint. Django
        # state still gets ``RemoveConstraint`` applied (so the model
        # state of this branch matches), and on rollback Django state
        # reverts to "constraint present" (matching ``main``'s model)
        # — only the DB-level CHECK is permanently gone. That is the
        # acceptable cost for a working
        # ``migrate core 0026`` chain. Re-adding the constraint
        # manually post-rollback is a one-line ``ALTER TABLE`` once
        # orphan blobs have been cleaned up by an operator.
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE messages_blob DROP CONSTRAINT IF EXISTS blob_has_owner;",
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
            state_operations=[
                migrations.RemoveConstraint(
                    model_name='blob',
                    name='blob_has_owner',
                ),
            ],
        ),
        # Expand/contract pattern: ``Blob.mailbox`` and ``Blob.maildomain``
        # are kept under a ``_deprecated_`` prefix and ``on_delete=SET_NULL``
        # so the historical owner column survives the migration. The actual
        # ``DROP COLUMN`` is deferred to a follow-up migration once the
        # deprecation has been validated in production.
        # ``CASCADE`` is downgraded to ``SET_NULL`` because cascade-delete of a
        # blob would now violate the ``PROTECT`` constraints on
        # ``Message.blob`` / ``Attachment.blob`` / ``MessageTemplate.blob``.
        migrations.RenameField(
            model_name='blob',
            old_name='mailbox',
            new_name='_deprecated_mailbox',
        ),
        migrations.AlterField(
            model_name='blob',
            name='_deprecated_mailbox',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='_deprecated_blobs',
                to='core.mailbox',
                help_text='DEPRECATED: legacy owner pre-tiered-storage. Kept for rollback; do not read or write. To be dropped in a future migration.',
            ),
        ),
        migrations.RenameField(
            model_name='blob',
            old_name='maildomain',
            new_name='_deprecated_maildomain',
        ),
        migrations.AlterField(
            model_name='blob',
            name='_deprecated_maildomain',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='_deprecated_blobs',
                to='core.maildomain',
                help_text='DEPRECATED: legacy owner pre-tiered-storage. Kept for rollback; do not read or write. To be dropped in a future migration.',
            ),
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
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='drafts',
                to='core.blob',
            ),
        ),

        # Rename the legacy M2M to ``_deprecated_messages`` *before*
        # adding the new FK, so the new FK can claim
        # ``related_name='attachments'`` directly (the M2M's reverse
        # becomes ``_deprecated_attachments``, freeing the original
        # name). Pure schema, no pending FK trigger events at this
        # point in 0027 → safe to keep both the rename and the FK add
        # in the same transaction.
        migrations.RenameField(
            model_name='attachment',
            old_name='messages',
            new_name='_deprecated_messages',
        ),
        migrations.AlterField(
            model_name='attachment',
            name='_deprecated_messages',
            field=models.ManyToManyField(
                to='core.message',
                blank=True,
                related_name='_deprecated_attachments',
                help_text='DEPRECATED: legacy multi-message linking. Kept for rollback; do not read or write. To be dropped in a future migration.',
            ),
        ),

        # Add Attachment.message as nullable FK with its final
        # ``related_name='attachments'`` (made available by the M2M
        # rename above). 0028 backfills the column; 0029 only flips
        # it to NOT NULL once the backfill has committed.
        migrations.AddField(
            model_name='attachment',
            name='message',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='attachments',
                to='core.message',
                help_text='The draft Message this attachment belongs to',
            ),
        ),

        # --- MailboxBlob: JMAP upload-reservation row --- #
        migrations.CreateModel(
            name='MailboxBlob',
            fields=[
                (
                    'id',
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        help_text='primary key for the record as UUID',
                        primary_key=True,
                        serialize=False,
                        verbose_name='id',
                    ),
                ),
                (
                    'created_at',
                    models.DateTimeField(
                        auto_now_add=True,
                        editable=False,
                        help_text='date and time at which a record was created',
                        verbose_name='created on',
                    ),
                ),
                (
                    'updated_at',
                    models.DateTimeField(
                        auto_now=True,
                        editable=False,
                        help_text='date and time at which a record was last updated',
                        verbose_name='updated on',
                    ),
                ),
                (
                    'expires_at',
                    models.DateTimeField(
                        null=True,
                        blank=True,
                        help_text='When the reservation stops protecting the blob from GC. Null or past = stale.',
                    ),
                ),
                (
                    'blob',
                    models.ForeignKey(
                        help_text='The blob whose upload reservation this row holds.',
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='mailbox_uploads',
                        to='core.blob',
                    ),
                ),
                (
                    'mailbox',
                    models.ForeignKey(
                        help_text='The mailbox that uploaded the blob.',
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='blob_uploads',
                        to='core.mailbox',
                    ),
                ),
            ],
            options={
                'verbose_name': 'mailbox blob',
                'verbose_name_plural': 'mailbox blobs',
                'db_table': 'messages_mailboxblob',
                'unique_together': {('blob', 'mailbox')},
            },
        ),
        migrations.AddIndex(
            model_name='mailboxblob',
            index=models.Index(
                fields=['expires_at'], name='mailboxblob_expires_idx'
            ),
        ),
    ]
