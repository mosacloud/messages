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
        """Initialize the service, checking if object storage is configured.

        ``message-blobs`` is always present in ``STORAGES`` because the
        Configuration class can't conditionally drop entries; we infer
        "actually configured" from the resolved options instead. An
        endpoint_url indicates a custom S3-compatible backend (MinIO,
        rustfs); an access_key indicates explicit credentials (AWS).
        IAM-role-only setups need to set a dummy access_key to opt in.
        """
        self._storage = None
        opts = settings.STORAGES.get("message-blobs", {}).get("OPTIONS", {})
        self.enabled = bool(opts.get("endpoint_url") or opts.get("access_key"))
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

        Format: ``blobs/{key_id}/{sha[:3]}/{sha}``.

        - ``key_id`` first: lets blobs encrypted with different keys
          coexist on disk (essential for crash-safe online rotation),
          and lets ops list everything at a key with one prefix scan.
        - 3-char sha prefix: 4,096 sub-shards for S3 request-rate balance.

        Compression is intentionally NOT in the path. A given sha256
        adopts whatever compression the first stored copy used and
        sticks with it forever (later uploads that requested a
        different algorithm just inherit, see ``upload_blob``). One
        sha256 → one stored object — full stop.
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

    def get_existing_sibling(self, sha256_bytes: bytes) -> "tuple[int, int] | None":
        """Return ``(encryption_key_id, compression)`` of any OBJECT_STORAGE
        sibling for this sha256, or ``None`` if none exists.

        A sha256 has exactly one stored object across the cluster. The
        sibling's ``compression`` is what was used to produce those
        stored bytes — new uploads that find a sibling adopt both its
        ``key_id`` (so they read from the same path) and its
        ``compression`` (so ``restore()`` decompresses correctly).
        """
        # pylint: disable-next=import-outside-toplevel
        from core.models import Blob

        existing = (
            Blob.objects.filter(
                sha256=sha256_bytes,
                storage_location=BlobStorageLocationChoices.OBJECT_STORAGE,
            )
            .values("encryption_key_id", "compression")
            .first()
        )
        if existing is None:
            return None
        return existing["encryption_key_id"], existing["compression"]

    def upload_blob(self, blob: "Blob") -> "tuple[int, int]":
        """Upload a blob's already-encrypted raw_content to object storage.

        Returns ``(encryption_key_id, compression)`` — the values the
        caller must persist on the new blob row before flipping its
        ``storage_location`` to OBJECT_STORAGE. On a dedup hit these
        come from the existing sibling, not from the new blob: a given
        sha256 keeps the encryption key and compression algorithm of
        whichever copy hit the bucket first, regardless of what the
        configured defaults are at upload time.

        The storage existence check guards against the DB row pointing
        at a missing/expired object — if the sibling's stored bytes are
        gone (manual deletion, lifecycle expiry), we fall through to a
        real upload of the new blob's own raw_content.
        """
        if not self.enabled:
            raise RuntimeError("Object storage is not configured")
        if blob.raw_content is None:
            raise ValueError(f"Blob {blob.id} has no raw_content to upload")

        sha256_bytes = bytes(blob.sha256)
        sibling = self.get_existing_sibling(sha256_bytes)
        if sibling is not None:
            existing_key_id, existing_compression = sibling
            existing_path = self.compute_storage_key(sha256_bytes, existing_key_id)
            if self.storage.exists(existing_path):
                logger.debug(
                    "Blob %s deduped against existing %s", blob.id, existing_path
                )
                return existing_key_id, existing_compression

        key = self.compute_storage_key_for_blob(blob)
        self.storage.save(key, ContentFile(bytes(blob.raw_content)))
        logger.info("Uploaded blob %s to object storage", blob.id)
        return blob.encryption_key_id, blob.compression

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

        ``target_key_id`` MUST equal ``self.active_key_id`` — ``encrypt()``
        only knows how to encrypt with the active key, so rotating to any
        other key would produce ciphertext under one key while the DB row
        records another.

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
        if target_key_id != self.active_key_id:
            raise ValueError(
                f"rotate_blob target_key_id={target_key_id} must match "
                f"active_key_id={self.active_key_id}"
            )
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

        # OBJECT_STORAGE: read → re-encrypt → write new path → flip DB → drop old path.
        # The cohort sharing this storage object is (sha, key_id) — every
        # row in it shares the same compression value too (set at first
        # upload), but compression isn't part of the path so we don't
        # need to filter on it.
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
        """Delete the storage object at ``path(sha, key_id)`` if no blob row
        references it.

        With key_id encoded in the path, only blobs whose
        ``(sha256, encryption_key_id)`` pair matches can possibly need
        this object — a sibling at a different key_id has its own path,
        and compression is shared across the whole cohort (set at first
        upload). Counting rows at this exact pair is sufficient.
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
        # Let storage errors propagate — the cleanup task catches transient
        # ones (BotoCoreError/OSError) and retries; permanent errors surface
        # in logs instead of being silently swallowed as "still referenced".
        self.storage.delete(key)
        logger.info("Deleted orphaned storage object: %s", key)
        return True
