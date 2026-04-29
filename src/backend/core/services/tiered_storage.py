"""
Tiered Storage Service for blob offloading to object storage.

This service handles:
- Uploading blobs to object storage (S3-compatible)
- Downloading blobs from object storage
- Encryption/decryption using AES-256-GCM
- Deduplication via SHA256-based storage keys
"""

import hashlib
import os
from contextlib import contextmanager
from logging import getLogger
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.db import connection

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.enums import BlobStorageLocationChoices

# AES-GCM nonce size — 12 bytes is the NIST-recommended size and the only
# one accepted without performance/security caveats. Stored ciphertext is
# laid out as ``nonce(12) || aes_ciphertext_with_tag(N+16)``.
_NONCE_SIZE = 12

# Minimum length for a configured key string. SHA-256 spreads bits
# uniformly across the 32-byte output, but it can't add entropy that
# wasn't there — operators must supply something high-entropy.
# 32 chars chosen as a sane floor (the system check warns below this).
_MIN_KEY_LEN = 32


def _decode_key(secret: str) -> bytes:
    """Derive a 32-byte AES-256 key from an arbitrary operator-supplied secret.

    We accept any string (passphrase, base64, hex, …) and SHA-256 it to a
    fixed 32-byte key. The hash provides domain separation and uniform
    distribution; it does NOT add entropy. Operators are responsible for
    supplying a high-entropy value (e.g. ``openssl rand -base64 32``).
    """
    if not isinstance(secret, str) or not secret:
        raise ValueError("encryption key must be a non-empty string")
    return hashlib.sha256(secret.encode("utf-8")).digest()


if TYPE_CHECKING:
    from core.models import Blob

logger = getLogger(__name__)


@contextmanager
def sha256_advisory_lock(sha256_bytes: bytes, *, blocking: bool = True):
    """Hold a Postgres advisory lock keyed on a blob's sha256 cohort.

    Must be called inside ``transaction.atomic()`` — the lock is bound to
    the current transaction and released on commit/rollback. Acts as a
    cluster-wide mutex for all offload, dedup, cleanup, and re-encrypt
    work that touches blobs sharing this content.

    With ``blocking=True`` waits until the lock is granted.
    With ``blocking=False`` yields ``True`` if acquired, ``False`` if held
    elsewhere — caller is expected to retry.
    """
    # First 8 bytes of sha256 as a signed 64-bit int — pg_advisory_lock
    # takes a bigint. Collisions are 2^-64, irrelevant in practice.
    key = int.from_bytes(sha256_bytes[:8], byteorder="big", signed=True)
    with connection.cursor() as cursor:
        if blocking:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])
            yield True
        else:
            cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [key])
            yield cursor.fetchone()[0]


