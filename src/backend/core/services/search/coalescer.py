"""Coalescing buffers for OpenSearch thread reindex and delete enqueues.

Signal handlers push thread IDs into Redis sets instead of scheduling a
Celery task per ``save()`` / ``delete()``. A periodic task
(``process_pending_reindex_task``) drains the buffers every
``SEARCH_REINDEX_TASKS_INTERVAL`` seconds, deduplicates IDs that appear in
both the reindex and the delete set (the delete wins), chunks each set by
``DEFAULT_FLUSH_BATCH_SIZE`` to keep each Celery payload bounded, and
enqueues ``bulk_delete_threads_task`` / ``bulk_reindex_threads_task`` per
chunk so the whole backlog clears in a single flush cycle.

Two sets are tracked:

* ``search:pending_reindex_threads`` — thread IDs that need their
  OpenSearch documents rebuilt from the DB. ``reindex_bulk_threads`` also
  purges orphan message documents for each batched thread, so a message
  ``post_delete`` schedules a thread reindex rather than a dedicated
  per-message delete.
* ``search:pending_delete_threads`` — thread IDs whose documents (thread +
  children) must be removed from the index.

The buffer picks its storage based on ``CACHES['default']['BACKEND']``:

* **Redis** (``django_redis``): uses a native Redis set via ``SADD`` and
  drains with ``SPOP count=N`` (atomic since Redis 3.2). Dedup and drain are
  race-free across workers and hosts. This is the production path.
* **Fallback** (LocMem, FileBasedCache, …): stores a serialized Python
  ``set`` under a single Django cache key. Read-modify-write is not atomic,
  so concurrent writers may drop IDs. Reindex is idempotent and fires on
  every save, so the index stays eventually consistent. This path is meant
  for tests (LocMem) and single-process dev deployments — multi-worker prod
  should use Redis.
"""

import logging

from django.conf import settings
from django.core.cache import cache

from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

PENDING_REINDEX_KEY = "search:pending_reindex_threads"
PENDING_DELETE_KEY = "search:pending_delete_threads"

# Max flush batch size to limit the celery payloads
DEFAULT_FLUSH_BATCH_SIZE = 10_000

# Max number of bulk tasks a single flush cycle can enqueue, shared across
# delete and reindex handoffs.
DEFAULT_FLUSH_MAX_BATCHES = 10


def _is_redis_backend() -> bool:
    """Return True when the default cache is backed by django_redis."""
    backend = settings.CACHES.get("default", {}).get("BACKEND", "")
    return "django_redis" in backend


def _is_dummy_backend() -> bool:
    """Return True when the default cache is Django's DummyCache."""
    backend = settings.CACHES.get("default", {}).get("BACKEND", "")
    return "dummy" in backend.lower()


def _redis_client():
    # pylint: disable-next=import-outside-toplevel
    from django_redis import get_redis_connection

    return get_redis_connection("default")


def _enqueue(key: str, value) -> None:
    """Add ``value`` to the pending set at ``key``."""
    if value is None:
        return

    try:
        if _is_redis_backend():
            _redis_client().sadd(key, str(value))
        else:
            if _is_dummy_backend():
                logger.warning(
                    "OpenSearch reindex coalescer is using DummyCache: "
                    "enqueued thread IDs are dropped. Use Redis or LocMemCache, "
                    "or disable OPENSEARCH_INDEX_THREADS."
                )
                return
            ids = set(cache.get(key) or ())
            ids.add(str(value))
            cache.set(key, ids, timeout=None)
    except RedisError as exc:
        logger.error(
            "Redis unavailable while enqueuing thread %s into %s (%s: %s); "
            "ID dropped — index will diverge until another signal fires "
            "on this thread",
            value,
            key,
            type(exc).__name__,
            exc,
        )
    # pylint: disable=broad-exception-caught
    except Exception:
        logger.exception("Failed to enqueue %s into %s", value, key)


def enqueue_thread_reindex(thread_id) -> None:
    """Add ``thread_id`` to the pending reindex set."""
    _enqueue(PENDING_REINDEX_KEY, thread_id)


def enqueue_thread_delete(thread_id) -> None:
    """Add ``thread_id`` to the pending delete set."""
    _enqueue(PENDING_DELETE_KEY, thread_id)


def _drain_batch(key: str, is_redis_cache: bool, batch_size: int) -> list | None:
    """Drain up to ``batch_size`` IDs from the pending set at ``key``.

    Returns the drained IDs as a list (possibly empty when the set is empty)
    or ``None`` if the drain itself failed — signalling the caller to stop.
    """
    try:
        if is_redis_cache:
            drained = _redis_client().spop(key, count=batch_size)
            return [
                tid.decode() if isinstance(tid, bytes) else str(tid)
                for tid in (drained or [])
            ]
        ids = set(cache.get(key) or ())
        if not ids:
            return []
        thread_ids = list(ids)[:batch_size]
        remaining = ids - set(thread_ids)
        if remaining:
            cache.set(key, remaining, timeout=None)
        else:
            cache.delete(key)
        return thread_ids
    except RedisError as exc:
        logger.error(
            "Redis unavailable while draining pending set %s (%s: %s); "
            "skipping this flush cycle — IDs already in the set are preserved",
            key,
            type(exc).__name__,
            exc,
        )
        return None
    # pylint: disable=broad-exception-caught
    except Exception:
        logger.exception("Failed to drain pending set %s", key)
        return None


