"""
Tiered storage Celery tasks for blob offloading.

These tasks handle the asynchronous offloading of blob content
from PostgreSQL to object storage.
"""

from datetime import timedelta
from typing import Any, Dict

from django.conf import settings
from django.db import transaction
from django.utils.timezone import now

from botocore.exceptions import BotoCoreError
from celery.utils.log import get_task_logger

from core.enums import BlobStorageLocationChoices
from core.models import Blob
from core.services.tiered_storage import TieredStorageService, sha256_advisory_lock

from messages.celery_app import app as celery_app

logger = get_task_logger(__name__)

# Transient exceptions that should trigger a Celery retry.
# BotoCoreError covers connection-level errors (timeouts, DNS, etc.).
# ClientError covers HTTP API errors (403, 404, etc.) which are usually
# permanent and intentionally not retried.
_TRANSIENT_EXCEPTIONS = (OSError, BotoCoreError)


@celery_app.task(bind=True)
def offload_blobs_task(self) -> Dict[str, Any]:
    """Periodic task: queue eligible blobs for offload to object storage."""
    if not settings.TIERED_STORAGE_OFFLOAD_ENABLED:
        return {"status": "disabled", "queued": 0}

    service = TieredStorageService()
    if not service.enabled:
        return {"status": "disabled", "queued": 0}

    cutoff_date = now() - timedelta(days=settings.TIERED_STORAGE_OFFLOAD_AFTER_DAYS)
    queryset = Blob.objects.filter(
        storage_location=BlobStorageLocationChoices.POSTGRES,
        created_at__lt=cutoff_date,
        size__gte=settings.TIERED_STORAGE_OFFLOAD_MIN_SIZE,
    ).values_list("id", flat=True)

    queued_count = 0
    for blob_id in queryset.iterator(chunk_size=1000):
        offload_single_blob_task.delay(str(blob_id))
        queued_count += 1

    if queued_count > 0:
        logger.info("Queued %d blobs for offloading to object storage", queued_count)

    return {"status": "success", "queued": queued_count}


@celery_app.task(bind=True, max_retries=30)
def offload_single_blob_task(self, blob_id: str) -> Dict[str, Any]:
    """Offload a single blob to object storage atomically.

    Acquires a per-sha256 advisory lock so that concurrent offload,
    cleanup, or re-encrypt of the same content cohort cannot interleave.
    If the lock is held elsewhere, the task is re-queued with backoff.

    Transient S3/network errors are retried with exponential backoff.
    """
    if not settings.TIERED_STORAGE_OFFLOAD_ENABLED:
        return {"status": "disabled", "blob_id": blob_id}

    service = TieredStorageService()
    if not service.enabled:
        return {"status": "disabled", "blob_id": blob_id}

    # sha256 is immutable, so we can safely look it up before taking the lock.
    try:
        sha256 = bytes(Blob.objects.values_list("sha256", flat=True).get(id=blob_id))
    except Blob.DoesNotExist:
        logger.warning("Blob %s not found for offloading", blob_id)
        return {"status": "not_found", "blob_id": blob_id}

    try:
        with transaction.atomic():
            with sha256_advisory_lock(sha256, blocking=False) as got:
                if not got:
                    raise self.retry(countdown=5)

                blob = Blob.objects.select_for_update().get(id=blob_id)

                if blob.storage_location != BlobStorageLocationChoices.POSTGRES:
                    return {"status": "already_offloaded", "blob_id": blob_id}

                if blob.raw_content is None:
                    logger.warning("Blob %s has no raw_content to offload", blob_id)
                    return {"status": "no_content", "blob_id": blob_id}

                key_id = service.upload_blob(blob)

                blob.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
                blob.encryption_key_id = key_id
                blob.raw_content = None
                blob.save(
                    update_fields=[
                        "storage_location",
                        "encryption_key_id",
                        "raw_content",
                    ]
                )

                logger.info(
                    "Offloaded blob %s to object storage (key_id=%d)", blob_id, key_id
                )
                return {"status": "success", "blob_id": blob_id, "key_id": key_id}

    except _TRANSIENT_EXCEPTIONS as e:
        logger.warning("Transient error offloading blob %s: %s", blob_id, e)
        raise self.retry(exc=e, countdown=60 * (2**self.request.retries)) from e
    except Exception as e:  # pylint: disable=broad-except
        logger.exception("Failed to offload blob %s: %s", blob_id, e)
        return {"status": "error", "blob_id": blob_id, "error": str(e)}


@celery_app.task(bind=True, max_retries=30)
def cleanup_orphaned_blob_task(self, sha256_hex: str, key_id: int) -> Dict[str, Any]:
    """Delete a storage object if its ``(sha256, key_id)`` cohort is empty.

    Queued by the ``post_delete`` signal on ``Blob``. Acquires the
    per-sha256 advisory lock so it serializes with concurrent offload
    and re-encrypt of the same content.
    """
    service = TieredStorageService()
    if not service.enabled:
        return {"status": "disabled"}

    sha256 = bytes.fromhex(sha256_hex)

    try:
        with transaction.atomic():
            with sha256_advisory_lock(sha256, blocking=False) as got:
                if not got:
                    raise self.retry(countdown=5)
                deleted = service.delete_if_orphaned(sha256, key_id)
                return {"status": "deleted" if deleted else "still_referenced"}
    except _TRANSIENT_EXCEPTIONS as e:
        raise self.retry(exc=e, countdown=60 * (2**self.request.retries)) from e