class TieredStorageService:
    """Service for tiered blob storage operations using object storage backend."""

    def __init__(self):
        """Initialize the service, checking if object storage is configured."""
        self._storage = None
        self.enabled = bool(settings.STORAGES.get("message-blobs"))
        # encryption_keys is a dict: {"1": "key1", "2": "key2"}
        self.encryption_keys = settings.MESSAGES_BLOB_ENCRYPTION_KEYS or {}
        self.active_key_id = settings.MESSAGES_BLOB_ENCRYPTION_ACTIVE_KEY_ID

    @property
    def storage(self):
        """Lazy load the storage backend."""
        if self._storage is None and self.enabled:
            self._storage = storages["message-blobs"]
        return self._storage

    @staticmethod
    def compute_storage_key(sha256_bytes: bytes, key_id: int) -> str:
        """Compute the storage path for a blob's ciphertext.

        Format: ``blobs/{key_id}/{sha[:3]}/{sha}``. Sharding by sha prefix
        (4,096 directories) keeps S3 request rate balanced; the leading
        ``key_id`` segment lets blobs encrypted with different keys
        coexist, which is what makes online key rotation crash-safe
        (write the new path, flip the DB cohort, then delete the old —
        each step independently atomic). It also means listing all blobs
        at a given key is a single prefix scan, useful when verifying
        that a rotation has fully drained an old key.
        """
        sha_hex = sha256_bytes.hex()
        return f"blobs/{key_id}/{sha_hex[:3]}/{sha_hex}"

    @classmethod
    def compute_storage_key_for_blob(cls, blob: "Blob") -> str:
        """Convenience wrapper around ``compute_storage_key`` for a Blob row."""
        return cls.compute_storage_key(bytes(blob.sha256), blob.encryption_key_id)

    def _aesgcm(self, key_id: int) -> AESGCM:
        """Build an AESGCM cipher for the given key_id (raises if missing)."""
        key_id_str = str(key_id)
        if key_id_str not in self.encryption_keys:
            raise ValueError(
                f"Encryption key_id {key_id} not found in MESSAGES_BLOB_ENCRYPTION_KEYS"
            )
        return AESGCM(_decode_key(self.encryption_keys[key_id_str]))

    def encrypt(self, data: bytes) -> tuple[bytes, int]:
        """Encrypt with AES-256-GCM under the active key.

        Returns ``(nonce(12) || ciphertext+tag(16), key_id)``. ``key_id=0``
        means encryption is disabled and the bytes pass through unchanged.
        """
        if not self.encryption_keys or self.active_key_id == 0:
            return data, 0
        nonce = os.urandom(_NONCE_SIZE)
        ciphertext = self._aesgcm(self.active_key_id).encrypt(nonce, data, None)
        return nonce + ciphertext, self.active_key_id

    def decrypt(self, data: bytes, key_id: int) -> bytes:
        """Decrypt an AES-256-GCM token produced by ``encrypt``.

        ``key_id=0`` is the passthrough sentinel. Raises ``ValueError`` if
        the key is unknown, ``InvalidTag`` if the ciphertext or tag is
        corrupted / decrypted with the wrong key.
        """
        if key_id == 0:
            return data
        nonce, ciphertext = data[:_NONCE_SIZE], data[_NONCE_SIZE:]
        return self._aesgcm(key_id).decrypt(nonce, ciphertext, None)

    def get_existing_key_id(self, sha256_bytes: bytes) -> "int | None":
        """Return the encryption_key_id of any sibling already in OBJECT_STORAGE,
        or ``None`` if none exists. Used by ``upload_blob`` for deduplication."""
        # pylint: disable-next=import-outside-toplevel
        from core.models import Blob

        existing = Blob.objects.filter(
            sha256=sha256_bytes,
            storage_location=BlobStorageLocationChoices.OBJECT_STORAGE,
        ).first()
        return existing.encryption_key_id if existing else None

    def upload_blob(self, blob: "Blob") -> int:
        """Upload a blob's already-encrypted raw_content to object storage.

        Deduplicates: if any sibling row is already in OBJECT_STORAGE for
        this sha256, returns its ``encryption_key_id`` and skips the
        upload — the caller drops ``raw_content`` and reuses the existing
        S3 object via that key_id's path. The storage existence check
        guards against the DB row pointing at a missing/expired object.
        """
        if not self.enabled:
            raise RuntimeError("Object storage is not configured")
        if blob.raw_content is None:
            raise ValueError(f"Blob {blob.id} has no raw_content to upload")

        sha256_bytes = bytes(blob.sha256)
        existing_key_id = self.get_existing_key_id(sha256_bytes)
        if existing_key_id is not None:
            existing_path = self.compute_storage_key(sha256_bytes, existing_key_id)
            if self.storage.exists(existing_path):
                logger.debug(
                    "Blob %s deduped against existing %s", blob.id, existing_path
                )
                return existing_key_id

        key = self.compute_storage_key_for_blob(blob)
        self.storage.save(key, ContentFile(bytes(blob.raw_content)))
        logger.info("Uploaded blob %s to %s", blob.id, key)
        return blob.encryption_key_id

    def download_blob(self, blob: "Blob") -> bytes:
        """Download and decrypt a blob's content. Returns compressed bytes."""
        if not self.enabled:
            raise RuntimeError("Object storage is not configured")

        key = self.compute_storage_key_for_blob(blob)
        with self.storage.open(key, "rb") as f:
            encrypted = f.read()
        return self.decrypt(encrypted, blob.encryption_key_id)

    def rotate_blob(self, blob: "Blob", target_key_id: int) -> bool:
        """Re-encrypt a blob (and its OBJECT_STORAGE cohort) with target_key_id.

        Returns True if rotated, False if already at target / unrotatable.

        For OBJECT_STORAGE the rotation is a 3-step sequence — each step
        independently atomic, so a crash at any boundary leaves the blob
        readable from one consistent path:

        1. write new ciphertext at ``path(sha, target_key_id)`` (atomic S3)
        2. flip the cohort's ``encryption_key_id`` to target (atomic DB)
        3. best-effort delete the old path; strays are cleaned by verify

        Caller must hold ``transaction.atomic()`` and the per-sha256
        advisory lock for the duration.
        """
        if blob.encryption_key_id == target_key_id:
            return False

        old_key_id = blob.encryption_key_id
        sha256 = bytes(blob.sha256)

        if blob.storage_location == BlobStorageLocationChoices.POSTGRES:
            if blob.raw_content is None:
                return False
            decrypted = self.decrypt(bytes(blob.raw_content), old_key_id)
            encrypted, new_id = self.encrypt(decrypted)
            blob.raw_content = encrypted
            blob.encryption_key_id = new_id
            blob.save(
                update_fields=["raw_content", "encryption_key_id", "size_compressed"]
            )
            return True

        # OBJECT_STORAGE: read → re-encrypt → write new path → flip DB → drop old path
        old_path = self.compute_storage_key(sha256, old_key_id)
        new_path = self.compute_storage_key(sha256, target_key_id)

        with self.storage.open(old_path, "rb") as f:
            old_encrypted = f.read()
        decrypted = self.decrypt(old_encrypted, old_key_id)
        encrypted, new_id = self.encrypt(decrypted)

        self.storage.save(new_path, ContentFile(encrypted))

        # pylint: disable-next=import-outside-toplevel
        from core.models import Blob

        Blob.objects.filter(
            sha256=sha256,
            storage_location=BlobStorageLocationChoices.OBJECT_STORAGE,
            encryption_key_id=old_key_id,
        ).update(encryption_key_id=new_id)

        try:
            self.storage.delete(old_path)
        except Exception as e:  # pylint: disable=broad-except
            logger.warning("Failed to drop rotated-from path %s: %s", old_path, e)

        return True

    def delete_if_orphaned(self, sha256_bytes: bytes, key_id: int) -> bool:
        """Delete the storage object at ``path(sha, key_id)`` if unreferenced.

        With key_id encoded in the path, only blobs whose
        ``encryption_key_id`` equals ``key_id`` can possibly need this
        path: a future offload of a sibling row at a different key_id
        would dedup against an existing OBJECT_STORAGE row (adopting its
        key_id) or write to its own key_id's path. So checking for any
        OBJECT_STORAGE blob at ``(sha, key_id)`` is enough.
        """
        if not self.enabled:
            return False

        # pylint: disable-next=import-outside-toplevel
        from core.models import Blob

        refs = Blob.objects.filter(
            sha256=sha256_bytes,
            storage_location=BlobStorageLocationChoices.OBJECT_STORAGE,
            encryption_key_id=key_id,
        ).count()

        if refs > 0:
            return False

        key = self.compute_storage_key(sha256_bytes, key_id)
        try:
            self.storage.delete(key)
            logger.info("Deleted orphaned storage object: %s", key)
            return True
        except Exception as e:  # pylint: disable=broad-except
            logger.warning("Failed to delete storage object %s: %s", key, e)
            return False
