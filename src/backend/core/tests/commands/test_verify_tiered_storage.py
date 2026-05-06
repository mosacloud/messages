"""Tests for verify_tiered_storage management command.

These tests use real object storage when available.
Only minimal mocking is used for testing disabled/error states.
"""

# pylint: disable=unused-argument,import-outside-toplevel

import secrets
from io import StringIO

from django.core.management import call_command
from django.test import override_settings

import pytest

from core import factories
from core.enums import BlobStorageLocationChoices
from core.services.tiered_storage import TieredStorageService

# Generate encryption key at module level for decorators (full config entry).
_TEST_ENCRYPTION_KEY = {"algo": "aes-gcm", "secret": secrets.token_hex(32)}


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
            mock_settings.MESSAGES_BLOBS_ENCRYPT_KEYS = {}

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
        storage_key = TieredStorageService.compute_storage_key_for_blob(blob)

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
            storage_keys.append(TieredStorageService.compute_storage_key_for_blob(blob))

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
        storage_key = TieredStorageService.compute_storage_key_for_blob(blob)

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
        orphan_key = f"blobs/0/{orphan_sha[:3]}/{orphan_sha}"
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

    def test_verify_hashes(self):
        """Test --verify-hashes downloads and verifies blob content."""
        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        content = b"Content for hash verification test" * 10
        blob = mailbox.create_blob(content=content, content_type="text/plain")
        storage_key = TieredStorageService.compute_storage_key_for_blob(blob)

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
        storage_key = TieredStorageService.compute_storage_key_for_blob(blob)

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
        MESSAGES_BLOBS_ENCRYPT_KEYS={"1": {**_TEST_ENCRYPTION_KEY, "active": True}},
    )
    def test_verify_hashes_with_encryption(self):
        """Test --verify-hashes works correctly with encrypted blobs."""
        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        content = b"Encrypted content for hash verification" * 10

        # create_blob() should automatically encrypt when keys are configured
        blob = mailbox.create_blob(content=content, content_type="text/plain")
        assert blob.encryption_key_id > 0  # Should be encrypted
        storage_key = TieredStorageService.compute_storage_key_for_blob(blob)

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
class TestReStoreE2E:
    """E2E tests for the --re-store functionality."""

    def test_no_keys_configured_is_a_noop(self):
        """With no encryption keys and offload on, --re-store has nothing to do."""
        from unittest.mock import patch

        stdout = StringIO()
        stderr = StringIO()

        with patch("core.services.tiered_storage.settings") as mock_settings:
            mock_settings.STORAGES = {"message-blobs": {"OPTIONS": {}}}
            mock_settings.MESSAGES_BLOBS_ENCRYPT_KEYS = {}
            mock_settings.MESSAGES_BLOBS_OFFLOAD_ENABLED = True

            call_command(
                "verify_tiered_storage",
                re_store=True,
                stdout=stdout,
                stderr=stderr,
            )

        # No encryption keys + active=0 + offload on + no offloaded blobs
        # = nothing to do.
        out = stdout.getvalue()
        assert "Nothing to do" in out or "Work units to re-store: 0" in out

    def test_all_blobs_already_current_key(self):
        """Test that re-encrypt reports success when all blobs use current key."""
        key = {"algo": "aes-gcm", "secret": secrets.token_hex(32)}
        service = TieredStorageService()
        service.encryption_keys = {"1": key}
        service.active_key_id = 1

        mailbox = factories.MailboxFactory()
        blob = mailbox.create_blob(content=b"test", content_type="text/plain")

        # Manually encrypt with key 1
        compressed = bytes(blob.raw_content)
        encrypted, key_id = service.encrypt(compressed, bytes(blob.sha256))
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
                re_store=True,
                stdout=stdout,
                stderr=stderr,
            )

        assert "Nothing to do" in stdout.getvalue()

    def test_re_store_postgres_blob(self):
        """Test re-encrypting a PostgreSQL blob with real encryption."""
        import pyzstd

        service = TieredStorageService()
        old_key = {"algo": "aes-gcm", "secret": secrets.token_hex(32)}
        new_key = {"algo": "aes-gcm", "secret": secrets.token_hex(32)}

        mailbox = factories.MailboxFactory()
        original_content = b"test content for re-encryption" * 20

        # Create blob and encrypt with old key (key_id=2)
        blob = mailbox.create_blob(content=original_content, content_type="text/plain")
        compressed = bytes(blob.raw_content)
        sha = bytes(blob.sha256)

        service.encryption_keys = {"2": old_key}
        service.active_key_id = 2
        encrypted, key_id = service.encrypt(compressed, sha)
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
                re_store=True,
                stdout=stdout,
                stderr=stderr,
            )

        output = stdout.getvalue()
        assert "Re-encrypted (rotation): 1" in output

        # Verify blob was updated
        blob.refresh_from_db()
        assert blob.encryption_key_id == 1

        # Verify content is still readable
        decrypted = service.decrypt(bytes(blob.raw_content), blob.encryption_key_id, sha)
        assert pyzstd.decompress(decrypted) == original_content

    @pytest.mark.django_db(transaction=True)
    def test_re_store_object_storage_blob(self):
        """Test re-encrypting an object storage blob with real encryption."""
        import pyzstd

        service = TieredStorageService()
        old_key = {"algo": "aes-gcm", "secret": secrets.token_hex(32)}
        new_key = {"algo": "aes-gcm", "secret": secrets.token_hex(32)}

        mailbox = factories.MailboxFactory()
        original_content = b"test content for object storage re-encryption" * 20

        # Create blob and encrypt with old key (key_id=2)
        blob = mailbox.create_blob(content=original_content, content_type="text/plain")
        compressed = bytes(blob.raw_content)
        sha = bytes(blob.sha256)

        service.encryption_keys = {"2": old_key}
        service.active_key_id = 2
        encrypted, key_id = service.encrypt(compressed, sha)
        blob.raw_content = encrypted
        blob.encryption_key_id = key_id
        blob.save()

        old_path = TieredStorageService.compute_storage_key_for_blob(blob)
        new_path = TieredStorageService.compute_storage_key(sha, 1)

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
                    re_store=True,
                    stdout=stdout,
                    stderr=stderr,
                )

            output = stdout.getvalue()
            assert "Re-encrypted (rotation): 1" in output

            # Verify blob was updated
            blob.refresh_from_db()
            assert blob.encryption_key_id == 1

            # Verify content moved from old path to new path
            assert not service.storage.exists(old_path)
            assert service.storage.exists(new_path)
            downloaded = service.download_blob(blob)
            assert pyzstd.decompress(downloaded) == original_content
        finally:
            for k in (old_path, new_path):
                if service.storage.exists(k):
                    service.storage.delete(k)

    def test_dry_run(self):
        """Test that --dry-run shows what would be done without changes."""
        service = TieredStorageService()
        key = {"algo": "aes-gcm", "secret": secrets.token_hex(32)}
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
                re_store=True,
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

    def test_re_store_with_limit(self):
        """Test that --limit restricts number of blobs re-encrypted."""
        service = TieredStorageService()
        key = {"algo": "aes-gcm", "secret": secrets.token_hex(32)}
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
                re_store=True,
                limit=2,
                stdout=stdout,
                stderr=stderr,
            )

        output = stdout.getvalue()
        assert "Work units to re-store: 2" in output

    @pytest.mark.django_db(transaction=True)
    @override_settings(MESSAGES_BLOBS_OFFLOAD_ENABLED=False)
    def test_restore_to_postgres_when_offload_disabled(self):
        """When offload is off, --re-store pulls OBJECT_STORAGE blobs back to PG."""
        import pyzstd

        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        original = b"content to restore back to postgres" * 30

        blob = mailbox.create_blob(content=original, content_type="text/plain")
        storage_key = TieredStorageService.compute_storage_key_for_blob(blob)

        try:
            # Pre-condition: offload the blob.
            service.upload_blob(blob)
            blob.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
            blob.raw_content = None
            blob.save()
            assert service.storage.exists(storage_key)

            stdout = StringIO()
            stderr = StringIO()

            call_command(
                "verify_tiered_storage",
                re_store=True,
                stdout=stdout,
                stderr=stderr,
            )

            output = stdout.getvalue()
            assert "Restored to PostgreSQL: 1" in output

            blob.refresh_from_db()
            assert blob.storage_location == BlobStorageLocationChoices.POSTGRES
            assert blob.raw_content is not None
            # And the content is still readable.
            assert pyzstd.decompress(bytes(blob.raw_content)) == original
            assert blob.get_content() == original
            # Last cohort member restored → S3 object cleaned up.
            assert not service.storage.exists(storage_key)
        finally:
            if service.storage.exists(storage_key):
                service.storage.delete(storage_key)

    # ``test_restore_keeps_s3_until_last_cohort_member`` removed: with
    # DB-level dedup at create time, two mailboxes uploading the same
    # content land in the SAME Blob row (size-1 cohort), so the
    # progressive restore-then-cleanup-on-last-member flow that this
    # test exercised is no longer reachable from the application path.
    # ``delete_if_orphaned`` still has its own unit test in
    # ``test_tiered_storage.py::TestTieredStorageE2E.test_delete_if_orphaned``.

    def test_re_store_skips_blob_without_content(self):
        """Test that re-encrypt skips PostgreSQL blobs with no content."""
        service = TieredStorageService()
        key = {"algo": "aes-gcm", "secret": secrets.token_hex(32)}
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
                re_store=True,
                stdout=stdout,
                stderr=stderr,
            )

        output = stdout.getvalue()
        assert "Skipped: 1" in output
        # Blob row left unchanged.
        blob.refresh_from_db()
        assert blob.encryption_key_id == 0
        assert blob.raw_content is None

    @pytest.mark.django_db(transaction=True)
    @override_settings(
        MESSAGES_BLOBS_ENCRYPT_KEYS={
            "1": {**_TEST_ENCRYPTION_KEY, "active": True},
        },
    )
    def test_re_store_object_storage_first_encryption(self):
        """D8 — rotate a plain (key_id=0) S3 blob to encrypted (key=1).

        The "we just enabled encryption, sweep the legacy plain S3 blobs"
        scenario. Today's tests covered the POSTGRES variant; this is
        the OBJECT_STORAGE one. After --re-store, the cohort flips to
        key_id=1, the path moves from blobs/0/... to blobs/1/..., and
        the content is still readable.
        """
        import pyzstd

        # Step 1: create + offload a plain blob (no encryption configured).
        with override_settings(MESSAGES_BLOBS_ENCRYPT_KEYS={}):
            mailbox = factories.MailboxFactory()
            content = b"legacy plain content awaiting encryption" * 20
            blob = mailbox.create_blob(content=content, content_type="text/plain")
            assert blob.encryption_key_id == 0
            plain_service = TieredStorageService()
            plain_service.upload_blob(blob)
            blob.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
            blob.raw_content = None
            blob.save()

        old_path = TieredStorageService.compute_storage_key(bytes(blob.sha256), 0)
        new_path = TieredStorageService.compute_storage_key(bytes(blob.sha256), 1)

        # Step 2: encryption is now enabled (key 1 active, decorator
        # already applied). Build a fresh service that picks up the new
        # keys, run --re-store.
        service = TieredStorageService()
        try:
            assert service.storage.exists(old_path)

            stdout = StringIO()
            stderr = StringIO()
            call_command(
                "verify_tiered_storage",
                re_store=True,
                stdout=stdout,
                stderr=stderr,
            )
            assert "Re-encrypted (rotation): 1" in stdout.getvalue()

            blob.refresh_from_db()
            assert blob.encryption_key_id == 1
            assert blob.storage_location == BlobStorageLocationChoices.OBJECT_STORAGE
            assert not service.storage.exists(old_path)
            assert service.storage.exists(new_path)
            downloaded = service.download_blob(blob)
            assert pyzstd.decompress(downloaded) == content
        finally:
            for k in (old_path, new_path):
                if service.storage.exists(k):
                    service.storage.delete(k)

    @pytest.mark.django_db(transaction=True)
    @override_settings(MESSAGES_BLOBS_OFFLOAD_ENABLED=False)
    def test_re_store_decrypts_to_plaintext_when_no_active_key(self):
        """Rolling encryption + offload back, end-to-end. Start: blob is
        encrypted under key 1 in S3. Drop encryption (passive entry only)
        and disable offload. ``--re-store`` pulls the blob back into PG
        with ``key_id=0`` and a plain (re-encrypted-with-passthrough)
        ``raw_content``. The S3 object is removed once the cohort empties.
        """
        import pyzstd

        with override_settings(
            MESSAGES_BLOBS_ENCRYPT_KEYS={
                "1": {**_TEST_ENCRYPTION_KEY, "active": True}
            },
        ):
            mailbox = factories.MailboxFactory()
            content = b"encrypted content to be decrypted on rollback" * 20
            blob = mailbox.create_blob(content=content, content_type="text/plain")
            assert blob.encryption_key_id == 1
            service = TieredStorageService()
            service.upload_blob(blob)
            blob.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
            blob.raw_content = None
            blob.save()

        encrypted_path = TieredStorageService.compute_storage_key(
            bytes(blob.sha256), 1
        )
        try:
            assert service.storage.exists(encrypted_path)

            with override_settings(
                MESSAGES_BLOBS_ENCRYPT_KEYS={
                    "1": {**_TEST_ENCRYPTION_KEY},  # passive, still readable
                },
            ):
                stdout = StringIO()
                stderr = StringIO()
                call_command(
                    "verify_tiered_storage",
                    re_store=True,
                    stdout=stdout,
                    stderr=stderr,
                )
                assert "Restored to PostgreSQL: 1" in stdout.getvalue()

                blob.refresh_from_db()
                assert blob.storage_location == BlobStorageLocationChoices.POSTGRES
                # active=0 → encrypt is passthrough → row stored as plaintext.
                assert blob.encryption_key_id == 0
                assert blob.raw_content is not None
                assert pyzstd.decompress(bytes(blob.raw_content)) == content
                assert blob.get_content() == content
                assert not service.storage.exists(encrypted_path)
        finally:
            if service.storage.exists(encrypted_path):
                service.storage.delete(encrypted_path)

    @pytest.mark.django_db(transaction=True)
    @override_settings(
        MESSAGES_BLOBS_OFFLOAD_ENABLED=False,
        MESSAGES_BLOBS_ENCRYPT_KEYS={
            "1": {**_TEST_ENCRYPTION_KEY, "active": True}
        },
    )
    def test_re_store_partial_failure_continues(self):
        """One blob fails mid-loop; the command keeps going and reports
        a non-zero error count. No partial-state corruption: failed blob
        stays as it was, others complete."""
        from unittest.mock import patch

        # Service must be constructed AFTER the override_settings decorators
        # apply so it picks up encryption_keys with key 1 active.
        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        blobs = [
            mailbox.create_blob(
                content=f"distinct content {i}".encode() * 30,
                content_type="text/plain",
            )
            for i in range(3)
        ]
        keys = [
            TieredStorageService.compute_storage_key_for_blob(b) for b in blobs
        ]
        for b in blobs:
            service.upload_blob(b)
            b.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
            b.raw_content = None
            b.save()

        original_open = service.storage.open
        failing_path = TieredStorageService.compute_storage_key_for_blob(blobs[1])

        def selective_open(name, mode="rb", *a, **kw):
            if name == failing_path:
                raise RuntimeError("simulated download failure")
            return original_open(name, mode, *a, **kw)

        try:
            with patch.object(service.storage, "open", side_effect=selective_open):
                with patch(
                    "core.management.commands.verify_tiered_storage.TieredStorageService",
                    return_value=service,
                ):
                    stdout = StringIO()
                    stderr = StringIO()
                    call_command(
                        "verify_tiered_storage",
                        re_store=True,
                        stdout=stdout,
                        stderr=stderr,
                    )

            output = stdout.getvalue()
            # blobs[0] and blobs[2] succeed; blobs[1] errors.
            assert "Restored to PostgreSQL: 2" in output
            assert "Errors: 1" in output

            blobs[1].refresh_from_db()
            assert (
                blobs[1].storage_location == BlobStorageLocationChoices.OBJECT_STORAGE
            )
            for i in (0, 2):
                blobs[i].refresh_from_db()
                assert (
                    blobs[i].storage_location == BlobStorageLocationChoices.POSTGRES
                )
        finally:
            for k in keys:
                if service.storage.exists(k):
                    service.storage.delete(k)

    def test_verify_db_to_storage_detects_externally_deleted_object(self):
        """Drift between DB and S3 (an OBJECT_STORAGE row whose path is
        gone from the bucket) is the failure mode that ``upload_blob``
        no longer guards against — so the verify command IS the line of
        defense. Confirm it surfaces as ``MISSING``."""
        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        blob = mailbox.create_blob(content=b"test", content_type="text/plain")
        storage_key = TieredStorageService.compute_storage_key_for_blob(blob)

        try:
            service.upload_blob(blob)
            blob.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
            blob.raw_content = None
            blob.save()
            assert service.storage.exists(storage_key)

            # External deletion (operator mishap, lifecycle expiry, etc.).
            service.storage.delete(storage_key)
            assert not service.storage.exists(storage_key)

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
        finally:
            if service.storage.exists(storage_key):
                service.storage.delete(storage_key)
