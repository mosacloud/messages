"""
Django management command to verify tiered storage integrity.

This command checks the consistency between the Blob database records
and the object storage backend, and can optionally fix issues or
re-store blobs to match the current configuration (key rotation +
optional rollback from object storage to PostgreSQL).
"""

import hashlib
from typing import Iterator

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

import pyzstd

from core.enums import BlobStorageLocationChoices, CompressionTypeChoices
from core.models import Blob
from core.services.tiered_storage import TieredStorageService, sha256_advisory_lock


class Command(BaseCommand):
    """Verify tiered storage integrity and manage encryption key rotation."""

    help = "Verify tiered storage integrity and manage encryption key rotation"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.service: TieredStorageService | None = None
        self.verify_hashes: bool = False
        self.limit: int = 0
        self.dry_run: bool = False
        self.start_after_key: str = ""

    def add_arguments(self, parser):
        parser.add_argument(
            "--mode",
            choices=["db-to-storage", "storage-to-db", "full"],
            default="full",
            help="Verification mode: db-to-storage (check DB records have storage backing), "
            "storage-to-db (find orphans in storage), or full (both)",
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
            "--re-store",
            action="store_true",
            help="Reconcile every blob with the current configuration: "
            "re-encrypt under whichever entry in MESSAGES_BLOBS_ENCRYPT_KEYS "
            "is flagged active=true, and (when MESSAGES_BLOBS_OFFLOAD_ENABLED "
            "is False) pull OBJECT_STORAGE blobs back into PostgreSQL. Use "
            "for key rotation, and for rolling tiered storage back.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making changes (use with --re-store)",
        )
        parser.add_argument(
            "--start-after-key",
            default="",
            help="Resume listing storage objects after this key (S3 lexicographic order). "
            "Pair with --limit to chunk a multi-million-object bucket across runs.",
        )

    def handle(self, *args, **options):
        self.service = TieredStorageService()
        self.verify_hashes = options["verify_hashes"]
        self.limit = options["limit"]
        self.dry_run = options["dry_run"]
        self.start_after_key = options["start_after_key"]

        # --re-store doesn't require object storage to be enabled
        # (works for PostgreSQL-only re-encryption too).
        if options["re_store"]:
            self.re_store_blobs()
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
            key = self.service.compute_storage_key_for_blob(blob)

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

            # Path format: blobs/{key_id}/{sha[:3]}/{sha}
            parts = obj_name.split("/")
            try:
                if len(parts) != 4 or parts[0] != "blobs":
                    raise ValueError("unexpected path shape")
                key_id = int(parts[1])
                sha_bytes = bytes.fromhex(parts[3])
            except ValueError:
                invalid_count += 1
                self.stdout.write(self.style.WARNING(f"INVALID PATH: {obj_name}"))
                continue

            # Compression isn't in the path — pull it (and ref existence)
            # from the DB row in one query.
            ref_compression = (
                Blob.objects.filter(
                    sha256=sha_bytes,
                    storage_location=BlobStorageLocationChoices.OBJECT_STORAGE,
                    encryption_key_id=key_id,
                )
                .values_list("compression", flat=True)
                .first()
            )
            refs_exist = ref_compression is not None

            if not refs_exist:
                orphan_count += 1
                self.stdout.write(self.style.WARNING(f"ORPHAN: {obj_name}"))

            if self.verify_hashes and refs_exist:
                if not self._verify_blob_hash(
                    obj_name, sha_bytes, key_id, ref_compression
                ):
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
        """List object keys under a prefix using boto3 pagination.

        Honors ``--start-after-key`` so a multi-million-object bucket
        can be checked in chunks (S3 lists in lexicographic key order;
        ``StartAfter`` resumes after the last key seen in a previous
        run). Combine with ``--limit`` to cap each chunk's wall time.
        """
        bucket = self.service.storage.bucket
        paginator = bucket.meta.client.get_paginator("list_objects_v2")
        kwargs = {"Bucket": bucket.name, "Prefix": prefix}
        if self.start_after_key:
            kwargs["StartAfter"] = self.start_after_key
        for page in paginator.paginate(**kwargs):
            for obj in page.get("Contents", []):
                yield obj["Key"]

    def _verify_blob_hash(
        self,
        obj_name: str,
        expected_sha_bytes: bytes,
        key_id: int,
        compression: int,
    ) -> bool:
        """Download the storage object, decrypt with ``key_id``, decompress
        per ``compression``, and check that
        ``sha256(decompressed) == expected_sha_bytes``."""
        try:
            with self.service.storage.open(obj_name, "rb") as f:
                encrypted = f.read()
            decrypted = self.service.decrypt(encrypted, key_id, expected_sha_bytes)

            if compression == CompressionTypeChoices.ZSTD:
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

    def re_store_blobs(self):
        """Reconcile every blob with the current configuration.

        Two operations, applied based on settings:

        - **Key rotation** (always): every row whose
          ``encryption_key_id`` differs from the entry currently
          flagged ``active=true`` in ``MESSAGES_BLOBS_ENCRYPT_KEYS``
          is re-encrypted under the active key.

        - **Restore** (only when ``MESSAGES_BLOBS_OFFLOAD_ENABLED`` is
          False): every ``OBJECT_STORAGE`` row is pulled back into
          PostgreSQL — the ciphertext is downloaded, decrypted under
          its original key, re-encrypted under the active key, and
          written to ``raw_content``. The S3 object is deleted once
          no rows reference it.

        Use cases:

        1. Key rotation. Add the new key alongside the old (with
           ``active=true`` on the new entry, omitted/false on the
           old), run this command (offload still on).
        2. Tiered-storage rollback. Set
           ``MESSAGES_BLOBS_OFFLOAD_ENABLED=False`` so new offloads
           stop, then run this command — every offloaded blob comes
           back into PG.
        """
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "\n=== Re-store (rotation + optional restore) ==="
            )
        )

        target_key_id = self.service.active_key_id
        offload_enabled = bool(settings.MESSAGES_BLOBS_OFFLOAD_ENABLED)
        restore_to_pg = not offload_enabled

        self.stdout.write(f"Target encryption key_id: {target_key_id}")
        if self.service.encryption_keys:
            self.stdout.write(
                f"Available keys: {list(self.service.encryption_keys.keys())}"
            )
        if restore_to_pg:
            self.stdout.write(
                self.style.WARNING(
                    "MESSAGES_BLOBS_OFFLOAD_ENABLED is False — "
                    "OBJECT_STORAGE blobs will be restored to PostgreSQL."
                )
            )
            if not self.service.enabled:
                # Need bucket access to read ciphertext on the way home.
                self.stderr.write(
                    self.style.ERROR(
                        "Object storage is not configured but OBJECT_STORAGE "
                        "rows exist. Configure STORAGE_MESSAGES_BLOBS_* to "
                        "let restore download them, or accept that those "
                        "blobs cannot be reached."
                    )
                )
                return

        # Active key must be in the dict if it's non-zero (passthrough at 0).
        if target_key_id > 0 and str(target_key_id) not in self.service.encryption_keys:
            self.stderr.write(
                self.style.ERROR(
                    f"Active key_id {target_key_id} not found in MESSAGES_BLOBS_ENCRYPT_KEYS. "
                    f"Available keys: {list(self.service.encryption_keys.keys())}"
                )
            )
            return

        if self.dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no changes will be made"))

        # Worklist construction.
        # - POSTGRES rows: every row not at the active key needs row-level
        #   rotation. One unit per row.
        # - OBJECT_STORAGE rows:
        #   * Restore mode: every row needs to be pulled back to PG with
        #     its own raw_content, so each row is a unit.
        #   * Rotation only: rows sharing (sha256, encryption_key_id)
        #     share one stored object and rotate as a cohort — one rep
        #     per cohort suffices.
        # --limit applies to the resulting worklist so "N units" means N
        # actual operations regardless of cohort sizes.
        postgres_ids = list(
            Blob.objects.filter(
                storage_location=BlobStorageLocationChoices.POSTGRES,
            )
            .exclude(encryption_key_id=target_key_id)
            .values_list("id", flat=True)
        )

        if restore_to_pg:
            object_storage_ids = list(
                Blob.objects.filter(
                    storage_location=BlobStorageLocationChoices.OBJECT_STORAGE
                ).values_list("id", flat=True)
            )
        else:
            object_storage_ids = list(
                Blob.objects.filter(
                    storage_location=BlobStorageLocationChoices.OBJECT_STORAGE,
                )
                .exclude(encryption_key_id=target_key_id)
                .order_by("sha256", "encryption_key_id", "id")
                .distinct("sha256", "encryption_key_id")
                .values_list("id", flat=True)
            )

        worklist = postgres_ids + object_storage_ids
        if self.limit > 0:
            worklist = worklist[: self.limit]
        total_count = len(worklist)
        self.stdout.write(f"Work units to re-store: {total_count}")

        if total_count == 0:
            self.stdout.write(
                self.style.SUCCESS("Nothing to do — all blobs already match config")
            )
            return

        rotated_count = 0
        restored_count = 0
        error_count = 0
        skipped_count = 0

        for blob_id in worklist:
            try:
                blob = Blob.objects.get(id=blob_id)
            except Blob.DoesNotExist:
                # Concurrently deleted between worklist build and processing.
                skipped_count += 1
                continue
            try:
                op = self._process_one(blob, target_key_id, restore_to_pg)
                if op == "rotated":
                    rotated_count += 1
                elif op == "restored":
                    restored_count += 1
                else:
                    skipped_count += 1
            except Exception as e:  # pylint: disable=broad-except
                error_count += 1
                self.stderr.write(
                    self.style.ERROR(f"ERROR re-storing blob {blob.id}: {e}")
                )

            done = rotated_count + restored_count + error_count + skipped_count
            if done % 100 == 0:
                self.stdout.write(f"  Progress: {done}/{total_count}")

        self.stdout.write("")
        self.stdout.write(f"Re-encrypted (rotation): {rotated_count}")
        self.stdout.write(f"Restored to PostgreSQL: {restored_count}")
        self.stdout.write(f"Skipped: {skipped_count}")
        self.stdout.write(f"Errors: {error_count}")

        if error_count == 0:
            self.stdout.write(self.style.SUCCESS("Re-store completed successfully"))
        else:
            self.stdout.write(
                self.style.WARNING(f"Re-store completed with {error_count} errors")
            )

    def _process_one(self, blob: Blob, target_key_id: int, restore_to_pg: bool) -> str:
        """Process one blob under transaction + per-sha lock.

        Returns one of: ``"rotated"``, ``"restored"``, ``"skipped"``.
        """
        sha256 = bytes(blob.sha256)
        will_restore = (
            restore_to_pg
            and blob.storage_location == BlobStorageLocationChoices.OBJECT_STORAGE
        )

        if self.dry_run:
            verb = "restore to PG" if will_restore else "re-encrypt"
            self.stdout.write(
                f"  Would {verb} blob {blob.id} "
                f"({blob.get_storage_location_display()}): "
                f"key_id {blob.encryption_key_id} -> {target_key_id}"
            )
            return "restored" if will_restore else "rotated"

        with transaction.atomic(), sha256_advisory_lock(sha256):
            blob.refresh_from_db()
            # Re-check storage_location after refresh — a concurrent
            # actor could have changed it.
            will_restore = (
                restore_to_pg
                and blob.storage_location == BlobStorageLocationChoices.OBJECT_STORAGE
            )
            if will_restore:
                done = self.service.re_store_blob_in_database(blob, target_key_id)
                op = "restored" if done else "skipped"
            elif blob.encryption_key_id == target_key_id:
                # Already at the active key — the worklist was built
                # before we took the lock, and another run (or a
                # concurrent re_store) may have rotated this row
                # already. Skip explicitly so the contract is local
                # to _process_one rather than relying on
                # rotate_blob's internal short-circuit.
                op = "skipped"
            else:
                done = self.service.rotate_blob(blob, target_key_id)
                op = "rotated" if done else "skipped"

        if op != "skipped":
            verb = "Restored" if op == "restored" else "Re-encrypted"
            self.stdout.write(f"  {verb} blob {blob.id} -> key_id {target_key_id}")
        return op
