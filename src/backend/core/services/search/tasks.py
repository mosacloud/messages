"""Search and indexing tasks."""

# pylint: disable=unused-argument, broad-exception-raised, broad-exception-caught

from django.conf import settings

from celery.utils.log import get_task_logger
from opensearchpy.exceptions import ConnectionError as OpenSearchConnectionError
from opensearchpy.exceptions import TransportError

from core import models
from core.services.search import (
    create_index_if_not_exists,
    delete_index,
    index_message,
    index_thread,
    update_thread_mailbox_flags,
)
from core.services.search import (
    reindex_all as _reindex_all_impl,
)
from core.services.search import (
    reindex_mailbox as _reindex_mailbox_impl,
)
from core.services.search.coalescer import process_pending_reindex
from core.services.search.index import (
    get_opensearch_client,
    reindex_bulk_threads,
)
from core.services.search.mapping import MESSAGE_INDEX

from messages.celery_app import app as celery_app

logger = get_task_logger(__name__)

# Retry only on transient OpenSearch connectivity failures.
# ``ConnectionError`` covers socket-level failures and timeouts.
# ``TransportError`` covers HTTP-level failures: ``index.py`` filters and
# only re-raises retryable status codes (5xx, 429), so any TransportError
# that reaches Celery is by construction safe to retry. 4xx errors stay
# swallowed inside the index module and never bubble up here.
_RETRYABLE_EXCEPTIONS = (OpenSearchConnectionError, TransportError)


def _reindex_all_base(update_progress=None):
    """Base function for reindexing all threads and messages.

    Delegates to the bulk ``reindex_all`` implementation in the search index
    module.

    Args:
        update_progress: Optional callback function to update progress
    """
    if not settings.OPENSEARCH_INDEX_THREADS:
        logger.info("OpenSearch thread indexing is disabled.")
        return {"success": False, "reason": "disabled"}

    result = _reindex_all_impl(progress_callback=update_progress)

    return {
        "success": True,
        "total": result["total"],
        "success_count": result["indexed_threads"],
        "failure_count": result["failure_count"],
    }


@celery_app.task(bind=True)
def reindex_all(self):
    """Celery task wrapper for reindexing all threads and messages."""

    def update_progress(current, total, success_count, failure_count):
        """Update task progress."""
        self.update_state(
            state="PROGRESS",
            meta={
                "current": current,
                "total": total,
                "success_count": success_count,
                "failure_count": failure_count,
            },
        )

    return _reindex_all_base(update_progress)


@celery_app.task(bind=True)
def reindex_thread_task(self, thread_id):
    """Reindex a specific thread and all its messages."""
    if not settings.OPENSEARCH_INDEX_THREADS:
        logger.info("OpenSearch thread indexing is disabled.")
        return {"success": False, "reason": "disabled"}

    try:
        # Ensure index exists first
        create_index_if_not_exists()

        # Get the thread
        thread = models.Thread.objects.get(id=thread_id)

        # Index the thread
        success = index_thread(thread)

        return {
            "thread_id": str(thread_id),
            "success": success,
        }
    except models.Thread.DoesNotExist:
        logger.error("Thread %s does not exist", thread_id)
        return {
            "thread_id": str(thread_id),
            "success": False,
            "error": f"Thread {thread_id} does not exist",
        }
    except Exception as e:
        logger.exception("Error in reindex_thread_task for thread %s: %s", thread_id, e)
        raise


@celery_app.task(
    bind=True,
    autoretry_for=_RETRYABLE_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=5,
)
def update_threads_mailbox_flags_task(self, thread_ids):
    """Update mailbox-scoped flags (unread_mailboxes, starred_mailboxes) in OpenSearch."""
    if not settings.OPENSEARCH_INDEX_THREADS:
        logger.info("OpenSearch thread indexing is disabled.")
        return {"success": False, "reason": "disabled"}

    create_index_if_not_exists()

    results = []
    for thread_id in thread_ids:
        try:
            thread = models.Thread.objects.get(id=thread_id)
            success = update_thread_mailbox_flags(thread)
            results.append({"thread_id": thread_id, "success": success})
        except models.Thread.DoesNotExist:
            logger.error("Thread %s does not exist", thread_id)
            results.append({"thread_id": thread_id, "success": False})

    return {"success": True, "results": results}


def _reindex_mailbox_base(mailbox_id, update_progress=None):
    """Base function for reindexing all threads in a mailbox.

    Delegates to the bulk ``reindex_mailbox`` implementation in the search
    index module.

    Args:
        mailbox_id: The mailbox ID to reindex.
        update_progress: Optional callback function to update progress.
    """
    if not settings.OPENSEARCH_INDEX_THREADS:
        logger.info("OpenSearch thread indexing is disabled.")
        return {"success": False, "reason": "disabled"}

    result = _reindex_mailbox_impl(mailbox_id, progress_callback=update_progress)

    if result.get("status") == "error":
        return {"success": False, **result}

    return {
        "mailbox_id": str(mailbox_id),
        "success": True,
        "total": result["total"],
        "success_count": result["indexed_threads"],
        "failure_count": result["failure_count"],
    }


