"""Unit tests for ``InboundMessage`` model helpers."""

import pytest

from core import factories, models


@pytest.mark.django_db
class TestGetRawBytes:
    """``get_raw_bytes`` reads the raw message bytes from the backing blob."""

    def test_returns_blob_content(self):
        """The happy path returns the decrypted blob bytes."""
        mailbox = factories.MailboxFactory()
        blob = models.Blob.objects.create_blob(
            content=b"raw mime bytes", content_type="message/rfc822"
        )
        inbound = models.InboundMessage.objects.create(mailbox=mailbox, blob=blob)

        assert inbound.get_raw_bytes() == b"raw mime bytes"

    def test_raises_clear_error_when_blob_missing(self):
        """A row without a blob fails fast with a named error instead of a
        bare ``AttributeError`` deep in ``Blob.get_content()``."""
        mailbox = factories.MailboxFactory()
        inbound = models.InboundMessage.objects.create(mailbox=mailbox, blob=None)

        with pytest.raises(ValueError, match=f"InboundMessage {inbound.id}"):
            inbound.get_raw_bytes()