def _restore_batch(key: str, is_redis_cache: bool, thread_ids: list) -> None:
    """Push ``thread_ids`` back into the pending set at ``key``."""
    try:
        if is_redis_cache:
            _redis_client().sadd(key, *thread_ids)
        else:
            current = set(cache.get(key) or ())
            current.update(thread_ids)
            cache.set(key, current, timeout=None)
    except RedisError as exc:
        logger.error(
            "Redis unavailable while restoring %d drained IDs to %s (%s: %s); "
            "these entries will stay out of sync until another signal fires",
            len(thread_ids),
            key,
            type(exc).__name__,
            exc,
        )
    # pylint: disable=broad-exception-caught
    except Exception:
        logger.exception(
            "Failed to restore %d drained IDs to %s; "
            "these entries will stay out of sync until another signal fires",
            len(thread_ids),
            key,
        )


def process_pending_reindex(
    batch_size: int = DEFAULT_FLUSH_BATCH_SIZE,
    max_batches: int = DEFAULT_FLUSH_MAX_BATCHES,
) -> dict:
    """Drain both pending sets and enqueue bulk delete/reindex tasks.

    Each iteration atomically drains up to ``batch_size`` IDs from one of the
    pending sets. Delete IDs are drained first and handed to
    ``bulk_delete_threads_task``; reindex IDs are handed to
    ``bulk_reindex_threads_task``. Before enqueuing a reindex batch, any ID
    also present in the drained delete set is filtered out so a thread that
    is about to be removed from the index is never reindexed.

    The loop stops when both sets are empty, a drain or handoff fails, or
    ``max_batches`` tasks have been enqueued in total (shared across delete
    and reindex so a long backlog of one type does not starve the other).
    Leftover IDs stay in their set and drain on the next beat tick.

    The drain removes IDs from each buffer *before* we know whether the
    broker accepted the task. If ``delay()`` raises (broker down,
    serialization error, …), the failing batch is pushed back into its own
    set and the loop stops so we don't hammer a degraded broker. Batches
    already accepted stay accepted. Without this rollback, a transient
    broker outage would silently desync the index from the database until
    another signal fired on those threads.

    Returns a dict ``{"deleted": int, "reindexed": int}`` with the count of
    IDs successfully handed off to each task type.
    """
    is_redis_cache = _is_redis_backend()

    # pylint: disable-next=import-outside-toplevel
    from core.services.search.tasks import (
        bulk_delete_threads_task,
        bulk_reindex_threads_task,
    )

    deleted_total = 0
    reindexed_total = 0
    drained_delete_ids: set[str] = set()
    remaining_budget = max_batches

    # Drain and handoff delete IDs first so reindex dedup below is accurate.
    while remaining_budget > 0:
        thread_ids = _drain_batch(PENDING_DELETE_KEY, is_redis_cache, batch_size)
        if not thread_ids:
            break

        try:
            bulk_delete_threads_task.delay(thread_ids)
        # pylint: disable=broad-exception-caught
        except Exception:
            logger.exception(
                "Failed to enqueue bulk_delete_threads_task for %d drained threads; "
                "returning IDs to the pending set for retry",
                len(thread_ids),
            )
            _restore_batch(PENDING_DELETE_KEY, is_redis_cache, thread_ids)
            return {"deleted": deleted_total, "reindexed": reindexed_total}

        deleted_total += len(thread_ids)
        drained_delete_ids.update(thread_ids)
        remaining_budget -= 1

    while remaining_budget > 0:
        thread_ids = _drain_batch(PENDING_REINDEX_KEY, is_redis_cache, batch_size)
        if not thread_ids:
            break

        # Drop IDs already scheduled for deletion in this cycle. The delete
        # task will remove those documents; reindexing them would be wasted
        # work and, if the delete runs first, recreate documents we just
        # dropped.
        if drained_delete_ids:
            filtered = [tid for tid in thread_ids if tid not in drained_delete_ids]
        else:
            filtered = thread_ids

        if not filtered:
            remaining_budget -= 1
            continue

        try:
            bulk_reindex_threads_task.delay(filtered)
        # pylint: disable=broad-exception-caught
        except Exception:
            logger.exception(
                "Failed to enqueue bulk_reindex_threads_task for %d drained threads; "
                "returning IDs to the pending set for retry",
                len(filtered),
            )
            _restore_batch(PENDING_REINDEX_KEY, is_redis_cache, filtered)
            return {"deleted": deleted_total, "reindexed": reindexed_total}

        reindexed_total += len(filtered)
        remaining_budget -= 1

    return {"deleted": deleted_total, "reindexed": reindexed_total}
