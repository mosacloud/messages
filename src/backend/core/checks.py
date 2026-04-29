"""Django system checks for the core app.

Run automatically by ``manage.py check`` and at server startup; surface
configuration mistakes before they manifest as runtime errors.
"""

# pylint: disable=unused-argument

import os

from django.conf import settings
from django.core.checks import Error, register
from django.core.checks import Warning as CheckWarning

from core.enums import parse_compression_spec
from core.services.tiered_storage import _MIN_KEY_LEN, _decode_key


@register()
def check_blob_compression_config(app_configs, **kwargs):
    """``MESSAGES_BLOB_COMPRESS`` must parse as ``"<algo>"`` or ``"<algo>:<level>"``."""
    value = getattr(settings, "MESSAGES_BLOB_COMPRESS", "zstd:3")
    issues = []
    try:
        parse_compression_spec(value)
    except (ValueError, AttributeError) as e:
        issues.append(
            Error(
                f"MESSAGES_BLOB_COMPRESS={value!r} is invalid: {e}",
                hint='Use "none", "zstd", or "zstd:<level>".',
                id="core.E004",
            )
        )
    if "MESSAGES_BLOB_ZSTD_LEVEL" in os.environ:
        issues.append(
            CheckWarning(
                "MESSAGES_BLOB_ZSTD_LEVEL is deprecated and ignored.",
                hint='Set MESSAGES_BLOB_COMPRESS="zstd:<level>" instead.',
                id="core.W001",
            )
        )
    return issues


@register()
def check_blob_encryption_config(app_configs, **kwargs):
    """Validate the tiered-storage blob encryption settings.

    - ``MESSAGES_BLOB_ENCRYPTION_KEYS`` must be a dict (or empty/None).
    - Every value must decode to a 32-byte AES-256 key (Fernet-format
      base64 is accepted for operator continuity).
    - If ``MESSAGES_BLOB_ENCRYPTION_ACTIVE_KEY_ID`` is non-zero, it must
      reference an entry in the keys dict.
    """
    errors = []
    keys = getattr(settings, "MESSAGES_BLOB_ENCRYPTION_KEYS", None) or {}
    active_id = getattr(settings, "MESSAGES_BLOB_ENCRYPTION_ACTIVE_KEY_ID", 0)

    if not isinstance(keys, dict):
        errors.append(
            Error(
                "MESSAGES_BLOB_ENCRYPTION_KEYS must be a JSON object "
                f"(got {type(keys).__name__}).",
                id="core.E001",
            )
        )
        return errors

    for key_id, key_value in keys.items():
        try:
            _decode_key(key_value)
        except Exception as e:  # pylint: disable=broad-except
            errors.append(
                Error(
                    f"MESSAGES_BLOB_ENCRYPTION_KEYS[{key_id!r}] is invalid: {e}",
                    id="core.E002",
                )
            )
            continue
        if isinstance(key_value, str) and len(key_value) < _MIN_KEY_LEN:
            errors.append(
                CheckWarning(
                    f"MESSAGES_BLOB_ENCRYPTION_KEYS[{key_id!r}] is shorter than "
                    f"{_MIN_KEY_LEN} chars — likely low-entropy.",
                    hint="Generate with `openssl rand -base64 32` or similar.",
                    id="core.W002",
                )
            )

    if active_id and str(active_id) not in keys:
        errors.append(
            Error(
                f"MESSAGES_BLOB_ENCRYPTION_ACTIVE_KEY_ID={active_id} but no "
                f"matching entry in MESSAGES_BLOB_ENCRYPTION_KEYS "
                f"(have keys: {sorted(keys)}).",
                hint="Add the key to MESSAGES_BLOB_ENCRYPTION_KEYS or set "
                "MESSAGES_BLOB_ENCRYPTION_ACTIVE_KEY_ID=0 to disable encryption.",
                id="core.E003",
            )
        )

    return errors
