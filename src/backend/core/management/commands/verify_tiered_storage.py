"""
Django management command to verify tiered storage integrity.

This command checks the consistency between the Blob database records
and the object storage backend, and can optionally fix issues or
re-encrypt blobs with a new key (key rotation).
"""

import hashlib
from typing import Iterator

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction

from core.enums import BlobStorageLocationChoices
from core.models import Blob
from core.services.tiered_storage import TieredStorageService


class Command(BaseCommand):
    help = "Verify tiered storage integrity and manage encryption key rotation"

    def add_arguments(self, parser):
        parser.add_argument(
            "--mode",
            choices=["db-to-storage", "storage-to-db", "full"],
            default="full",
            help="Verification mode: db-to-storage (check DB records have storage backing), "
            "storage-to-db (find orphans in storage), or full (both)",
        )
        parser.add_argument(
            "--fix",
            action="store_true",
            help="Fix issues: delete orphans from storage (missing blobs are only reported)",
        )
        parser.add_argument(
            "--verify-hashes",
            action="store_true",
            help="Re-download and verify SHA256 hashes (slow, requires --mode=storage-to-db or full)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Limit number of items to check or re-encrypt (0=unlimited)",
        )
        parser.add_argument(
            "--re-encrypt",
            action="store_true",
            help="Re-encrypt all blobs with the active encryption key (MESSAGES_BLOB_ENCRYPTION_ACTIVE_KEY_ID). "
            "Use this for key rotation after adding a new key to MESSAGES_BLOB_ENCRYPTION_KEYS.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making changes (use with --re-encrypt)",
        )

    def handle(self, *args, **options):
        self.service = TieredStorageService()
        self.fix = options["fix"]
        self.verify_hashes = options["verify_hashes"]
        self.limit = options["limit"]
        self.dry_run = options["dry_run"]

        # Re-encrypt doesn't require object storage to be enabled (works for PostgreSQL too)
        if options["re_encrypt"]:
            self.re_encrypt_blobs()
            return

        # Verification modes require object storage
        if not self.service.enabled:
            self.stderr.write(
                self.style.ERROR(
                    "Object storage not configured. Configure message-blobs in STORAGES to enable."
                )
            )
            return

        mode = options["mode"]

        if mode in ["db-to-storage", "full"]:
            self.verify_db_to_storage()

        if mode in ["storage-to-db", "full"]:
            self.verify_storage_to_db()

    def verify_db_to_storage(self):
        """Iterate blob DB rows -> verify all expected objects exist in storage."""
        self.stdout.write(
            self.style.MIGRATE_HEADING("\n=== DB to Storage Verification ===")
        )
        self.stdout.write(
            "Checking that all blobs marked as OBJECT_STORAGE exist in storage..."
        )

        missing_count = 0
        checked_count = 0

        queryset = Blob.objects.filter(
            storage_location=BlobStorageLocationChoices.OBJECT_STORAGE
        )

        if self.limit > 0:
            queryset = queryset[: self.limit]

        for blob in queryset.iterator(chunk_size=1000):
            checked_count += 1
            key = self.service.compute_storage_key(bytes(blob.sha256))

            if not self.service.storage.exists(key):
                missing_count += 1
                # Print to stderr - data may be lost, manual intervention required
                self.stderr.write(
                    self.style.ERROR(
                        f"MISSING: Blob {blob.id} -> {key} "
                        f"(sha256: {blob.sha256.hex()}, size: {blob.size} bytes)"
                    )
                )

            if checked_count % 1000 == 0:
                self.stdout.write(f"  Checked {checked_count} blobs...")

        self.stdout.write("")
        self.stdout.write(f"Checked: {checked_count} blobs")
        if missing_count == 0:
            self.stdout.write(
                self.style.SUCCESS("Result: All blobs have storage backing")
            )
        else:
            self.stdout.write(
                self.style.ERROR(f"Result: {missing_count} blobs missing from storage")
            )

    def verify_storage_to_db(self):
        """Iterate storage objects -> find orphans and optionally verify hashes."""
        self.stdout.write(
            self.style.MIGRATE_HEADING("\n=== Storage to DB Verification ===")
        )
        self.stdout.write("Checking storage objects for orphans and integrity...")

        orphan_count = 0
        invalid_count = 0
        hash_mismatch_count = 0
        checked_count = 0

        # List all objects in the blobs/ prefix
        try:
            objects = self._list_storage_objects("blobs/")
        except Exception as e:  # pylint: disable=broad-except
            self.stderr.write(self.style.ERROR(f"Failed to list storage objects: {e}"))
            return

        for obj_name in objects:
            if self.limit > 0 and checked_count >= self.limit:
                break

            checked_count += 1

            # Extract SHA256 from path: blobs/{sha[:3]}/{sha}
            parts = obj_name.split("/")
            if len(parts) < 3:
                invalid_count += 1
                self.stdout.write(self.style.WARNING(f"INVALID PATH: {obj_name}"))
                continue

            sha_hex = parts[-1]
            try:
                sha_bytes = bytes.fromhex(sha_hex)
            except ValueError:
                invalid_count += 1
                self.stdout.write(self.style.WARNING(f"INVALID SHA256: {obj_name}"))
                continue

            # Check if any blob references this object
            refs_exist = Blob.objects.filter(
                sha256=sha_bytes,
                storage_location=BlobStorageLocationChoices.OBJECT_STORAGE,
            ).exists()

            if not refs_exist:
                orphan_count += 1
                self.stdout.write(self.style.WARNING(f"ORPHAN: {obj_name}"))
                if self.fix:
                    try:
                        self.service.storage.delete(obj_name)
                        self.stdout.write(
                            self.style.SUCCESS(f"  -> Deleted orphan {obj_name}")
                        )
                    except Exception as e:  # pylint: disable=broad-except
                        self.stdout.write(
                            self.style.ERROR(f"  -> Failed to delete: {e}")
                        )

            # Optionally verify hash
            if self.verify_hashes and refs_exist:
                if not self._verify_blob_hash(obj_name, sha_bytes):
                    hash_mismatch_count += 1

            if checked_count % 100 == 0:
                self.stdout.write(f"  Checked {checked_count} objects...")

        self.stdout.write("")
        self.stdout.write(f"Checked: {checked_count} storage objects")
        self.stdout.write(f"Orphans: {orphan_count}")
        self.stdout.write(f"Invalid paths: {invalid_count}")
        if self.verify_hashes:
            self.stdout.write(f"Hash mismatches: {hash_mismatch_count}")

        if orphan_count == 0 and invalid_count == 0 and hash_mismatch_count == 0:
            self.stdout.write(self.style.SUCCESS("Result: Storage is consistent"))
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Result: Found {orphan_count + invalid_count + hash_mismatch_count} issues"
                )
            )

    def _list_storage_objects(self, prefix: str) -> Iterator[str]:
        """
        List all objects with given prefix.

        This is a generator that yields object names.
        Implementation depends on the storage backend.
        """
        # Try to use listdir if available (django-storages S3)
        storage = self.service.storage

        # For S3-compatible storage with boto3
        if hasattr(storage, "bucket"):
            # Direct boto3 access
            bucket = storage.bucket
            paginator = bucket.meta.client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket.name, Prefix=prefix):
                for obj in page.get("Contents", []):
                    yield obj["Key"]
        elif hasattr(storage, "listdir"):
            # Fallback to Django's listdir (may not work for all backends)
            # This is recursive and may be slow
            def _walk(path):
                dirs, files = storage.listdir(path)
                for f in files:
                    yield f"{path}/{f}" if path else f
                for d in dirs:
                    full_path = f"{path}/{d}" if path else d
                    yield from _walk(full_path)

            yield from _walk(prefix.rstrip("/"))
        else:
            raise NotImplementedError(
                "Storage backend does not support object listing. "
                "Use a S3-compatible backend."
            )

    def _verify_blob_hash(self, obj_name: str, expected_sha_bytes: bytes) -> bool:
        """
        Download, decrypt, decompress, and verify the hash of a blob.

        Returns True if hash matches, False otherwise.
        """
        try:
            # Get a blob to know the encryption key_id and compression
            blob = Blob.objects.filter(
                sha256=expected_sha_bytes,
                storage_location=BlobStorageLocationChoices.OBJECT_STORAGE,
            ).first()

            if not blob:
                return True  # No blob to verify against

            # Download and decrypt
            with self.service.storage.open(obj_name, "rb") as f:
                encrypted = f.read()

            decrypted = self.service.decrypt(encrypted, blob.encryption_key_id)

            # The decrypted content is still compressed
            # We need to decompress to verify the original hash
            import pyzstd

            from core.enums import CompressionTypeChoices

            if blob.compression == CompressionTypeChoices.ZSTD:
                original = pyzstd.decompress(decrypted)
            else:
                original = decrypted

            actual_hash = hashlib.sha256(original).digest()

            if actual_hash != expected_sha_bytes:
                self.stdout.write(
                    self.style.ERROR(
                        f"HASH MISMATCH: {obj_name}\n"
                        f"  Expected: {expected_sha_bytes.hex()}\n"
                        f"  Actual:   {actual_hash.hex()}"
                    )
                )
                return False

            return True

        except Exception as e:  # pylint: disable=broad-except
            self.stdout.write(self.style.ERROR(f"VERIFY ERROR: {obj_name} - {e}"))
            return False

    def re_encrypt_blobs(self):
        """
        Re-encrypt all blobs with the active encryption key.

        This is used for key rotation:
        1. Add new key to MESSAGES_BLOB_ENCRYPTION_KEYS dict: {"1": "old", "2": "new"}
        2. Set MESSAGES_BLOB_ENCRYPTION_ACTIVE_KEY_ID=2 (the new key)
        3. Run this command to re-encrypt all blobs with the new key
        4. Once complete, old keys can be removed from the dict
        """
        self.stdout.write(
            self.style.MIGRATE_HEADING("\n=== Re-encryption (Key Rotation) ===")
        )

        if not self.service.encryption_keys:
            self.stderr.write(
                self.style.ERROR(
                    "No encryption keys configured. Set MESSAGES_BLOB_ENCRYPTION_KEYS to enable encryption."
                )
            )
            return

        current_key_id = self.service.active_key_id
        self.stdout.write(f"Target encryption key_id: {current_key_id}")
        self.stdout.write(
            f"Available keys: {list(self.service.encryption_keys.keys())}"
        )

        # Validate that active_key_id exists in encryption_keys
        if current_key_id > 0:
            key_id_str = str(current_key_id)
            if key_id_str not in self.service.encryption_keys:
                self.stderr.write(
                    self.style.ERROR(
                        f"Active key_id {current_key_id} not found in MESSAGES_BLOB_ENCRYPTION_KEYS. "
                        f"Available keys: {list(self.service.encryption_keys.keys())}"
                    )
                )
                return

        if self.dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no changes will be made"))

        # Find blobs that need re-encryption (not using current key)
        # This includes key_id=0 (unencrypted) and key_id>1 (old keys)
        queryset = Blob.objects.exclude(encryption_key_id=current_key_id)

        if self.limit > 0:
            queryset = queryset[: self.limit]

        total_count = (
            queryset.count() if self.limit == 0 else min(self.limit, queryset.count())
        )
        self.stdout.write(f"Blobs to re-encrypt: {total_count}")

        if total_count == 0:
            self.stdout.write(
                self.style.SUCCESS("All blobs already use the current encryption key")
            )
            return

        success_count = 0
        error_count = 0
        skipped_count = 0

        for blob in queryset.iterator(chunk_size=100):
            try:
                result = self._re_encrypt_single_blob(blob, current_key_id)
                if result == "success":
                    success_count += 1
                elif result == "skipped":
                    skipped_count += 1
                else:
                    error_count += 1
            except Exception as e:  # pylint: disable=broad-except
                error_count += 1
                self.stderr.write(
                    self.style.ERROR(f"ERROR re-encrypting blob {blob.id}: {e}")
                )

            if (success_count + error_count + skipped_count) % 100 == 0:
                self.stdout.write(
                    f"  Progress: {success_count + error_count + skipped_count}/{total_count}"
                )

        self.stdout.write("")
        self.stdout.write(f"Re-encrypted: {success_count}")
        self.stdout.write(f"Skipped: {skipped_count}")
        self.stdout.write(f"Errors: {error_count}")

        if error_count == 0:
            self.stdout.write(self.style.SUCCESS("Key rotation completed successfully"))
        else:
            self.stdout.write(
                self.style.WARNING(f"Key rotation completed with {error_count} errors")
            )

    def _re_encrypt_single_blob(self, blob: Blob, target_key_id: int) -> str:
        """
        Re-encrypt a single blob with the target key.

        Args:
            blob: The blob to re-encrypt
            target_key_id: The encryption key ID to use for re-encryption

        Returns:
            "success", "skipped", or "error"
        """
        old_key_id = blob.encryption_key_id

        if self.dry_run:
            location = (
                "POSTGRES"
                if blob.storage_location == BlobStorageLocationChoices.POSTGRES
                else "OBJECT_STORAGE"
            )
            self.stdout.write(
                f"  Would re-encrypt blob {blob.id} ({location}): "
                f"key_id {old_key_id} -> {target_key_id}"
            )
            return "success"

        # Get the current encrypted/unencrypted content
        if blob.storage_location == BlobStorageLocationChoices.POSTGRES:
            if blob.raw_content is None:
                self.stdout.write(
                    self.style.WARNING(
                        f"  SKIP blob {blob.id}: no content in PostgreSQL"
                    )
                )
                return "skipped"

            # Decrypt with old key (or passthrough if key_id=0)
            decrypted = self.service.decrypt(bytes(blob.raw_content), old_key_id)

            # Re-encrypt with new key
            encrypted, new_key_id = self.service.encrypt(decrypted)

            # Update blob
            with transaction.atomic():
                blob.raw_content = encrypted
                blob.encryption_key_id = new_key_id
                blob.save(update_fields=["raw_content", "encryption_key_id"])

            self.stdout.write(
                f"  Re-encrypted blob {blob.id} (POSTGRES): "
                f"key_id {old_key_id} -> {new_key_id}"
            )

        else:
            # Object storage blob
            if not self.service.enabled:
                self.stdout.write(
                    self.style.WARNING(
                        f"  SKIP blob {blob.id}: object storage not configured"
                    )
                )
                return "skipped"

            # Download and decrypt
            storage_key = self.service.compute_storage_key(bytes(blob.sha256))
            try:
                with self.service.storage.open(storage_key, "rb") as f:
                    encrypted_content = f.read()
            except FileNotFoundError:
                self.stderr.write(
                    self.style.ERROR(
                        f"  ERROR blob {blob.id}: not found in storage at {storage_key}"
                    )
                )
                return "error"

            decrypted = self.service.decrypt(encrypted_content, old_key_id)

            # Re-encrypt with new key
            encrypted, new_key_id = self.service.encrypt(decrypted)

            # Upload new encrypted content (overwrites existing)
            self.service.storage.save(storage_key, ContentFile(encrypted))

            # Update blob metadata
            with transaction.atomic():
                blob.encryption_key_id = new_key_id
                blob.save(update_fields=["encryption_key_id"])

            self.stdout.write(
                f"  Re-encrypted blob {blob.id} (OBJECT_STORAGE): "
                f"key_id {old_key_id} -> {new_key_id}"
            )

        return "success"
