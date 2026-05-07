"""Backfill ``Attachment.message_id`` from the legacy (now-renamed)
``Attachment._deprecated_messages`` M2M, splitting multi-message rows
into per-message rows.

Replaces the legacy M2M semantics with ``Attachment.message`` (FK) —
see 0027 for the M2M rename + FK add, and 0029 for the NOT NULL flip.
The original M2M had no documented rationale and combined badly with
sha-based blob dedup: ``_get_or_create_attachment_from_blob`` keyed on
``(blob, mailbox)`` so two drafts in the same mailbox attaching the
same content shared a single Attachment row, and sending one of those
drafts deleted the row, silently removing the attachment from the
other draft. After this migration each Attachment belongs to exactly
one (draft) Message — see the ``Attachment`` model docstring.

The data step walks the (renamed) M2M through table and splits each
Attachment that's linked to N>1 messages into N rows (one per
message), keeping the original row for the first message and cloning
for the rest. Attachments with zero messages are dropped (those would
have been collected by the now-deleted ``delete_orphan_attachments``
management command).

The forward step is reversible thanks to the M2M rename in 0027: the
through table ``messages_attachment__deprecated_messages`` is a frozen
snapshot of pre-migration links, which the reverse function uses to
distinguish original Attachment rows (linked in the M2M) from the
per-message clones created here (not in the M2M). See
``reverse_split_multi_message_attachments`` below for what the reverse
restores, drops, and concedes.

Lives in its own migration to avoid mixing ``RunPython`` row
modifications with the schema flip in 0029. Postgres rejects
``ALTER TABLE messages_attachment`` while pending FK trigger events
from earlier ``INSERT/UPDATE/DELETE`` are still buffered in the same
transaction, so the data step must commit on its own first.
"""

from django.db import migrations


def split_multi_message_attachments(apps, schema_editor):
    """Backfill ``Attachment.message_id`` from the legacy M2M through table.

    For each (attachment, message) pair: the first one updates the
    existing Attachment row in place; subsequent ones clone the row
    so each message ends up with its own. Orphan attachments (no
    messages) are deleted at the end.
    """
    Attachment = apps.get_model("core", "Attachment")
    Through = Attachment._deprecated_messages.through  # noqa: SLF001

    seen = set()
    for through_row in Through.objects.all().iterator(chunk_size=1000):
        att_id = through_row.attachment_id
        msg_id = through_row.message_id
        if att_id not in seen:
            seen.add(att_id)
            Attachment.objects.filter(id=att_id).update(message_id=msg_id)
        else:
            original = Attachment.objects.get(id=att_id)
            original.pk = None
            original.id = None
            original.message_id = msg_id
            original.save()

    Attachment.objects.filter(message_id__isnull=True).delete()


def reverse_split_multi_message_attachments(apps, schema_editor):
    """Reverse the data split using the preserved M2M as ground truth.

    Two operations, in order:

    1. Drop the per-message clones created during the forward step.
       Clones are identified as Attachment rows with no entry in the
       preserved ``_deprecated_messages`` through table — only the
       originals carry M2M links. The drop is a single bulk DELETE.
    2. Reset ``message_id`` to NULL on the remaining originals so the
       column can be cleanly dropped when 0027's reverse runs
       ``RemoveField`` on it.

    Not restored:

    - Orphan Attachments deleted by the forward step. They were
      already orphans pre-forward (zero M2M links) and were therefore
      invisible to legacy M2M-based code; their absence post-reverse
      is indistinguishable from pre-forward.
    - Attachments created by the new code AFTER the forward step.
      These have no M2M link (new code writes only the FK) and are
      indistinguishable from clones, so they are dropped too. This is
      the cost of an emergency rollback: data created under the new
      schema that does not fit the old M2M model is lost. Take a
      fresh PG snapshot before rolling back if recent activity must
      be preserved.

    This reverse only handles the data layer. The full
    ``migrate core 0026`` chain may still fail in 0027's reverse on
    other data-dependent operations (re-adding ``blob_has_owner``,
    re-tightening ``raw_content`` to NOT NULL, restoring
    ``draft_blob`` as OneToOne). Those are inherent to the schema
    change and must be cleaned up by operator action before the
    reverse — see ``docs/tiered-storage.md`` for the rollback runbook.
    """
    Attachment = apps.get_model("core", "Attachment")
    Through = Attachment._deprecated_messages.through  # noqa: SLF001

    linked_ids = set(Through.objects.values_list("attachment_id", flat=True))
    Attachment.objects.exclude(id__in=linked_ids).delete()
    Attachment.objects.update(message_id=None)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0027_blob_encryption_key_id_blob_storage_location_and_more'),
    ]

    operations = [
        migrations.RunPython(
            split_multi_message_attachments,
            reverse_split_multi_message_attachments,
        ),
    ]
