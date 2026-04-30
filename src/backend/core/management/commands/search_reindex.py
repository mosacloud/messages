"""Management command to reindex content in OpenSearch."""

import uuid
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core import models
from core.services.search import create_index_if_not_exists, delete_index
from core.services.search.tasks import (
    _reindex_all_base,
    _reindex_mailbox_base,
    reindex_all,
    reindex_mailbox_task,
    reindex_thread_task,
)


class Command(BaseCommand):
    """Reindex content in OpenSearch."""

    help = "Reindex content in OpenSearch"

    def add_arguments(self, parser):
        """Add command arguments."""
        scope_group = parser.add_mutually_exclusive_group(required=True)
        scope_group.add_argument(
            "--all",
            action="store_true",
            help="Reindex all threads and messages",
        )
        scope_group.add_argument(
            "--thread",
            type=str,
            help="Reindex a specific thread by ID",
        )
        scope_group.add_argument(
            "--mailbox",
            type=str,
            help="Reindex all threads and messages in a specific mailbox by ID",
        )

        parser.add_argument(
            "--from-date",
            type=str,
            help=(
                "Only reindex threads with updated_at >= this date. "
                "ISO-8601, date or datetime (e.g. 2026-04-01 or "
                "2026-04-01T14:30). Compatible with --all and --mailbox."
            ),
        )

        parser.add_argument(
            "--async",
            action="store_true",
            help="Run task asynchronously",
            dest="async_mode",
        )

        parser.add_argument(
            "--recreate-index",
            action="store_true",
            help="Recreate the index before reindexing",
        )

    def handle(self, *args, **options):
        """Execute the command."""
        from_date = self._parse_from_date(
            options.get("from_date"),
            scope_thread=options["thread"],
            scope_all=options["all"],
            scope_mailbox=options["mailbox"],
        )

        if options["recreate_index"]:
            self.stdout.write("Deleting and recreating OpenSearch index...")
            delete_index()

        self.stdout.write("Ensuring OpenSearch index exists...")
        create_index_if_not_exists()

        if options["all"]:
            return self._reindex_all(options["async_mode"], from_date)
        if options["thread"]:
            return self._reindex_thread(options["thread"], options["async_mode"])
        return self._reindex_mailbox(
            options["mailbox"], options["async_mode"], from_date
        )

    def _parse_from_date(self, raw, *, scope_thread, scope_all, scope_mailbox):
        """Validate and parse the user-supplied ISO date/datetime string.

        ``--from-date`` only makes sense alongside a queryset-based scope
        (``--all`` / ``--mailbox``); on ``--thread`` it would be ignored, so
        we reject it loudly rather than silently.
        """
        if not raw:
            return None
        if scope_thread:
            raise CommandError("--from-date is incompatible with --thread.")
        if not (scope_all or scope_mailbox):
            raise CommandError("--from-date requires either --all or --mailbox.")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise CommandError(
                f"Invalid --from-date {raw!r}: expected ISO-8601 (YYYY-MM-DD "
                "or YYYY-MM-DDTHH:MM[:SS])."
            ) from exc
        # Naive input (no offset / "YYYY-MM-DD") is interpreted in the active
        # timezone — comparing against Thread.updated_at otherwise raises a
        # RuntimeWarning under USE_TZ=True.
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed)
        return parsed

    def _reindex_all(self, async_mode, from_date):
        """Reindex all threads and messages."""
        self.stdout.write("Reindexing all threads and messages...")

        if async_mode:
            task = reindex_all.delay(
                from_date_iso=from_date.isoformat() if from_date else None
            )
            self.stdout.write(
                self.style.SUCCESS(f"Reindexing task scheduled (ID: {task.id})")
            )
            return None

        def update_progress(current, total, success_count, failure_count):
            """Update progress in the console."""
            self.stdout.write(
                f"Progress: {current}/{total} threads processed "
                f"({success_count} succeeded, {failure_count} failed)"
            )

        result = _reindex_all_base(update_progress, from_date=from_date)
        self.stdout.write(
            self.style.SUCCESS(
                f"Reindexing completed: {result.get('success_count', 0)} succeeded, "
                f"{result.get('failure_count', 0)} failed"
            )
        )
        if result.get("failure_count", 0) > 0:
            return 1
        return None

    def _reindex_thread(self, thread_id, async_mode):
        """Reindex a specific thread and its messages."""
        try:
            thread_uuid = uuid.UUID(thread_id)
            models.Thread.objects.get(id=thread_uuid)
        except ValueError as e:
            raise CommandError(f"Invalid thread ID: {thread_id}") from e
        except models.Thread.DoesNotExist as e:
            raise CommandError(f"Thread with ID {thread_id} does not exist") from e

        self.stdout.write(f"Reindexing thread {thread_id}...")

        if async_mode:
            task = reindex_thread_task.delay(str(thread_uuid))
            self.stdout.write(
                self.style.SUCCESS(f"Reindexing task scheduled (ID: {task.id})")
            )
            return None

        result = reindex_thread_task(str(thread_uuid))  # pylint: disable=no-value-for-parameter
        if result.get("success", False):
            self.stdout.write(
                self.style.SUCCESS(f"Thread {thread_id} indexed successfully")
            )
            return None

        self.stdout.write(
            self.style.ERROR(
                f"Failed to index thread {thread_id}: {result.get('error', '')}"
            )
        )
        return 1

    def _reindex_mailbox(self, mailbox_id, async_mode, from_date):
        """Reindex all threads and messages in a specific mailbox."""
        try:
            mailbox_uuid = uuid.UUID(mailbox_id)
            mailbox = models.Mailbox.objects.get(id=mailbox_uuid)
        except ValueError as e:
            raise CommandError(f"Invalid mailbox ID: {mailbox_id}") from e
        except models.Mailbox.DoesNotExist as e:
            raise CommandError(f"Mailbox with ID {mailbox_id} does not exist") from e

        self.stdout.write(f"Reindexing threads for mailbox {mailbox}...")

        if async_mode:
            task = reindex_mailbox_task.delay(
                str(mailbox_uuid),
                from_date_iso=from_date.isoformat() if from_date else None,
            )
            self.stdout.write(
                self.style.SUCCESS(f"Reindexing task scheduled (ID: {task.id})")
            )
            return None

        def update_progress(current, total, success_count, failure_count):
            """Update progress in the console."""
            self.stdout.write(
                f"Progress: {current}/{total} threads processed "
                f"({success_count} succeeded, {failure_count} failed)"
            )

        result = _reindex_mailbox_base(
            str(mailbox_uuid), update_progress, from_date=from_date
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Reindexing completed: {result.get('success_count', 0)} succeeded, "
                f"{result.get('failure_count', 0)} failed"
            )
        )
        if result.get("failure_count", 0) > 0:
            return 1
        return None
