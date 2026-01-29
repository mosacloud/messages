"""
Tiered storage Celery tasks for blob offloading.

These tasks handle the asynchronous offloading of blob content
from PostgreSQL to object storage.
"""

from datetime import timedelta
from typing import Any, Dict

from django.conf import settings
from django.db import OperationalError, transaction
from django.utils.timezone import now

from botocore.exceptions import BotoCoreError
from celery.utils.log import get_task_logger

from core.enums import BlobStorageLocationChoices
from core.models import Blob
from core.services.tiered_storage import TieredStorageService

from messages.celery_app import app as celery_app

logger = get_task_logger(__name__)

# Transient exceptions that should trigger a Celery retry.
# BotoCoreError covers connection-level errors (timeouts, DNS, etc.).
# ClientError is intentionally excluded - it covers HTTP API errors
# (403, 404, etc.) which are usually permanent and shouldn't be retried.
_TRANSIENT_EXCEPTIONS = (
    OSError,
    BotoCoreError,
)


@celery_app.task(bind=True)
def offload_blobs_task(self) -> Dict[str, Any]:
    """
    Periodic task to find and queue blobs for offloading to object storage.

    This task finds blobs that:
    - Are currently stored in PostgreSQL
    - Are older than TIERED_STORAGE_OFFLOAD_AFTER_DAYS
    - Meet the minimum size threshold

    Returns:
        Dict with status and number of blobs queued
    """
    if not settings.TIERED_STORAGE_OFFLOAD_ENABLED:
        logger.debug("Tiered storage offload disabled, skipping")
        return {"status": "disabled", "queued": 0}

    service = TieredStorageService()
    if not service.enabled:
        logger.debug("Object storage not configured, skipping offload task")
        return {"status": "disabled", "queued": 0}

    offload_after_days = settings.TIERED_STORAGE_OFFLOAD_AFTER_DAYS
    offload_min_size = settings.TIERED_STORAGE_OFFLOAD_MIN_SIZE

    cutoff_date = now() - timedelta(days=offload_after_days)

    # Stream eligible blob IDs to avoid loading all into memory
    queryset = Blob.objects.filter(
        storage_location=BlobStorageLocationChoices.POSTGRES,
        created_at__lt=cutoff_date,
        size__gte=offload_min_size,
    ).values_list("id", flat=True)

    # Queue individual offload tasks - they run in parallel via Celery workers
    queued_count = 0
    for blob_id in queryset.iterator(chunk_size=1000):
        offload_single_blob_task.delay(str(blob_id))
        queued_count += 1

    if queued_count > 0:
        logger.info("Queued %d blobs for offloading to object storage", queued_count)

    return {"status": "success", "queued": queued_count}


@celery_app.task(bind=True, max_retries=3)
def offload_single_blob_task(self, blob_id: str) -> Dict[str, Any]:
    """
    Offload a single blob to object storage atomically.

    This task:
    1. Acquires a lock on the blob row
    2. Uploads content to object storage (with deduplication)
    3. Updates the blob record and clears raw_content
    4. All within a transaction for atomicity

    Transient S3/network errors are automatically retried with exponential
    backoff (up to 3 retries).

    Args:
        blob_id: UUID of the blob to offload

    Returns:
        Dict with status and blob_id
    """
    if not settings.TIERED_STORAGE_OFFLOAD_ENABLED:
        return {"status": "disabled", "blob_id": blob_id}

    service = TieredStorageService()
    if not service.enabled:
        return {"status": "disabled", "blob_id": blob_id}

    try:
        with transaction.atomic():
            # Lock the blob row (skip if already locked by another worker)
            try:
                blob = Blob.objects.select_for_update(nowait=True).get(id=blob_id)
            except Blob.DoesNotExist:
                logger.warning("Blob %s not found for offloading", blob_id)
                return {"status": "not_found", "blob_id": blob_id}
            except OperationalError:
                # Another worker is processing this blob
                logger.debug("Blob %s is locked by another worker, skipping", blob_id)
                return {"status": "locked", "blob_id": blob_id}

            # Skip if already offloaded
            if blob.storage_location != BlobStorageLocationChoices.POSTGRES:
                logger.debug("Blob %s already offloaded, skipping", blob_id)
                return {"status": "already_offloaded", "blob_id": blob_id}

            # Skip if no content
            if blob.raw_content is None:
                logger.warning("Blob %s has no raw_content to offload", blob_id)
                return {"status": "no_content", "blob_id": blob_id}

            # Upload to object storage
            key_id = service.upload_blob(blob)

            # Update blob record
            blob.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
            blob.encryption_key_id = key_id
            blob.raw_content = None  # Clear DB storage
            blob.save(
                update_fields=["storage_location", "encryption_key_id", "raw_content"]
            )

            logger.info(
                "Successfully offloaded blob %s to object storage (key_id=%d)",
                blob_id,
                key_id,
            )

            return {"status": "success", "blob_id": blob_id, "key_id": key_id}

    except _TRANSIENT_EXCEPTIONS as e:
        logger.warning(
            "Transient error offloading blob %s (attempt %d/%d): %s",
            blob_id,
            self.request.retries + 1,
            self.max_retries + 1,
            e,
        )
        raise self.retry(exc=e, countdown=60 * (2**self.request.retries)) from e
    except Exception as e:  # pylint: disable=broad-except
        logger.exception("Failed to offload blob %s: %s", blob_id, e)
        return {"status": "error", "blob_id": blob_id, "error": str(e)}
