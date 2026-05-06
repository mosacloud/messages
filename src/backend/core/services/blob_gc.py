"""
Blob lifecycle: candidate-set GC, upload reservations, and the periodic
sweep task.

Blobs are no longer owned by a Mailbox/MailDomain via a foreign key —
their lifetime is determined by whichever Message / Attachment /
MessageTemplate references them, plus a short-lived "upload
reservation" for the JMAP-style two-step upload-then-attach flow.
That means CASCADE delete can't clean blobs up; instead:

- Reference sources (Message, Attachment, MessageTemplate) push their
  blob_ids into a Redis set on ``post_delete`` (cheap — O(1) SADD,
  no per-blob celery task even when 100k cascade together).
- A periodic Celery task drains the set, checks each candidate for
  remaining references, and deletes orphans (with inline S3 cleanup
  under the per-sha advisory lock — same pattern as
  ``offload_blobs_task``).
- A weekly "full" run walks every Blob row to catch anything that
  fell through (Redis outage, signal that didn't fire, etc.).

The upload reservation gives the API upload-then-attach flow a window
during which a freshly-uploaded blob is "owned" by a mailbox in Redis
but not yet referenced by any DB row. GC honors the reservation;
re-uploading the same content on the JMAP path doesn't race.
"""

# pylint: disable=import-outside-toplevel,broad-exception-caught

from time import monotonic
from typing import Any, Dict, Iterable, Iterator, Optional
from uuid import UUID

from django.conf import settings
from django.db import transaction

from celery.utils.log import get_task_logger
from redis.exceptions import RedisError

from messages.celery_app import app as celery_app

logger = get_task_logger(__name__)


# Redis set holding blob ids that may have become orphans. Reference-source
# post_delete signals SADD here; the GC task SPOPs in batches.
_GC_CANDIDATES_KEY = "messages_blobs:gc_candidates"

# Per-blob upload reservation. Key: ``messages_blobs:upload:{blob_id}``,
# value: mailbox_id. TTL caps the window during which a blob can sit in
# the bucket without any DB reference.
_UPLOAD_RESERVATION_PREFIX = "messages_blobs:upload:"
_UPLOAD_RESERVATION_TTL = 3600  # 1h — sane window for compose-then-send

# How many candidates to process per fast-mode tick. Conservative; the
# task is wall-clock-bounded so the upper bound is the larger of these
# two before the deadline fires.
_GC_FAST_BATCH_SIZE = 1000

# Wall-clock budget for one tick. Hourly schedule with a 55-minute cap
# so the task always returns before the next beat tick could overlap.
# Mirrors ``offload_blobs_task``'s pattern.
_GC_MAX_RUN_SECONDS = 55 * 60


# --------------------------------------------------------------------
# Backend probe (mirrors ``coalescer.py``)
# --------------------------------------------------------------------
#
# The candidate set and upload-reservation primitives need atomic
# multi-process semantics that Django's pluggable cache layer can't
# provide reliably. We therefore only support ``django_redis`` here;
# any other backend (Dummy, LocMem, FileBased, …) skips with a warning.
# Blob lifetime stays correct: the periodic ``--full`` sweep is the
# safety net for environments without Redis.


def _is_redis_backend() -> bool:
    backend = settings.CACHES.get("default", {}).get("BACKEND", "")
    return "django_redis" in backend


def _redis_client():
    from django_redis import get_redis_connection

    return get_redis_connection("default")


# --------------------------------------------------------------------
# Candidate set
# --------------------------------------------------------------------


def schedule_for_gc(blob_id) -> None:
    """Push a blob id into the GC candidate set.

    Called from ``post_delete`` on Message / Attachment / MessageTemplate
    when they may have been the last reference to a Blob. The GC task
    (later) re-checks the reference graph; producers don't need to be
    accurate, just safe.

    A Redis outage drops the id; the periodic ``--full`` sweep is the
    safety net for that case.
    """
    if blob_id is None:
        return
    value = str(blob_id)
    if not _is_redis_backend():
        logger.warning(
            "Blob GC candidate set requires Redis: id %s dropped. "
            "Configure django_redis or rely on `--full` periodic sweeps.",
            value,
        )
        return
    try:
        _redis_client().sadd(_GC_CANDIDATES_KEY, value)
    except RedisError as exc:
        logger.error(
            "Redis unavailable while enqueuing blob %s for GC (%s: %s); "
            "id dropped — `--full` sweep will catch it eventually",
            value,
            type(exc).__name__,
            exc,
        )
    except Exception:
        logger.exception("Failed to enqueue %s for GC", value)


