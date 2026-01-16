"""Tests for tiered storage Celery tasks.

These tests use real MinIO object storage when available.
Only minimal mocking for disabled state and error simulation.
"""

# pylint: disable=no-value-for-parameter,unused-argument

from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings
from django.utils.timezone import now

import pytest
from cryptography.fernet import Fernet

from core import factories
from core.enums import BlobStorageLocationChoices
from core.models import Blob
from core.services.tiered_storage import TieredStorageService
from core.services.tiered_storage_tasks import (
    offload_blobs_task,
    offload_single_blob_task,
)

# Generate encryption keys at module level for decorators
_TEST_ENCRYPTION_KEY = Fernet.generate_key().decode()


@pytest.mark.django_db
class TestOffloadBlobsTaskDisabled:
    """Tests for offload_blobs_task when storage is disabled."""

    def test_task_disabled_when_no_storage(self):
        """Test that task returns disabled status when storage not configured."""
        with patch("core.services.tiered_storage.settings") as mock_settings:
            mock_settings.STORAGES = {
                "message-blobs": {"OPTIONS": {"endpoint_url": ""}}
            }
            mock_settings.MESSAGES_BLOB_ENCRYPTION_KEYS = {}
            mock_settings.MESSAGES_BLOB_ENCRYPTION_ACTIVE_KEY_ID = 0

            result = offload_blobs_task()

            assert result["status"] == "disabled"
            assert result["queued"] == 0


@pytest.mark.django_db
class TestOffloadBlobsTaskE2E:
    """E2E tests for offload_blobs_task."""

    def test_queues_eligible_blobs_by_age(self):
        """Test that task queues blobs older than cutoff date."""
        mailbox = factories.MailboxFactory()

        # Create an old blob (should be queued)
        old_blob = mailbox.create_blob(
            content=b"old content", content_type="text/plain"
        )
        Blob.objects.filter(id=old_blob.id).update(
            created_at=now()
            - timedelta(days=settings.TIERED_STORAGE_OFFLOAD_AFTER_DAYS + 1)
        )

        # Create a new blob (should not be queued)
        new_blob = mailbox.create_blob(
            content=b"new content", content_type="text/plain"
        )

        # Mock the delay call to track what gets queued
        queued_ids = []
        with patch.object(
            offload_single_blob_task,
            "delay",
            side_effect=queued_ids.append,
        ):
            result = offload_blobs_task()

        assert result["status"] == "success"
        assert str(old_blob.id) in queued_ids
        assert str(new_blob.id) not in queued_ids

    def test_queues_eligible_blobs_by_size(self):
        """Test that task respects minimum size threshold."""
        mailbox = factories.MailboxFactory()

        # Create a small blob (may or may not be queued depending on OFFLOAD_MIN_SIZE)
        small_blob = mailbox.create_blob(content=b"small", content_type="text/plain")
        Blob.objects.filter(id=small_blob.id).update(
            created_at=now()
            - timedelta(days=settings.TIERED_STORAGE_OFFLOAD_AFTER_DAYS + 1)
        )

        # Create a large blob (should be queued if old enough)
        large_content = b"x" * (settings.TIERED_STORAGE_OFFLOAD_MIN_SIZE + 1000)
        large_blob = mailbox.create_blob(
            content=large_content, content_type="text/plain"
        )
        Blob.objects.filter(id=large_blob.id).update(
            created_at=now()
            - timedelta(days=settings.TIERED_STORAGE_OFFLOAD_AFTER_DAYS + 1)
        )

        queued_ids = []
        with patch.object(
            offload_single_blob_task,
            "delay",
            side_effect=queued_ids.append,
        ):
            result = offload_blobs_task()

        assert result["status"] == "success"
        assert str(large_blob.id) in queued_ids

        # Small blob should only be queued if min_size is 0
        if settings.TIERED_STORAGE_OFFLOAD_MIN_SIZE > 0:
            assert str(small_blob.id) not in queued_ids

    def test_skips_already_offloaded_blobs(self):
        """Test that task doesn't queue already offloaded blobs."""
        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        blob = mailbox.create_blob(content=b"test", content_type="text/plain")
        storage_key = blob.get_storage_key()

        try:
            # Offload the blob
            service.upload_blob(blob)
            blob.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
            blob.raw_content = None
            blob.save()

            # Make it old
            Blob.objects.filter(id=blob.id).update(
                created_at=now()
                - timedelta(days=settings.TIERED_STORAGE_OFFLOAD_AFTER_DAYS + 1)
            )

            queued_ids = []
            with patch.object(
                offload_single_blob_task,
                "delay",
                side_effect=queued_ids.append,
            ):
                offload_blobs_task()

            assert str(blob.id) not in queued_ids
        finally:
            if service.storage.exists(storage_key):
                service.storage.delete(storage_key)


@pytest.mark.django_db
class TestOffloadSingleBlobTaskDisabled:
    """Tests for offload_single_blob_task when storage is disabled."""

    def test_task_disabled_when_no_storage(self):
        """Test that task returns disabled status when storage not configured."""
        with patch("core.services.tiered_storage.settings") as mock_settings:
            mock_settings.STORAGES = {
                "message-blobs": {"OPTIONS": {"endpoint_url": ""}}
            }
            mock_settings.MESSAGES_BLOB_ENCRYPTION_KEYS = {}
            mock_settings.MESSAGES_BLOB_ENCRYPTION_ACTIVE_KEY_ID = 0

            result = offload_single_blob_task("fake-uuid")

            assert result["status"] == "disabled"