@celery_app.task(bind=True)
def reindex_mailbox_task(self, mailbox_id):
    """Celery task wrapper for reindexing all threads in a mailbox."""

    def update_progress(current, total, success_count, failure_count):
        """Update task progress."""
        self.update_state(
            state="PROGRESS",
            meta={
                "current": current,
                "total": total,
                "success_count": success_count,
                "failure_count": failure_count,
            },
        )

    return _reindex_mailbox_base(mailbox_id, update_progress)


@celery_app.task(bind=True)
def index_message_task(self, message_id):
    """Index a single message."""
    if not settings.OPENSEARCH_INDEX_THREADS:
        logger.info("OpenSearch message indexing is disabled.")
        return {"success": False, "reason": "disabled"}

    try:
        # Ensure index exists first
        create_index_if_not_exists()

        # Get the message
        message = (
            models.Message.objects.select_related("thread", "sender")
            .prefetch_related("recipients__contact")
            .get(id=message_id)
        )

        # Index the message
        success = index_message(message)

        return {
            "message_id": str(message_id),
            "thread_id": str(message.thread_id),
            "success": success,
        }
    except models.Message.DoesNotExist:
        logger.error("Message %s does not exist", message_id)
        return {
            "message_id": str(message_id),
            "success": False,
            "error": f"Message {message_id} does not exist",
        }
    except Exception as e:
        logger.exception(
            "Error in index_message_task for message %s: %s", message_id, e
        )
        raise


@celery_app.task(
    bind=True,
    autoretry_for=_RETRYABLE_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=5,
)
def bulk_reindex_threads_task(self, thread_ids):
    """Reindex a list of threads and all their messages in one bulk pass.

    Enqueued at the end of a scoped ``ThreadReindexDeferrer.defer()`` block
    (bulk import flows) and by the periodic ``process_pending_reindex_task``
    that drains the coalescing buffers used by non-import signals. Replaces
    the per-row ``index_message_task`` / ``reindex_thread_task`` /
    ``update_threads_mailbox_flags_task`` calls that post_save signals would
    otherwise trigger.
    """
    if not settings.OPENSEARCH_INDEX_THREADS:
        logger.info("OpenSearch thread indexing is disabled.")
        return {"success": False, "reason": "disabled"}

    if not thread_ids:
        return {"success": True, "total": 0, "success_count": 0, "failure_count": 0}

    create_index_if_not_exists()

    result = reindex_bulk_threads(models.Thread.objects.filter(id__in=thread_ids))

    return {
        "success": True,
        "total": result["total"],
        "success_count": result["indexed_threads"],
        "failure_count": result["failure_count"],
    }


@celery_app.task(
    bind=True,
    autoretry_for=_RETRYABLE_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=5,
)
def bulk_delete_threads_task(self, thread_ids):
    """Remove thread documents (and their child messages) from OpenSearch.

    A single ``delete_by_query`` with ``terms: {thread_id: [...]}`` sweeps
    both the thread parent documents and all their message children in one
    request. Enqueued by ``process_pending_reindex_task`` after draining the
    ``search:pending_delete_threads`` set.
    """
    if not settings.OPENSEARCH_INDEX_THREADS:
        return {"success": False, "reason": "disabled"}

    if not thread_ids:
        return {"success": True, "deleted_threads": 0}

    es = get_opensearch_client()

    str_ids = [str(tid) for tid in thread_ids]

    # pylint: disable=unexpected-keyword-arg
    es.delete_by_query(
        index=MESSAGE_INDEX,
        body={"query": {"terms": {"thread_id": str_ids}}},
        ignore=[404, 409],
        conflicts="proceed",
    )

    return {"success": True, "deleted_threads": len(str_ids)}


@celery_app.task(bind=True)
def reset_search_index(self):
    """Delete and recreate the OpenSearch index."""

    delete_index()
    create_index_if_not_exists()
    return {"success": True}


@celery_app.task(bind=True)
def process_pending_reindex_task(self):
    """Drain the coalescing buffers and enqueue bulk delete/reindex tasks.

    Scheduled every ``SEARCH_REINDEX_TASKS_INTERVAL`` seconds by Celery Beat.
    Consumes thread IDs accumulated by ``enqueue_thread_reindex`` /
    ``enqueue_thread_delete`` from signal handlers firing outside any
    ``ThreadReindexDeferrer.defer()`` scope and hands them off to
    ``bulk_reindex_threads_task`` / ``bulk_delete_threads_task``.
    """
    if not settings.OPENSEARCH_INDEX_THREADS:
        return {"success": False, "reason": "disabled", "deleted": 0, "reindexed": 0}

    result = process_pending_reindex()
    return {"success": True, **result}