def _drain_candidates(batch_size: int) -> list[str]:
    """Pop up to ``batch_size`` ids from the candidate set."""
    if not _is_redis_backend():
        return []
    try:
        popped = _redis_client().spop(_GC_CANDIDATES_KEY, count=batch_size)
        return [
            bid.decode() if isinstance(bid, bytes) else str(bid)
            for bid in (popped or [])
        ]
    except RedisError as exc:
        logger.error(
            "Redis unavailable while draining blob GC set (%s: %s); "
            "skipping this tick",
            type(exc).__name__,
            exc,
        )
        return []
    except Exception:
        logger.exception("Failed to drain blob GC candidate set")
        return []


# --------------------------------------------------------------------
# Upload reservations
# --------------------------------------------------------------------


def reserve_upload(blob_id, mailbox_id, ttl: int = _UPLOAD_RESERVATION_TTL) -> None:
    """Mark ``blob_id`` as reserved by ``mailbox_id`` for ``ttl`` seconds.

    Called by the upload endpoint right after the Blob row is created
    (or fetched on a dedup hit). The reservation:

    - Tells the GC sweep to skip this blob even if it has no DB
      references yet (the user hasn't completed the attach step).
    - Stands in for the old ``Blob.mailbox`` FK as a provenance hint
      for the attach-by-id authz check: the mailbox that uploaded a
      blob is the only one allowed to attach it before any reference
      exists.

    Released by ``release_upload`` once an Attachment / Message /
    MessageTemplate FKs the blob — at which point the reference-graph
    authz takes over. Auto-expires after ``ttl`` seconds if the user
    abandons the upload; the next GC sweep cleans up.
    """
    if blob_id is None or mailbox_id is None:
        return
    key = _UPLOAD_RESERVATION_PREFIX + str(blob_id)
    if not _is_redis_backend():
        logger.warning(
            "Blob upload reservation requires Redis: blob %s "
            "won't be protected during the upload-then-attach window.",
            blob_id,
        )
        return
    try:
        _redis_client().setex(key, ttl, str(mailbox_id))
    except RedisError as exc:
        logger.error(
            "Redis unavailable while reserving blob %s for mailbox %s "
            "(%s: %s); blob is unprotected for the upload window",
            blob_id,
            mailbox_id,
            type(exc).__name__,
            exc,
        )
    except Exception:
        logger.exception(
            "Failed to reserve blob %s for mailbox %s", blob_id, mailbox_id
        )


def release_upload(blob_id) -> None:
    """Drop the reservation for ``blob_id`` (no-op if none exists).

    Call after an Attachment / Message / MessageTemplate has been
    created referencing the blob — the reference-graph authz now
    covers it. The TTL would clean up regardless; this just shortens
    the unnecessary-protection window.
    """
    if blob_id is None:
        return
    if not _is_redis_backend():
        return
    key = _UPLOAD_RESERVATION_PREFIX + str(blob_id)
    try:
        _redis_client().delete(key)
    except RedisError:
        # Best-effort. If the delete fails the TTL still cleans up.
        pass
    except Exception:
        logger.exception("Failed to release reservation for %s", blob_id)


def get_upload_reservation(blob_id) -> Optional[str]:
    """Return the reserving mailbox_id (as str) or ``None``."""
    if blob_id is None:
        return None
    if not _is_redis_backend():
        return None
    key = _UPLOAD_RESERVATION_PREFIX + str(blob_id)
    try:
        value = _redis_client().get(key)
        if value is None:
            return None
        return value.decode() if isinstance(value, bytes) else str(value)
    except RedisError:
        # If we can't tell, fail closed: behave as if reserved so the GC
        # doesn't delete a blob that may legitimately be in the upload
        # window. Authz callers also fail closed via the same path.
        return ""
    except Exception:
        logger.exception("Failed to read reservation for %s", blob_id)
        return ""


def has_upload_reservation(blob_id) -> bool:
    """Cheap boolean variant of :func:`get_upload_reservation`."""
    return get_upload_reservation(blob_id) is not None


# --------------------------------------------------------------------
# GC task
# --------------------------------------------------------------------


def _all_blob_ids_iterator() -> Iterator[str]:
    """Yield every Blob.id as a string. Used by ``--full`` mode."""
    from core.models import Blob

    qs = Blob.objects.values_list("id", flat=True).order_by()
    for blob_id in qs.iterator(chunk_size=1000):
        yield str(blob_id)