@pytest.mark.django_db
class TestOffloadSingleBlobTaskE2E:
    """E2E tests for offload_single_blob_task."""

    def test_not_found(self):
        """Test that task handles non-existent blob."""
        result = offload_single_blob_task("00000000-0000-0000-0000-000000000000")
        assert result["status"] == "not_found"

    def test_already_offloaded(self):
        """Test that task skips already offloaded blobs."""
        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        blob = mailbox.create_blob(content=b"test", content_type="text/plain")
        storage_key = blob.get_storage_key()

        try:
            # Manually offload
            service.upload_blob(blob)
            blob.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
            blob.raw_content = None
            blob.save()

            result = offload_single_blob_task(str(blob.id))

            assert result["status"] == "already_offloaded"
        finally:
            if service.storage.exists(storage_key):
                service.storage.delete(storage_key)

    def test_successful_offload(self):
        """Test successful blob offload with content verification."""
        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        original_content = b"test content for offload" * 20
        blob = mailbox.create_blob(content=original_content, content_type="text/plain")
        storage_key = blob.get_storage_key()

        try:
            result = offload_single_blob_task(str(blob.id))

            assert result["status"] == "success"
            assert result["blob_id"] == str(blob.id)

            # Verify blob was updated
            blob.refresh_from_db()
            assert blob.storage_location == BlobStorageLocationChoices.OBJECT_STORAGE
            assert blob.raw_content is None

            # Verify content is accessible
            retrieved = blob.get_content()
            assert retrieved == original_content
        finally:
            if service.storage.exists(storage_key):
                service.storage.delete(storage_key)

    def test_no_content(self):
        """Test that task handles blobs with no content."""
        mailbox = factories.MailboxFactory()
        blob = mailbox.create_blob(content=b"test", content_type="text/plain")

        # Simulate blob with cleared content
        Blob.objects.filter(id=blob.id).update(raw_content=None)

        result = offload_single_blob_task(str(blob.id))

        assert result["status"] == "no_content"

    def test_handles_upload_error(self):
        """Test that task handles upload errors gracefully."""
        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        blob = mailbox.create_blob(content=b"test", content_type="text/plain")

        # Mock storage to raise an error
        with patch.object(
            service.storage, "save", side_effect=Exception("Upload failed")
        ):
            with patch(
                "core.services.tiered_storage_tasks.TieredStorageService",
                return_value=service,
            ):
                result = offload_single_blob_task(str(blob.id))

        assert result["status"] == "error"
        assert "Upload failed" in result["error"]

        # Verify blob was NOT modified (transaction rolled back)
        blob.refresh_from_db()
        assert blob.storage_location == BlobStorageLocationChoices.POSTGRES
        assert blob.raw_content is not None

    def test_deduplication_during_offload(self):
        """Test that offload uses deduplication for identical content."""
        service = TieredStorageService()
        mailbox1 = factories.MailboxFactory()
        mailbox2 = factories.MailboxFactory()
        content = b"identical content for dedup test" * 20

        blob1 = mailbox1.create_blob(content=content, content_type="text/plain")
        blob2 = mailbox2.create_blob(content=content, content_type="text/plain")

        assert blob1.sha256 == blob2.sha256
        storage_key = blob1.get_storage_key()

        try:
            # Offload first blob
            result1 = offload_single_blob_task(str(blob1.id))
            assert result1["status"] == "success"

            # Offload second blob - should use existing storage object
            result2 = offload_single_blob_task(str(blob2.id))
            assert result2["status"] == "success"

            # Both should be accessible
            blob1.refresh_from_db()
            blob2.refresh_from_db()
            assert blob1.get_content() == content
            assert blob2.get_content() == content

            # Delete first blob - storage should remain
            blob1.delete()
            assert service.storage.exists(storage_key)

            # Delete second blob - now orphaned
            blob2.delete()
            assert not service.storage.exists(storage_key)
        finally:
            if service.storage.exists(storage_key):
                service.storage.delete(storage_key)

    @override_settings(
        MESSAGES_BLOB_ENCRYPTION_KEYS={"1": _TEST_ENCRYPTION_KEY},
        MESSAGES_BLOB_ENCRYPTION_ACTIVE_KEY_ID=1,
    )
    def test_offload_with_encryption(self):
        """Test offload preserves encryption key_id."""
        mailbox = factories.MailboxFactory()
        original_content = b"encrypted content for offload test" * 20

        # create_blob() should automatically encrypt when keys are configured
        blob = mailbox.create_blob(content=original_content, content_type="text/plain")
        assert blob.encryption_key_id > 0  # Should be encrypted
        storage_key = blob.get_storage_key()

        try:
            result = offload_single_blob_task(str(blob.id))
            assert result["status"] == "success"

            blob.refresh_from_db()
            assert blob.storage_location == BlobStorageLocationChoices.OBJECT_STORAGE
            assert blob.encryption_key_id > 0  # Preserved

            # Verify content readable
            retrieved = blob.get_content()
            assert retrieved == original_content
        finally:
            service = TieredStorageService()
            if service.storage and service.storage.exists(storage_key):
                service.storage.delete(storage_key)

    def test_concurrent_offload_idempotent(self):
        """Test that concurrent offload attempts are handled gracefully."""
        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        blob = mailbox.create_blob(content=b"test content", content_type="text/plain")
        storage_key = blob.get_storage_key()

        try:
            # First offload succeeds
            result1 = offload_single_blob_task(str(blob.id))
            assert result1["status"] == "success"

            # Second offload should report already_offloaded
            result2 = offload_single_blob_task(str(blob.id))
            assert result2["status"] == "already_offloaded"
        finally:
            if service.storage.exists(storage_key):
                service.storage.delete(storage_key)
