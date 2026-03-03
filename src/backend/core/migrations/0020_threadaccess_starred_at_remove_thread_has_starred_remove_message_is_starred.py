"""Add starred_at to ThreadAccess, populate from Thread.has_starred, then remove legacy fields."""

from django.db import migrations, models
from django.utils import timezone


def populate_starred_at(apps, schema_editor):
    """Populate ThreadAccess.starred_at from Thread.has_starred.

    All accesses on previously starred threads inherit the flag since the old
    model was global (not per-mailbox).
    """
    ThreadAccess = apps.get_model("core", "ThreadAccess")
    ThreadAccess.objects.filter(thread__has_starred=True).update(
        starred_at=timezone.now()
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0019_remove_message_read_at"),
    ]

    operations = [
        # 1. Add starred_at field
        migrations.AddField(
            model_name="threadaccess",
            name="starred_at",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="starred at"
            ),
        ),
        # 2. Populate starred_at from has_starred
        migrations.RunPython(populate_starred_at, migrations.RunPython.noop),
        # 3. Remove legacy fields
        migrations.RemoveField(
            model_name="thread",
            name="has_starred",
        ),
        migrations.RemoveField(
            model_name="message",
            name="is_starred",
        ),
    ]