def _gc_one_blob(blob_id_str: str, service) -> str:
    """Process a single GC candidate.

    Returns one of ``"deleted"``, ``"skipped_reserved"``,
    ``"skipped_referenced"``, ``"not_found"``, ``"error"``.
    """
    from core.enums import BlobStorageLocationChoices
    from core.models import Blob
    from core.services.tiered_storage import sha256_advisory_lock

    # Reservation check is a cheap Redis lookup; skip the lock if held.
    if has_upload_reservation(blob_id_str):
        return "skipped_reserved"

    try:
        blob_uuid = UUID(blob_id_str)
    except (TypeError, ValueError):
        logger.warning("GC: dropping non-UUID candidate %r", blob_id_str)
        return "error"

    try:
        blob = Blob.objects.only(
            "id", "sha256", "encryption_key_id", "storage_location"
        ).get(id=blob_uuid)
    except Blob.DoesNotExist:
        return "not_found"

    # Cheap pre-lock reference check.
    if Blob.objects.is_referenced(blob_uuid):
        return "skipped_referenced"

    sha = bytes(blob.sha256)
    key_id = blob.encryption_key_id
    location = blob.storage_location

    try:
        with transaction.atomic(), sha256_advisory_lock(sha):
            # Re-check inside the lock: a Message / Attachment may have
            # been created between the cheap check and this point.
            if has_upload_reservation(blob_id_str):
                return "skipped_reserved"
            if Blob.objects.is_referenced(blob_uuid):
                return "skipped_referenced"
            # Refresh in case storage_location flipped (offload could be
            # in flight if our candidate sat in Redis a while).
            blob.refresh_from_db()
            location = blob.storage_location
            blob.delete()
            if location == BlobStorageLocationChoices.OBJECT_STORAGE and service.enabled:
                # Best-effort S3 cleanup. ``delete_if_orphaned`` re-checks
                # the row count; for an OBJECT_STORAGE blob that we just
                # deleted, it'll see zero refs and remove the bucket
                # object — unless another row is still pointing at the
                # same path (different Blob row, but same sha + key_id).
                service.delete_if_orphaned(sha, key_id)
        return "deleted"
    except Exception:
        logger.exception("GC failed for blob %s", blob_id_str)
        return "error"


@celery_app.task
def gc_orphan_blobs_task(mode: str = "fast") -> Dict[str, Any]:
    """Periodic: GC blobs whose last reference was deleted.

    Modes:

    - ``"fast"`` (default, hooked to celery beat) — drain ids from the
      Redis candidate set and process each. Catches the common case
      where a Message / Attachment / MessageTemplate post_delete has
      pushed the blob_id.
    - ``"full"`` — walk every Blob row. Use as a periodic safety-net
      sweep (weekly cron via ``manage.py shell`` or a separate beat
      entry) to catch anything dropped by a Redis outage or a missing
      signal.

    Both modes:

    - Skip blobs with an active upload reservation (JMAP 2-step flow).
    - Re-check the reference graph inside a per-sha advisory lock to
      avoid racing the offload / re-store / dedup paths.
    - Do S3 cleanup inline (no per-blob celery fan-out) when the
      deleted row was at OBJECT_STORAGE.
    """
    from core.services.tiered_storage import TieredStorageService

    if mode == "fast":
        candidate_iter: Iterable[str] = _drain_candidates(_GC_FAST_BATCH_SIZE)
    elif mode == "full":
        candidate_iter = _all_blob_ids_iterator()
    else:
        raise ValueError(f"unknown mode {mode!r} (use 'fast' or 'full')")

    service = TieredStorageService()
    deadline = monotonic() + _GC_MAX_RUN_SECONDS

    counts = {
        "mode": mode,
        "deleted": 0,
        "skipped_reserved": 0,
        "skipped_referenced": 0,
        "not_found": 0,
        "errors": 0,
        "stop_reason": "exhausted",
    }

    for blob_id_str in candidate_iter:
        if monotonic() >= deadline:
            counts["stop_reason"] = "deadline"
            break
        result = _gc_one_blob(blob_id_str, service)
        if result == "deleted":
            counts["deleted"] += 1
        elif result == "skipped_reserved":
            counts["skipped_reserved"] += 1
        elif result == "skipped_referenced":
            counts["skipped_referenced"] += 1
        elif result == "not_found":
            counts["not_found"] += 1
        else:
            counts["errors"] += 1

    logger.info(
        "gc_orphan_blobs_task[%s]: deleted=%d skipped_reserved=%d "
        "skipped_referenced=%d not_found=%d errors=%d stop=%s",
        counts["mode"],
        counts["deleted"],
        counts["skipped_reserved"],
        counts["skipped_referenced"],
        counts["not_found"],
        counts["errors"],
        counts["stop_reason"],
    )
    return counts
