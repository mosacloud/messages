"""Tests for verify_tiered_storage management command.

These tests use real MinIO object storage when available.
Only minimal mocking is used for testing disabled/error states.
"""

# pylint: disable=unused-argument,import-outside-toplevel

from io import StringIO

from django.core.management import call_command
from django.test import override_settings

import pytest
from cryptography.fernet import Fernet

from core import factories
from core.enums import BlobStorageLocationChoices
from core.services.tiered_storage import TieredStorageService

# Generate encryption key at module level for decorators
_TEST_ENCRYPTION_KEY = Fernet.generate_key().decode()


@pytest.mark.django_db
class TestVerifyTieredStorageDisabled:
    """Tests for when storage is not configured."""

    def test_command_disabled_when_no_storage(self):
        """Test that command reports disabled when storage not configured."""
        from unittest.mock import patch

        stdout = StringIO()
        stderr = StringIO()

        with patch("core.services.tiered_storage.settings") as mock_settings:
            mock_settings.STORAGES = {}
            mock_settings.MESSAGES_BLOB_ENCRYPTION_KEYS = {}
            mock_settings.MESSAGES_BLOB_ENCRYPTION_ACTIVE_KEY_ID = 0

            call_command("verify_tiered_storage", stdout=stdout, stderr=stderr)

        assert "not configured" in stderr.getvalue()


@pytest.mark.django_db
class TestVerifyDbToStorageE2E:
    """E2E tests for db-to-storage verification mode."""

    def test_all_blobs_present(self):
        """Test db-to-storage when all blobs exist in storage."""
        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        blob = factories.BlobFactory(mailbox=mailbox)
        storage_key = blob.get_storage_key()

        try:
            # Upload blob to storage
            service.upload_blob(blob)
            blob.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
            blob.save()

            stdout = StringIO()
            stderr = StringIO()

            call_command(
                "verify_tiered_storage",
                mode="db-to-storage",
                stdout=stdout,
                stderr=stderr,
            )

            output = stdout.getvalue()
            assert "All blobs have storage backing" in output
            assert "MISSING" not in stderr.getvalue()
        finally:
            if service.storage.exists(storage_key):
                service.storage.delete(storage_key)

    def test_missing_blob_detected(self):
        """Test db-to-storage when a blob is missing from storage."""
        mailbox = factories.MailboxFactory()
        blob = factories.BlobFactory(mailbox=mailbox)

        # Mark as in object storage but don't actually upload
        blob.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
        blob.save()

        stdout = StringIO()
        stderr = StringIO()

        call_command(
            "verify_tiered_storage",
            mode="db-to-storage",
            stdout=stdout,
            stderr=stderr,
        )

        assert "MISSING" in stderr.getvalue()
        assert str(blob.id) in stderr.getvalue()
        assert "1 blobs missing" in stdout.getvalue()

    def test_limit_option(self):
        """Test that --limit restricts number of items checked."""
        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        blobs = []
        storage_keys = []

        # Create 5 blobs in object storage
        for i in range(5):
            blob = mailbox.create_blob(
                content=f"test content {i}".encode(),
                content_type="text/plain",
            )
            service.upload_blob(blob)
            blob.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
            blob.save()
            blobs.append(blob)
            storage_keys.append(blob.get_storage_key())

        try:
            stdout = StringIO()
            stderr = StringIO()

            call_command(
                "verify_tiered_storage",
                mode="db-to-storage",
                limit=2,
                stdout=stdout,
                stderr=stderr,
            )

            output = stdout.getvalue()
            assert "Checked: 2 blobs" in output
        finally:
            for key in storage_keys:
                if service.storage.exists(key):
                    service.storage.delete(key)


