"""
Tiered Storage Service for blob offloading to object storage.

This service handles:
- Uploading blobs to object storage (S3-compatible)
- Downloading blobs from object storage
- Encryption/decryption using Fernet
- Deduplication via SHA256-based storage keys
"""

from logging import getLogger
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import storages

from cryptography.fernet import Fernet

from core.enums import BlobStorageLocationChoices

if TYPE_CHECKING:
    from core.models import Blob

logger = getLogger(__name__)


class TieredStorageService:
    """Service for tiered blob storage operations using object storage backend."""

    def __init__(self):
        """Initialize the service, checking if object storage is configured."""
        # Check if message-blobs storage has endpoint_url configured
        self._storage = None
        self.enabled = bool(
            settings.STORAGES.get("message-blobs", {})
            .get("OPTIONS", {})
            .get("endpoint_url")
        )
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
    def compute_storage_key(sha256_bytes: bytes) -> str:
        """
        Compute storage key from SHA256 hash.

        Format: blobs/{sha[:3]}/{sha}
        Uses 3 hex characters for directory sharding (4,096 directories).

        Args:
            sha256_bytes: The SHA256 hash as bytes

        Returns:
            Storage key string
        """
        sha_hex = sha256_bytes.hex()
        return f"blobs/{sha_hex[:3]}/{sha_hex}"

    def encrypt(self, data: bytes) -> tuple[bytes, int]:
        """
        Encrypt data using Fernet with the active key.

        Args:
            data: Raw bytes to encrypt

        Returns:
            Tuple of (encrypted_bytes, key_id)
            key_id=0 means no encryption (passthrough)
            key_id>=1 refers to the key ID in the encryption_keys dict
        """
        # No encryption if no keys or active_key_id is 0
        if not self.encryption_keys or self.active_key_id == 0:
            return data, 0  # No encryption, passthrough

        key_id_str = str(self.active_key_id)
        if key_id_str not in self.encryption_keys:
            raise ValueError(
                f"Active encryption key_id {self.active_key_id} not found in MESSAGES_BLOB_ENCRYPTION_KEYS"
            )

        fernet = Fernet(self.encryption_keys[key_id_str].encode())
        return fernet.encrypt(data), self.active_key_id

    def decrypt(self, data: bytes, key_id: int) -> bytes:
        """
        Decrypt data using specified key from key dict.

        Args:
            data: Encrypted bytes
            key_id: Key identifier (0=no encryption, >=1=dict key)

        Returns:
            Decrypted bytes

        Raises:
            ValueError: If key_id not found in dict
        """
        if key_id == 0:
            return data  # No encryption, passthrough

        key_id_str = str(key_id)
        if key_id_str not in self.encryption_keys:
            raise ValueError(
                f"Encryption key_id {key_id} not found in MESSAGES_BLOB_ENCRYPTION_KEYS"
            )

        fernet = Fernet(self.encryption_keys[key_id_str].encode())
        return fernet.decrypt(data)

    def check_already_uploaded(self, sha256_bytes: bytes) -> bool:
        """
        Check if a blob with the same SHA256 already exists in object storage.

        Uses DB lookup (not HEAD request) - DB is source of truth.

        Args:
            sha256_bytes: SHA256 hash to check

        Returns:
            True if already uploaded, False otherwise
        """
        # Import here to avoid circular import at module load time
        from core.models import Blob

        return Blob.objects.filter(
            sha256=sha256_bytes,
            storage_location=BlobStorageLocationChoices.OBJECT_STORAGE,
        ).exists()

    def get_existing_key_id(self, sha256_bytes: bytes) -> int:
        """
        Get the encryption key_id from an existing blob with same SHA256.

        Args:
            sha256_bytes: SHA256 hash to look up

        Returns:
            encryption_key_id from existing blob, or 0 if not found
        """
        from core.models import Blob

        existing = Blob.objects.filter(
            sha256=sha256_bytes,
            storage_location=BlobStorageLocationChoices.OBJECT_STORAGE,
        ).first()
        return existing.encryption_key_id if existing else 0

    def upload_blob(self, blob: "Blob") -> int:
        """
        Upload blob content to object storage.

        The blob's raw_content is already encrypted (from create_blob), so we
        just upload it as-is without re-encrypting.

        Handles deduplication: if a blob with the same SHA256 already exists
        in object storage, skip the upload and return the existing key_id.

        Args:
            blob: Blob instance with raw_content to upload

        Returns:
            encryption_key_id (blob's existing key_id, unchanged)

        Raises:
            ValueError: If blob has no raw_content
        """
        if not self.enabled:
            raise RuntimeError("Object storage is not configured")

        if blob.raw_content is None:
            raise ValueError(f"Blob {blob.id} has no raw_content to upload")

        sha256_bytes = bytes(blob.sha256)

        # Check if already uploaded (deduplication via DB lookup)
        if self.check_already_uploaded(sha256_bytes):
            logger.debug(
                "Blob %s already exists in object storage (dedup), skipping upload",
                blob.id,
            )
            return self.get_existing_key_id(sha256_bytes)

        # Upload raw_content as-is (already encrypted from create_blob)
        content = bytes(blob.raw_content)
        key = self.compute_storage_key(sha256_bytes)
        self.storage.save(key, ContentFile(content))

        logger.info(
            "Uploaded blob %s to object storage: %s (%d bytes, key_id=%d)",
            blob.id,
            key,
            len(content),
            blob.encryption_key_id,
        )

        # Return blob's existing encryption_key_id (unchanged)
        return blob.encryption_key_id

    def download_blob(self, blob: "Blob") -> bytes:
        """
        Download and decrypt blob content from object storage.

        Args:
            blob: Blob instance with sha256 and encryption_key_id

        Returns:
            Decrypted (but still compressed) content

        Raises:
            FileNotFoundError: If blob not found in storage
        """
        if not self.enabled:
            raise RuntimeError("Object storage is not configured")

        key = self.compute_storage_key(bytes(blob.sha256))

        try:
            with self.storage.open(key, "rb") as f:
                encrypted = f.read()
        except FileNotFoundError:
            logger.error("Blob %s not found in object storage: %s", blob.id, key)
            raise

        decrypted = self.decrypt(encrypted, blob.encryption_key_id)

        logger.debug(
            "Downloaded blob %s from object storage: %s (%d bytes)",
            blob.id,
            key,
            len(decrypted),
        )

        return decrypted

    def delete_if_orphaned(self, sha256_bytes: bytes) -> bool:
        """
        Delete storage object only if no other blobs reference it.

        Args:
            sha256_bytes: SHA256 hash of the blob to potentially delete

        Returns:
            True if deleted, False if still referenced
        """
        if not self.enabled:
            return False

        from core.models import Blob

        # Count remaining references
        refs = Blob.objects.filter(
            sha256=sha256_bytes,
            storage_location=BlobStorageLocationChoices.OBJECT_STORAGE,
        ).count()

        if refs > 0:
            logger.debug(
                "Blob %s still has %d references, not deleting from storage",
                sha256_bytes.hex()[:8],
                refs,
            )
            return False

        key = self.compute_storage_key(sha256_bytes)
        try:
            self.storage.delete(key)
            logger.info("Deleted orphaned blob from object storage: %s", key)
            return True
        except Exception as e:  # pylint: disable=broad-except
            logger.warning("Failed to delete blob from storage %s: %s", key, e)
            return False

    def exists(self, sha256_bytes: bytes) -> bool:
        """
        Check if a storage object exists for the given SHA256.

        Args:
            sha256_bytes: SHA256 hash to check

        Returns:
            True if exists in storage, False otherwise
        """
        if not self.enabled:
            return False

        key = self.compute_storage_key(sha256_bytes)
        return self.storage.exists(key)
