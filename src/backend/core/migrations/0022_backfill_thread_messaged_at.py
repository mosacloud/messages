"""Backfill messaged_at to exclude both draft and trashed messages."""

from django.db import migrations, models

BATCH_SIZE = 1000


def update_thread_messaged_at(apps, schema_editor):
    """Recompute messaged_at as MAX(created_at) of non-draft, non-trashed messages."""
    Thread = apps.get_model("core", "Thread")
    Message = apps.get_model("core", "Message")

    last_visible = models.Subquery(
        Message.objects.filter(
            thread=models.OuterRef("pk"),
            is_draft=False,
            is_trashed=False,
        )
        .order_by("-created_at")
        .values("created_at")[:1]
    )

    # Batch update threads that have visible (non-draft, non-trashed) messages
    batch_ids = []
    queryset = (
        Thread.objects.filter(messages__is_draft=False, messages__is_trashed=False)
        .distinct()
        .values_list("pk", flat=True)
    )
    for thread_id in queryset.iterator(chunk_size=BATCH_SIZE):
        batch_ids.append(thread_id)
        if len(batch_ids) >= BATCH_SIZE:
            Thread.objects.filter(pk__in=batch_ids).update(messaged_at=last_visible)
            batch_ids = []
    if batch_ids:
        Thread.objects.filter(pk__in=batch_ids).update(messaged_at=last_visible)

    # Batch nullify threads with only drafts or trashed messages
    batch_ids = []
    visible_threads = Thread.objects.filter(
        messages__is_draft=False, messages__is_trashed=False,
    )
    queryset = (
        Thread.objects.exclude(pk__in=visible_threads.values("pk"))
        .exclude(messaged_at__isnull=True)
        .values_list("pk", flat=True)
    )
    for thread_id in queryset.iterator(chunk_size=BATCH_SIZE):
        batch_ids.append(thread_id)
        if len(batch_ids) >= BATCH_SIZE:
            Thread.objects.filter(pk__in=batch_ids).update(messaged_at=None)
            batch_ids = []
    if batch_ids:
        Thread.objects.filter(pk__in=batch_ids).update(messaged_at=None)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0021_messagetemplate_metadata_messagetemplate_signature_and_more"),
    ]

    operations = [
        migrations.RunPython(update_thread_messaged_at, migrations.RunPython.noop, elidable=True),
    ]