@pytest.mark.django_db
class TestVerifyStorageToDbE2E:
    """E2E tests for storage-to-db verification mode."""

    def test_no_orphans(self):
        """Test storage-to-db when no orphans exist."""
        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        blob = factories.BlobFactory(mailbox=mailbox)
        storage_key = blob.get_storage_key()

        try:
            service.upload_blob(blob)
            blob.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
            blob.save()

            stdout = StringIO()
            stderr = StringIO()

            call_command(
                "verify_tiered_storage",
                mode="storage-to-db",
                stdout=stdout,
                stderr=stderr,
            )

            output = stdout.getvalue()
            assert "Storage to DB Verification" in output
            # Should not find our blob as an orphan
            assert "ORPHAN" not in output or storage_key not in output
        finally:
            if service.storage.exists(storage_key):
                service.storage.delete(storage_key)

    def test_orphan_detected(self):
        """Test storage-to-db when an orphan exists."""
        from django.core.files.base import ContentFile

        service = TieredStorageService()
        # Create an orphan object in storage (no DB record)
        orphan_sha = "a" * 64
        orphan_key = f"blobs/{orphan_sha[:3]}/{orphan_sha}"
        service.storage.save(orphan_key, ContentFile(b"orphan content"))

        try:
            stdout = StringIO()
            stderr = StringIO()

            call_command(
                "verify_tiered_storage",
                mode="storage-to-db",
                stdout=stdout,
                stderr=stderr,
            )

            output = stdout.getvalue()
            assert "ORPHAN" in output
            assert "Orphans: 1" in output
        finally:
            if service.storage.exists(orphan_key):
                service.storage.delete(orphan_key)

    def test_fix_deletes_orphan(self):
        """Test that --fix deletes orphans from storage."""
        from django.core.files.base import ContentFile

        service = TieredStorageService()
        orphan_sha = "b" * 64
        orphan_key = f"blobs/{orphan_sha[:3]}/{orphan_sha}"
        service.storage.save(orphan_key, ContentFile(b"orphan content"))

        try:
            assert service.storage.exists(orphan_key)

            stdout = StringIO()
            stderr = StringIO()

            call_command(
                "verify_tiered_storage",
                mode="storage-to-db",
                fix=True,
                stdout=stdout,
                stderr=stderr,
            )

            output = stdout.getvalue()
            assert "ORPHAN" in output
            assert "Deleted orphan" in output
            assert not service.storage.exists(orphan_key)
        finally:
            if service.storage.exists(orphan_key):
                service.storage.delete(orphan_key)

    def test_verify_hashes(self):
        """Test --verify-hashes downloads and verifies blob content."""
        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        content = b"Content for hash verification test" * 10
        blob = mailbox.create_blob(content=content, content_type="text/plain")
        storage_key = blob.get_storage_key()

        try:
            service.upload_blob(blob)
            blob.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
            blob.raw_content = None
            blob.save()

            stdout = StringIO()
            stderr = StringIO()

            call_command(
                "verify_tiered_storage",
                mode="storage-to-db",
                verify_hashes=True,
                stdout=stdout,
                stderr=stderr,
            )

            output = stdout.getvalue()
            assert "Hash mismatches: 0" in output
        finally:
            if service.storage.exists(storage_key):
                service.storage.delete(storage_key)


@pytest.mark.django_db
class TestVerifyHashesE2E:
    """E2E tests for --verify-hashes with edge cases."""

    def test_verify_hashes_detects_corruption(self):
        """Test that --verify-hashes detects corrupted content."""
        from django.core.files.base import ContentFile

        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        content = b"Content that will be corrupted" * 10
        blob = mailbox.create_blob(content=content, content_type="text/plain")
        storage_key = blob.get_storage_key()

        try:
            # Upload blob normally
            service.upload_blob(blob)
            blob.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
            blob.raw_content = None
            blob.save()

            # Corrupt the storage object
            service.storage.delete(storage_key)
            service.storage.save(storage_key, ContentFile(b"corrupted garbage data"))

            stdout = StringIO()
            stderr = StringIO()

            call_command(
                "verify_tiered_storage",
                mode="storage-to-db",
                verify_hashes=True,
                stdout=stdout,
                stderr=stderr,
            )

            output = stdout.getvalue()
            # Should detect hash mismatch or decryption error
            assert "HASH MISMATCH" in output or "VERIFY ERROR" in output
        finally:
            if service.storage.exists(storage_key):
                service.storage.delete(storage_key)

    @override_settings(
        MESSAGES_BLOB_ENCRYPTION_KEYS={"1": _TEST_ENCRYPTION_KEY},
        MESSAGES_BLOB_ENCRYPTION_ACTIVE_KEY_ID=1,
    )
    def test_verify_hashes_with_encryption(self):
        """Test --verify-hashes works correctly with encrypted blobs."""
        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        content = b"Encrypted content for hash verification" * 10

        # create_blob() should automatically encrypt when keys are configured
        blob = mailbox.create_blob(content=content, content_type="text/plain")
        assert blob.encryption_key_id > 0  # Should be encrypted
        storage_key = blob.get_storage_key()

        try:
            service.upload_blob(blob)
            blob.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
            blob.raw_content = None
            blob.save()

            stdout = StringIO()
            stderr = StringIO()

            call_command(
                "verify_tiered_storage",
                mode="storage-to-db",
                verify_hashes=True,
                stdout=stdout,
                stderr=stderr,
            )

            output = stdout.getvalue()
            assert "Hash mismatches: 0" in output
        finally:
            if service.storage and service.storage.exists(storage_key):
                service.storage.delete(storage_key)


