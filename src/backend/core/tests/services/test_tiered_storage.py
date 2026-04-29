"""Tests for tiered storage functionality.

These tests use real MinIO object storage when available.
Unit tests only cover pure functions that don't require storage.
"""

# pylint: disable=protected-access,import-outside-toplevel,no-value-for-parameter,unused-argument

import secrets

from django.db import transaction
from django.test import override_settings

import pytest

from core import enums, factories
from core.enums import BlobStorageLocationChoices, CompressionTypeChoices
from core.services.tiered_storage import TieredStorageService, sha256_advisory_lock

# Generate encryption keys at module level for decorators
_TEST_ENCRYPTION_KEY = secrets.token_hex(32)
_TEST_ENCRYPTION_KEY_1 = secrets.token_hex(32)
_TEST_ENCRYPTION_KEY_2 = secrets.token_hex(32)


class TestTieredStorageServiceUnit:
    """Pure unit tests for TieredStorageService (no DB, no storage)."""

    def test_compute_storage_key(self):
        """Storage keys encode (key_id, sha)."""
        sha256 = bytes.fromhex(
            "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        )

        assert TieredStorageService.compute_storage_key(sha256, 0) == (
            "blobs/0/abc/"
            "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        )
        assert TieredStorageService.compute_storage_key(sha256, 2) == (
            "blobs/2/abc/"
            "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        )

    def test_compute_storage_key_different_prefixes(self):
        """Different SHA256 hashes produce different sha-prefix directories."""
        sha1 = bytes.fromhex("abc" + "0" * 61)
        sha2 = bytes.fromhex("def" + "0" * 61)

        assert TieredStorageService.compute_storage_key(sha1, 0).startswith(
            "blobs/0/abc/"
        )
        assert TieredStorageService.compute_storage_key(sha2, 0).startswith(
            "blobs/0/def/"
        )

    def test_encrypt_decrypt_no_keys(self):
        """Test that encryption is a passthrough when no keys are configured."""
        service = TieredStorageService()
        service.encryption_keys = {}
        service.active_key_id = 0

        data = b"test data"
        encrypted, key_id = service.encrypt(data)

        assert encrypted == data  # Passthrough
        assert key_id == 0

        decrypted = service.decrypt(encrypted, key_id)
        assert decrypted == data

    def test_encrypt_decrypt_with_key(self):
        """Test encryption and decryption with an AES-GCM key."""
        service = TieredStorageService()
        key = secrets.token_hex(32)
        service.encryption_keys = {"1": key}
        service.active_key_id = 1

        data = b"test data to encrypt"
        encrypted, key_id = service.encrypt(data)

        assert encrypted != data  # Should be encrypted
        assert key_id == 1

        decrypted = service.decrypt(encrypted, key_id)
        assert decrypted == data

    def test_encrypt_passthrough_when_active_key_zero(self):
        """Test that encryption is passthrough when active_key_id=0 even with keys configured."""
        service = TieredStorageService()
        key = secrets.token_hex(32)
        service.encryption_keys = {"1": key}
        service.active_key_id = 0  # Disabled

        data = b"test data"
        encrypted, key_id = service.encrypt(data)

        assert encrypted == data  # Passthrough
        assert key_id == 0

    def test_decrypt_with_invalid_key_id(self):
        """Test that decryption fails with invalid key_id."""
        service = TieredStorageService()
        service.encryption_keys = {}

        with pytest.raises(ValueError, match="key_id 5 not found"):
            service.decrypt(b"data", 5)

    def test_encrypt_with_missing_active_key(self):
        """Test that encrypt fails if active_key_id not in encryption_keys."""
        service = TieredStorageService()
        service.encryption_keys = {"1": secrets.token_hex(32)}
        service.active_key_id = 99  # Not in keys

        with pytest.raises(ValueError, match="key_id 99 not found"):
            service.encrypt(b"test data")

    def test_decrypt_with_corrupted_data(self):
        """decrypt fails with InvalidTag on corrupted ciphertext."""
        from cryptography.exceptions import InvalidTag

        service = TieredStorageService()
        service.encryption_keys = {"1": secrets.token_hex(32)}
        service.active_key_id = 1

        with pytest.raises(InvalidTag):
            service.decrypt(b"\x00" * 64, 1)

    def test_decrypt_with_wrong_key(self):
        """decrypt fails with InvalidTag when key doesn't match."""
        from cryptography.exceptions import InvalidTag

        service = TieredStorageService()
        service.encryption_keys = {
            "1": secrets.token_hex(32),
            "2": secrets.token_hex(32),
        }

        service.active_key_id = 1
        encrypted, _ = service.encrypt(b"test data")

        with pytest.raises(InvalidTag):
            service.decrypt(encrypted, 2)

    def test_encrypt_empty_data(self):
        """Test that encryption works with empty data."""
        service = TieredStorageService()
        key = secrets.token_hex(32)
        service.encryption_keys = {"1": key}
        service.active_key_id = 1

        encrypted, key_id = service.encrypt(b"")
        assert key_id == 1
        assert encrypted != b""  # AES-GCM adds nonce + tag

        decrypted = service.decrypt(encrypted, key_id)
        assert decrypted == b""

    def test_encrypt_with_key_rotation(self):
        """Test that we can encrypt with new key and decrypt with old key."""
        service = TieredStorageService()
        old_key = secrets.token_hex(32)
        new_key = secrets.token_hex(32)

        # Both keys available
        service.encryption_keys = {"1": old_key, "2": new_key}

        # Data encrypted with old key
        service.active_key_id = 1
        data = b"test data"
        encrypted_old, old_key_id = service.encrypt(data)
        assert old_key_id == 1

        # Now use new key for encryption
        service.active_key_id = 2
        encrypted_new, new_key_id = service.encrypt(data)
        assert new_key_id == 2

        # Both can still be decrypted
        assert service.decrypt(encrypted_old, 1) == data
        assert service.decrypt(encrypted_new, 2) == data


@pytest.mark.django_db
class TestTieredStorageDB:
    """Tests that require database but not object storage."""

    def test_blob_default_storage_location(self):
        """Test that new blobs default to POSTGRES storage location."""
        mailbox = factories.MailboxFactory()
        blob = mailbox.create_blob(
            content=b"test content",
            content_type="text/plain",
        )

        assert blob.storage_location == BlobStorageLocationChoices.POSTGRES
        assert blob.encryption_key_id == 0
        assert blob.raw_content is not None

    def test_zstd_compresses_repetitive_content(self):
        """1024 'a's should compress to a tiny PG payload."""
        import pyzstd

        content = b"a" * 1024
        mailbox = factories.MailboxFactory()
        blob = mailbox.create_blob(content=content, content_type="text/plain")

        assert blob.compression == CompressionTypeChoices.ZSTD
        assert blob.size == 1024
        assert blob.encryption_key_id == 0
        # raw_content is the compressed bytes verbatim (no encryption).
        assert blob.size_compressed == len(bytes(blob.raw_content))
        assert blob.size_compressed == len(pyzstd.compress(content, level_or_option=3))
        # Sanity floor: zstd on a single-byte run is well under 50 bytes.
        assert blob.size_compressed < 50, blob.size_compressed

    @override_settings(MESSAGES_BLOB_COMPRESS="none")
    def test_no_compression_preserves_size(self):
        """MESSAGES_BLOB_COMPRESS=none stores plaintext bytes as-is."""
        content = b"a" * 1024
        mailbox = factories.MailboxFactory()
        blob = mailbox.create_blob(content=content, content_type="text/plain")

        assert blob.size == 1024
        assert blob.size_compressed == 1024
        assert bytes(blob.raw_content) == content

    @override_settings(
        MESSAGES_BLOB_ENCRYPTION_KEYS={"1": _TEST_ENCRYPTION_KEY},
        MESSAGES_BLOB_ENCRYPTION_ACTIVE_KEY_ID=1,
    )
    def test_encryption_adds_exactly_aesgcm_overhead(self):
        """raw_content = compressed bytes + 28 (AES-GCM nonce 12 + tag 16)."""
        import pyzstd

        content = b"a" * 1024
        pure_compressed_len = len(pyzstd.compress(content, level_or_option=3))

        mailbox = factories.MailboxFactory()
        blob = mailbox.create_blob(content=content, content_type="text/plain")

        assert blob.encryption_key_id == 1
        assert blob.size_compressed == pure_compressed_len + 28
        # And content still round-trips cleanly.
        assert blob.get_content() == content

    @override_settings(
        MESSAGES_BLOB_COMPRESS="none",
        MESSAGES_BLOB_ENCRYPTION_KEYS={"1": _TEST_ENCRYPTION_KEY},
        MESSAGES_BLOB_ENCRYPTION_ACTIVE_KEY_ID=1,
    )
    def test_encryption_with_no_compression_size(self):
        """With MESSAGES_BLOB_COMPRESS=none: raw_content = plaintext_size + 28."""
        content = b"a" * 1024
        mailbox = factories.MailboxFactory()
        blob = mailbox.create_blob(content=content, content_type="text/plain")

        assert blob.encryption_key_id == 1
        assert blob.size_compressed == 1024 + 28
        assert blob.get_content() == content

    def test_blob_get_content_from_postgres(self):
        """Test getting content from a blob stored in PostgreSQL."""
        mailbox = factories.MailboxFactory()
        content = b"Hello World" * 100

        blob = mailbox.create_blob(content=content, content_type="text/plain")

        assert blob.storage_location == BlobStorageLocationChoices.POSTGRES
        assert blob.get_content() == content

    def test_blob_get_content_raises_when_no_raw_content(self):
        """Test that get_content raises when raw_content is None for POSTGRES location."""
        mailbox = factories.MailboxFactory()
        blob = mailbox.create_blob(content=b"test", content_type="text/plain")

        blob.raw_content = None
        blob.save(update_fields=["raw_content"])

        with pytest.raises(ValueError, match="has no content in PostgreSQL"):
            blob.get_content()

    def test_same_content_same_sha256(self):
        """Test that identical content produces identical SHA256."""
        mailbox1 = factories.MailboxFactory()
        mailbox2 = factories.MailboxFactory()
        content = b"identical content for both blobs"

        blob1 = mailbox1.create_blob(content=content, content_type="text/plain")
        blob2 = mailbox2.create_blob(content=content, content_type="text/plain")

        assert blob1.sha256 == blob2.sha256
        assert blob1.id != blob2.id

    def test_get_existing_sibling(self):
        """get_existing_sibling returns ``(key_id, compression)`` of any
        OBJECT_STORAGE sibling, or None if there is none.

        Compression is intentionally NOT a filter — a sha256 has exactly
        one stored object cluster-wide, and new uploads adopt its
        compression rather than creating a parallel object.
        """
        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        blob = mailbox.create_blob(content=b"test content", content_type="text/plain")

        assert service.get_existing_sibling(bytes(blob.sha256)) is None

        blob.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
        blob.encryption_key_id = 7
        blob.compression = CompressionTypeChoices.ZSTD
        blob.save()

        assert service.get_existing_sibling(bytes(blob.sha256)) == (
            7,
            CompressionTypeChoices.ZSTD,
        )


@pytest.mark.django_db
class TestTieredStorageE2E:
    """End-to-end tests that hit real MinIO object storage."""

    def test_upload_download_roundtrip(self):
        """Test uploading a blob to MinIO and downloading it back."""
        import pyzstd

        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        content = b"Hello, this is e2e test content for tiered storage!" * 10

        blob = mailbox.create_blob(content=content, content_type="text/plain")
        storage_key = TieredStorageService.compute_storage_key_for_blob(blob)

        try:
            service.upload_blob(blob)
            assert service.storage.exists(storage_key)

            downloaded = service.download_blob(blob)
            decompressed = pyzstd.decompress(downloaded)
            assert decompressed == content
        finally:
            service.storage.delete(storage_key)

    @override_settings(
        MESSAGES_BLOB_ENCRYPTION_KEYS={"1": _TEST_ENCRYPTION_KEY},
        MESSAGES_BLOB_ENCRYPTION_ACTIVE_KEY_ID=1,
    )
    def test_upload_download_with_encryption(self):
        """Test upload/download roundtrip with encryption enabled."""
        import pyzstd

        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        content = b"Encrypted content for e2e test" * 10

        # create_blob() should automatically encrypt when keys are configured
        blob = mailbox.create_blob(content=content, content_type="text/plain")
        assert blob.encryption_key_id > 0  # Should be encrypted
        storage_key = TieredStorageService.compute_storage_key_for_blob(blob)

        try:
            service.upload_blob(blob)
            assert service.storage.exists(storage_key)

            # Download returns decrypted but compressed content
            downloaded = service.download_blob(blob)
            decompressed = pyzstd.decompress(downloaded)
            assert decompressed == content
        finally:
            service.storage.delete(storage_key)

    @pytest.mark.django_db(transaction=True)
    def test_deduplication_single_upload(self):
        """Test that two blobs with same content result in single storage object."""
        service = TieredStorageService()
        mailbox1 = factories.MailboxFactory()
        mailbox2 = factories.MailboxFactory()
        content = b"Identical content for deduplication test" * 5

        blob1 = mailbox1.create_blob(content=content, content_type="text/plain")
        blob2 = mailbox2.create_blob(content=content, content_type="text/plain")

        assert blob1.sha256 == blob2.sha256
        storage_key = TieredStorageService.compute_storage_key_for_blob(blob1)

        try:
            # Upload first blob
            service.upload_blob(blob1)
            blob1.storage_location = enums.BlobStorageLocationChoices.OBJECT_STORAGE
            blob1.save()

            assert service.storage.exists(storage_key)

            # Upload second blob - should detect duplicate
            key_id, compression = service.upload_blob(blob2)
            blob2.storage_location = enums.BlobStorageLocationChoices.OBJECT_STORAGE
            blob2.encryption_key_id = key_id
            blob2.compression = compression
            blob2.save()

            # Still only one object
            assert service.storage.exists(storage_key)

            # Delete first blob - storage object should remain
            blob1.delete()
            assert service.storage.exists(storage_key)

            # Delete second blob - now orphaned
            blob2.delete()
            assert not service.storage.exists(storage_key)
        finally:
            # Cleanup in case of failure
            if service.storage.exists(storage_key):
                service.storage.delete(storage_key)

    @pytest.mark.django_db(transaction=True)
    def test_full_offload_workflow(self):
        """Test the complete offload workflow: create blob, offload, read content."""
        from core.services.tiered_storage_tasks import (
            offload_single_blob_task,
        )

        mailbox = factories.MailboxFactory()
        content = b"Content for full offload workflow test" * 20

        blob = mailbox.create_blob(content=content, content_type="text/plain")
        assert blob.storage_location == enums.BlobStorageLocationChoices.POSTGRES

        try:
            result = offload_single_blob_task(str(blob.id))
            assert result["status"] == "success"

            blob.refresh_from_db()
            assert (
                blob.storage_location == enums.BlobStorageLocationChoices.OBJECT_STORAGE
            )
            assert blob.raw_content is None

            retrieved = blob.get_content()
            assert retrieved == content
        finally:
            blob.delete()

    @override_settings(
        MESSAGES_BLOB_ENCRYPTION_KEYS={"1": _TEST_ENCRYPTION_KEY},
        MESSAGES_BLOB_ENCRYPTION_ACTIVE_KEY_ID=1,
    )
    @pytest.mark.django_db(transaction=True)
    def test_offload_with_encryption_roundtrip(self):
        """
        Test full offload workflow with encryption: create encrypted blob,
        offload to storage, read back content.

        This is a critical regression test for the double-encryption bug.
        """
        from core.services.tiered_storage_tasks import (
            offload_single_blob_task,
        )

        mailbox = factories.MailboxFactory()
        original_content = b"Test content for encryption offload roundtrip" * 50

        # create_blob() should automatically encrypt when keys are configured
        blob = mailbox.create_blob(content=original_content, content_type="text/plain")
        assert blob.encryption_key_id > 0  # Should be encrypted

        try:
            result = offload_single_blob_task(str(blob.id))
            assert result["status"] == "success"

            blob.refresh_from_db()
            assert (
                blob.storage_location == enums.BlobStorageLocationChoices.OBJECT_STORAGE
            )
            assert blob.raw_content is None
            assert blob.encryption_key_id > 0  # Preserved

            # Critical: content should still be readable
            retrieved_content = blob.get_content()
            assert retrieved_content == original_content
        finally:
            blob.delete()

    @pytest.mark.django_db(transaction=True)
    def test_delete_if_orphaned(self):
        """delete_if_orphaned only deletes when no blob references (sha, key_id)."""
        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        blob = mailbox.create_blob(content=b"test content", content_type="text/plain")
        storage_key = TieredStorageService.compute_storage_key_for_blob(blob)

        try:
            service.upload_blob(blob)
            blob.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
            blob.save()

            # Still referenced by the blob row → no-op.
            assert (
                service.delete_if_orphaned(bytes(blob.sha256), blob.encryption_key_id)
                is False
            )
            assert service.storage.exists(storage_key)

            # Deleting the blob fires the cleanup signal which removes the object.
            blob.delete()
            assert not service.storage.exists(storage_key)
        finally:
            if service.storage.exists(storage_key):
                service.storage.delete(storage_key)

    def test_upload_creates_storage_object(self):
        """upload_blob writes to the (sha, key_id) path."""
        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        blob = mailbox.create_blob(content=b"test", content_type="text/plain")
        storage_key = TieredStorageService.compute_storage_key_for_blob(blob)

        assert not service.storage.exists(storage_key)
        try:
            service.upload_blob(blob)
            assert service.storage.exists(storage_key)
        finally:
            service.storage.delete(storage_key)

    def test_upload_falls_through_when_storage_object_missing(self):
        """If a sibling DB row says OBJECT_STORAGE but the S3 object is gone
        (manual deletion, lifecycle expiry, etc.), upload_blob must NOT trust
        the dedup fast-path — it has to upload from raw_content so the new
        row doesn't end up pointing at nothing."""
        service = TieredStorageService()
        mailbox_a = factories.MailboxFactory()
        mailbox_b = factories.MailboxFactory()
        content = b"shared content for missing-storage fallback test" * 5

        # Blob A: upload then mark OBJECT_STORAGE.
        blob_a = mailbox_a.create_blob(content=content, content_type="text/plain")
        service.upload_blob(blob_a)
        blob_a.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
        blob_a.raw_content = None
        blob_a.save()

        path_a = TieredStorageService.compute_storage_key_for_blob(blob_a)
        assert service.storage.exists(path_a)

        # Simulate the storage object disappearing out of band.
        service.storage.delete(path_a)
        assert not service.storage.exists(path_a)

        # Blob B has the same content; dedup would normally short-circuit
        # against blob A, but the storage-existence guard must force a real
        # upload so B's data lands somewhere.
        blob_b = mailbox_b.create_blob(content=content, content_type="text/plain")
        path_b = TieredStorageService.compute_storage_key_for_blob(blob_b)

        try:
            returned_key_id, returned_compression = service.upload_blob(blob_b)
            assert returned_key_id == blob_b.encryption_key_id
            assert returned_compression == blob_b.compression
            assert service.storage.exists(path_b)
        finally:
            for k in (path_a, path_b):
                if service.storage.exists(k):
                    service.storage.delete(k)

    def test_download_missing_blob_raises(self):
        """Test that download_blob raises FileNotFoundError for missing blob."""
        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        blob = mailbox.create_blob(content=b"test", content_type="text/plain")

        # Mark as in object storage but don't actually upload
        blob.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
        blob.save()

        with pytest.raises(FileNotFoundError):
            service.download_blob(blob)

    def test_upload_blob_without_content_raises(self):
        """Test that upload_blob raises ValueError when blob has no content."""
        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        blob = mailbox.create_blob(content=b"test", content_type="text/plain")
        blob.raw_content = None
        blob.save()

        with pytest.raises(ValueError, match="has no raw_content"):
            service.upload_blob(blob)

    def test_deduplication_with_different_encryption_keys(self):
        """
        Test deduplication when blobs were encrypted with different keys.

        When two blobs have the same content but were encrypted with different
        keys, deduplication should still work - the second blob uses the
        storage object from the first blob (and its encryption key).
        """
        content = b"Same content, different keys" * 20

        # Create first blob with key 1 active
        with override_settings(
            MESSAGES_BLOB_ENCRYPTION_KEYS={"1": _TEST_ENCRYPTION_KEY_1},
            MESSAGES_BLOB_ENCRYPTION_ACTIVE_KEY_ID=1,
        ):
            mailbox1 = factories.MailboxFactory()
            # create_blob() should automatically encrypt with key 1
            blob1 = mailbox1.create_blob(content=content, content_type="text/plain")
            assert blob1.encryption_key_id == 1

        # Later, we switch to a second key, while keeping the first key available for reading
        with override_settings(
            MESSAGES_BLOB_ENCRYPTION_KEYS={
                "1": _TEST_ENCRYPTION_KEY_1,
                "2": _TEST_ENCRYPTION_KEY_2,
            },
            MESSAGES_BLOB_ENCRYPTION_ACTIVE_KEY_ID=2,
        ):
            mailbox2 = factories.MailboxFactory()
            # create_blob() should automatically encrypt with key 2
            blob2 = mailbox2.create_blob(content=content, content_type="text/plain")
            assert blob2.encryption_key_id == 2

            # Same SHA256 (computed on original content)
            assert blob1.sha256 == blob2.sha256
            storage_key = TieredStorageService.compute_storage_key_for_blob(blob1)

            try:
                service = TieredStorageService()
                # Upload first blob
                returned_key_id1, returned_compression1 = service.upload_blob(blob1)
                blob1.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
                blob1.encryption_key_id = returned_key_id1
                blob1.compression = returned_compression1
                blob1.raw_content = None
                blob1.save()

                assert returned_key_id1 == 1  # Original key

                # Upload second blob - dedup should kick in
                returned_key_id2, returned_compression2 = service.upload_blob(blob2)
                blob2.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
                # Gets key 1 from first blob!
                blob2.encryption_key_id = returned_key_id2
                blob2.compression = returned_compression2
                blob2.raw_content = None
                blob2.save()

                # Deduplication returns the EXISTING blob's key_id
                assert (
                    returned_key_id2 == 1
                )  # Not 2! Until we have re-encrypted all blobs with the management command

                # Both blobs should be readable with key 1
                assert blob1.get_content() == content
                assert blob2.get_content() == content
            finally:
                service = TieredStorageService()
                if service.storage and service.storage.exists(storage_key):
                    service.storage.delete(storage_key)

    @pytest.mark.django_db(transaction=True)
    def test_deduplication_adopts_existing_compression(self):
        """A new blob created with a different compression than the
        already-stored sibling MUST adopt the sibling's compression on
        offload — otherwise restore() would decompress the wrong way."""
        from core.services.tiered_storage_tasks import offload_single_blob_task

        content = b"shared content for cross-compression dedup" * 5

        # First blob lands with ZSTD and gets offloaded.
        mailbox1 = factories.MailboxFactory()
        with override_settings(MESSAGES_BLOB_COMPRESS="zstd:3"):
            blob1 = mailbox1.create_blob(content=content, content_type="text/plain")
        assert blob1.compression == CompressionTypeChoices.ZSTD
        storage_key = TieredStorageService.compute_storage_key_for_blob(blob1)

        try:
            assert offload_single_blob_task(str(blob1.id))["status"] == "success"

            # Operator flips the global default to NONE; a second mailbox
            # gets the same content compressed-as-NONE.
            mailbox2 = factories.MailboxFactory()
            with override_settings(MESSAGES_BLOB_COMPRESS="none"):
                blob2 = mailbox2.create_blob(content=content, content_type="text/plain")
            assert blob2.compression == CompressionTypeChoices.NONE

            assert offload_single_blob_task(str(blob2.id))["status"] == "success"

            blob2.refresh_from_db()
            # Adopted ZSTD from blob1 — otherwise blob2 would try to read
            # the ZSTD-compressed bytes as plaintext on get_content().
            assert blob2.compression == CompressionTypeChoices.ZSTD
            assert blob2.get_content() == content

            # Both rows resolve to the same storage object.
            assert (
                TieredStorageService.compute_storage_key_for_blob(blob2) == storage_key
            )
        finally:
            service = TieredStorageService()
            if service.storage and service.storage.exists(storage_key):
                service.storage.delete(storage_key)


@pytest.mark.django_db(transaction=True)
class TestTieredStorageCascadeDelete:
    """Tests that S3 cleanup works during cascade and bulk deletes."""

    def test_cascade_delete_triggers_storage_cleanup(self):
        """Test that deleting a mailbox cascade-deletes blobs and cleans S3."""
        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        blob = mailbox.create_blob(content=b"cascade test", content_type="text/plain")

        storage_key = TieredStorageService.compute_storage_key_for_blob(blob)

        try:
            service.upload_blob(blob)
            blob.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
            blob.raw_content = None
            blob.save()

            assert service.storage.exists(storage_key)

            # CASCADE delete via mailbox - Blob.delete() is NOT called,
            # but the post_delete signal should handle S3 cleanup.
            mailbox.delete()

            assert not service.storage.exists(storage_key)
        finally:
            if service.storage.exists(storage_key):
                service.storage.delete(storage_key)

    def test_queryset_delete_triggers_storage_cleanup(self):
        """Test that QuerySet.delete() triggers S3 cleanup via signal."""
        from core.models import Blob as BlobModel

        service = TieredStorageService()
        mailbox = factories.MailboxFactory()
        blob = mailbox.create_blob(
            content=b"queryset delete test", content_type="text/plain"
        )

        storage_key = TieredStorageService.compute_storage_key_for_blob(blob)

        try:
            service.upload_blob(blob)
            blob.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
            blob.raw_content = None
            blob.save()

            assert service.storage.exists(storage_key)

            # Bulk delete via QuerySet - Blob.delete() is NOT called,
            # but the post_delete signal should handle S3 cleanup.
            BlobModel.objects.filter(id=blob.id).delete()

            assert not service.storage.exists(storage_key)
        finally:
            if service.storage.exists(storage_key):
                service.storage.delete(storage_key)


@pytest.mark.django_db
class TestTieredStorageKeyRotation:
    """Tests for encryption key rotation scenarios."""

    def test_key_rotation_postgres_blob(self):
        """Test re-encrypting a PostgreSQL blob with a new key."""
        import pyzstd

        service = TieredStorageService()
        old_key = secrets.token_hex(32)
        new_key = secrets.token_hex(32)

        mailbox = factories.MailboxFactory()
        original_content = b"Content for key rotation test" * 20

        # Create blob and encrypt with old key
        blob = mailbox.create_blob(content=original_content, content_type="text/plain")
        compressed = bytes(blob.raw_content)

        service.encryption_keys = {"1": old_key}
        service.active_key_id = 1
        encrypted_old, old_key_id = service.encrypt(compressed)
        blob.raw_content = encrypted_old
        blob.encryption_key_id = old_key_id
        blob.save()

        # Verify we can decrypt with old key
        decrypted = service.decrypt(bytes(blob.raw_content), blob.encryption_key_id)
        assert pyzstd.decompress(decrypted) == original_content

        # Add new key and set as active
        service.encryption_keys = {"1": old_key, "2": new_key}
        service.active_key_id = 2

        # Re-encrypt: decrypt with old key, encrypt with new key
        decrypted = service.decrypt(bytes(blob.raw_content), blob.encryption_key_id)
        encrypted_new, new_key_id = service.encrypt(decrypted)
        blob.raw_content = encrypted_new
        blob.encryption_key_id = new_key_id
        blob.save()

        assert blob.encryption_key_id == 2

        # Verify content still accessible
        decrypted = service.decrypt(bytes(blob.raw_content), blob.encryption_key_id)
        assert pyzstd.decompress(decrypted) == original_content

    def test_key_rotation_object_storage_blob(self):
        """rotate_blob moves the storage object from old path to new path."""
        import pyzstd

        service = TieredStorageService()
        old_key = secrets.token_hex(32)
        new_key = secrets.token_hex(32)

        mailbox = factories.MailboxFactory()
        original_content = b"Content for object storage key rotation" * 20

        blob = mailbox.create_blob(content=original_content, content_type="text/plain")
        compressed = bytes(blob.raw_content)

        service.encryption_keys = {"1": old_key}
        service.active_key_id = 1
        encrypted_old, old_key_id = service.encrypt(compressed)
        blob.raw_content = encrypted_old
        blob.encryption_key_id = old_key_id
        blob.save()

        old_path = TieredStorageService.compute_storage_key_for_blob(blob)
        new_path = TieredStorageService.compute_storage_key(bytes(blob.sha256), 2)

        try:
            service.upload_blob(blob)
            blob.storage_location = BlobStorageLocationChoices.OBJECT_STORAGE
            blob.raw_content = None
            blob.save()

            service.encryption_keys = {"1": old_key, "2": new_key}
            service.active_key_id = 2

            with transaction.atomic(), sha256_advisory_lock(bytes(blob.sha256)):
                assert service.rotate_blob(blob, 2) is True

            blob.refresh_from_db()
            assert blob.encryption_key_id == 2
            # Old path is gone, new path is the canonical one.
            assert not service.storage.exists(old_path)
            assert service.storage.exists(new_path)

            downloaded = service.download_blob(blob)
            assert pyzstd.decompress(downloaded) == original_content
        finally:
            for k in (old_path, new_path):
                if service.storage.exists(k):
                    service.storage.delete(k)