@pytest.mark.django_db
class TestReEncryptE2E:
    """E2E tests for the --re-encrypt functionality."""

    def test_re_encrypt_no_keys_configured(self):
        """Test that re-encrypt fails when no keys are configured."""
        from unittest.mock import patch

        stdout = StringIO()
        stderr = StringIO()

        with patch("core.services.tiered_storage.settings") as mock_settings:
            mock_settings.STORAGES = {"message-blobs": {"OPTIONS": {}}}
            mock_settings.MESSAGES_BLOB_ENCRYPTION_KEYS = {}
            mock_settings.MESSAGES_BLOB_ENCRYPTION_ACTIVE_KEY_ID = 0

            call_command(
                "verify_tiered_storage",
                re_encrypt=True,
                stdout=stdout,
                stderr=stderr,
            )

        assert "No encryption keys configured" in stderr.getvalue()

    def test_all_blobs_already_current_key(self):
        """Test that re-encrypt reports success when all blobs use current key."""
        key = Fernet.generate_key().decode()
        service = TieredStorageService()
        service.encryption_keys = {"1": key}
        service.active_key_id = 1

        mailbox = factories.MailboxFactory()
        blob = mailbox.create_blob(content=b"test", content_type="text/plain")

        # Manually encrypt with key 1
        compressed = bytes(blob.raw_content)
        encrypted, key_id = service.encrypt(compressed)
        blob.raw_content = encrypted
        blob.encryption_key_id = key_id
        blob.save()

        stdout = StringIO()
        stderr = StringIO()

        # Temporarily modify service in command
        from unittest.mock import patch

        with patch(
            "core.management.commands.verify_tiered_storage.TieredStorageService"
        ) as mock_svc_class:
            mock_svc_class.return_value = service

            call_command(
                "verify_tiered_storage",
                re_encrypt=True,
                stdout=stdout,
                stderr=stderr,
            )

        assert "All blobs already use the current encryption key" in stdout.getvalue()

    def test_re_encrypt_postgres_blob(self):
        """Test re-encrypting a PostgreSQL blob with real encryption."""
        import pyzstd

        service = TieredStorageService()
        old_key = Fernet.generate_key().decode()
        new_key = Fernet.generate_key().decode()

        mailbox = factories.MailboxFactory()
        original_content = b"test content for re-encryption" * 20

        # Create blob and encrypt with old key (key_id=2)
        blob = mailbox.create_blob(content=original_content, content_type="text/plain")
        compressed = bytes(blob.raw_content)

        service.encryption_keys = {"2": old_key}
        service.active_key_id = 2
        encrypted, key_id = service.encrypt(compressed)
        blob.raw_content = encrypted
        blob.encryption_key_id = key_id
        blob.save()

        # Now configure service for key rotation (new key is "1", old is "2")
        service.encryption_keys = {"1": new_key, "2": old_key}
        service.active_key_id = 1

        stdout = StringIO()
        stderr = StringIO()

        from unittest.mock import patch

        with patch(
            "core.management.commands.verify_tiered_storage.TieredStorageService"
        ) as mock_svc_class:
            mock_svc_class.return_value = service

            call_command(
                "verify_tiered_storage",
                re_encrypt=True,
                stdout=stdout,
                stderr=stderr,
            )

        output = stdout.getvalue()
        assert "Re-encrypted" in output
        assert "key_id 2 -> 1" in output

        # Verify blob was updated
        blob.refresh_from_db()
        assert blob.encryption_key_id == 1

        # Verify content is still readable
        decrypted = service.decrypt(bytes(blob.raw_content), blob.encryption_key_id)
        assert pyzstd.decompress(decrypted) == original_content

    @pytest.mark.django_db(transaction=True)
    def test_re_encrypt_object_storage_blob(self):
        """Test re-encrypting an object storage blob with real encryption."""
        import pyzstd

        service = TieredStorageService()
        old_key = Fernet.generate_key().decode()
        new_key = Fernet.generate_key().decode()

        mailbox = factories.MailboxFactory()
        original_content = b"test content for object storage re-encryption" * 20

        # Create blob and encrypt with old key (key_id=2)
        blob = mailbox.create_blob(content=original_content, content_type="text/plain")
        compressed = bytes(blob.raw_content)

        service.encryption_keys = {"2": old_key}
        service.active_key_id = 2
        encrypted, key_id = service.encrypt(compressed)
        blob.raw_content = encrypted
        blob.encryption_key_id = key_id
        blob.save()

        storage_key = blob.get_storage_key()

        try:
            # Upload to storage
            service.upload_blob(blob)
            blob.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
            blob.raw_content = None
            blob.save()

            # Configure for key rotation
            service.encryption_keys = {"1": new_key, "2": old_key}
            service.active_key_id = 1

            stdout = StringIO()
            stderr = StringIO()

            from unittest.mock import patch

            with patch(
                "core.management.commands.verify_tiered_storage.TieredStorageService"
            ) as mock_svc_class:
                mock_svc_class.return_value = service

                call_command(
                    "verify_tiered_storage",
                    re_encrypt=True,
                    stdout=stdout,
                    stderr=stderr,
                )

            output = stdout.getvalue()
            assert "Re-encrypted" in output
            assert "key_id 2 -> 1" in output
            assert "OBJECT_STORAGE" in output

            # Verify blob was updated
            blob.refresh_from_db()
            assert blob.encryption_key_id == 1

            # Verify content is still readable
            downloaded = service.download_blob(blob)
            assert pyzstd.decompress(downloaded) == original_content
        finally:
            if service.storage.exists(storage_key):
                service.storage.delete(storage_key)

    def test_dry_run(self):
        """Test that --dry-run shows what would be done without changes."""
        service = TieredStorageService()
        key = Fernet.generate_key().decode()
        service.encryption_keys = {"1": key}
        service.active_key_id = 1

        mailbox = factories.MailboxFactory()
        blob = mailbox.create_blob(content=b"test", content_type="text/plain")
        # key_id=0 means unencrypted, needs re-encryption
        blob.encryption_key_id = 0
        blob.save()

        stdout = StringIO()
        stderr = StringIO()

        from unittest.mock import patch

        with patch(
            "core.management.commands.verify_tiered_storage.TieredStorageService"
        ) as mock_svc_class:
            mock_svc_class.return_value = service

            call_command(
                "verify_tiered_storage",
                re_encrypt=True,
                dry_run=True,
                stdout=stdout,
                stderr=stderr,
            )

        output = stdout.getvalue()
        assert "DRY RUN" in output
        assert "Would re-encrypt" in output

        # Verify blob was NOT modified
        blob.refresh_from_db()
        assert blob.encryption_key_id == 0

    def test_re_encrypt_with_limit(self):
        """Test that --limit restricts number of blobs re-encrypted."""
        service = TieredStorageService()
        key = Fernet.generate_key().decode()
        service.encryption_keys = {"1": key}
        service.active_key_id = 1

        mailbox = factories.MailboxFactory()

        # Create 3 blobs with key_id=0
        for i in range(3):
            blob = mailbox.create_blob(
                content=f"test content {i}".encode(),
                content_type="text/plain",
            )
            blob.encryption_key_id = 0
            blob.save()

        stdout = StringIO()
        stderr = StringIO()

        from unittest.mock import patch

        with patch(
            "core.management.commands.verify_tiered_storage.TieredStorageService"
        ) as mock_svc_class:
            mock_svc_class.return_value = service

            call_command(
                "verify_tiered_storage",
                re_encrypt=True,
                limit=2,
                stdout=stdout,
                stderr=stderr,
            )

        output = stdout.getvalue()
        assert "Blobs to re-encrypt: 2" in output

    def test_re_encrypt_skips_blob_without_content(self):
        """Test that re-encrypt skips PostgreSQL blobs with no content."""
        service = TieredStorageService()
        key = Fernet.generate_key().decode()
        service.encryption_keys = {"1": key}
        service.active_key_id = 1

        mailbox = factories.MailboxFactory()
        blob = mailbox.create_blob(content=b"test", content_type="text/plain")
        blob.encryption_key_id = 0
        blob.raw_content = None  # Simulate missing content
        blob.save()

        stdout = StringIO()
        stderr = StringIO()

        from unittest.mock import patch

        with patch(
            "core.management.commands.verify_tiered_storage.TieredStorageService"
        ) as mock_svc_class:
            mock_svc_class.return_value = service

            call_command(
                "verify_tiered_storage",
                re_encrypt=True,
                stdout=stdout,
                stderr=stderr,
            )

        output = stdout.getvalue()
        assert "SKIP" in output
        assert "Skipped: 1" in output
