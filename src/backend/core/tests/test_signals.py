"""Test signal handlers for core models."""

from unittest.mock import patch

import pytest

from core import enums, factories
from core.utils import ThreadStatsUpdateDeferrer

pytestmark = pytest.mark.django_db


class TestUpdateThreadStatsOnDeliveryStatusChange:
    """Test the signal that updates thread stats when delivery status changes."""

    def test_signal_triggers_on_delivery_status_change(self):
        """Test that update_stats is called when delivery_status changes."""
        thread = factories.ThreadFactory()
        message = factories.MessageFactory(
            thread=thread,
            is_sender=True,
            is_draft=False,
            is_trashed=False,
        )
        recipient = factories.MessageRecipientFactory(
            message=message,
            delivery_status=None,
        )

        with patch.object(thread, "update_stats") as mock_update_stats:
            recipient.delivery_status = enums.MessageDeliveryStatusChoices.SENT
            recipient.save(update_fields=["delivery_status"])

            mock_update_stats.assert_called_once()

    def test_signal_does_not_trigger_for_non_sender_message(self):
        """Test that update_stats is NOT called for inbound messages (is_sender=False)."""
        thread = factories.ThreadFactory()
        message = factories.MessageFactory(
            thread=thread,
            is_sender=False,  # Inbound message
            is_draft=False,
            is_trashed=False,
        )
        recipient = factories.MessageRecipientFactory(
            message=message,
            delivery_status=None,
        )

        with patch.object(thread, "update_stats") as mock_update_stats:
            recipient.delivery_status = enums.MessageDeliveryStatusChoices.SENT
            recipient.save(update_fields=["delivery_status"])

            mock_update_stats.assert_not_called()

    def test_signal_does_not_trigger_for_draft_message(self):
        """Test that update_stats is NOT called for draft messages."""
        thread = factories.ThreadFactory()
        message = factories.MessageFactory(
            thread=thread,
            is_sender=True,
            is_draft=True,  # Draft
            is_trashed=False,
        )
        recipient = factories.MessageRecipientFactory(
            message=message,
            delivery_status=None,
        )

        with patch.object(thread, "update_stats") as mock_update_stats:
            recipient.delivery_status = enums.MessageDeliveryStatusChoices.SENT
            recipient.save(update_fields=["delivery_status"])

            mock_update_stats.assert_not_called()

    def test_signal_does_not_trigger_for_trashed_message(self):
        """Test that update_stats is NOT called for trashed messages."""
        thread = factories.ThreadFactory()
        message = factories.MessageFactory(
            thread=thread,
            is_sender=True,
            is_draft=False,
            is_trashed=True,  # Trashed
        )
        recipient = factories.MessageRecipientFactory(
            message=message,
            delivery_status=None,
        )

        with patch.object(thread, "update_stats") as mock_update_stats:
            recipient.delivery_status = enums.MessageDeliveryStatusChoices.SENT
            recipient.save(update_fields=["delivery_status"])

            mock_update_stats.assert_not_called()

    def test_signal_does_not_trigger_for_other_field_changes(self):
        """Test that update_stats is NOT called when other fields change."""
        thread = factories.ThreadFactory()
        message = factories.MessageFactory(
            thread=thread,
            is_sender=True,
            is_draft=False,
            is_trashed=False,
        )
        recipient = factories.MessageRecipientFactory(
            message=message,
            delivery_status=enums.MessageDeliveryStatusChoices.SENT,
        )

        with patch.object(thread, "update_stats") as mock_update_stats:
            recipient.delivery_message = "Updated message"
            recipient.save(update_fields=["delivery_message"])

            mock_update_stats.assert_not_called()


class TestThreadStatsUpdateDeferrer:
    """Test the ThreadStatsUpdateDeferrer context manager."""

    def test_defers_update_until_context_exit(self):
        """Test that updates are deferred and called once at context exit."""
        thread = factories.ThreadFactory()
        message = factories.MessageFactory(
            thread=thread,
            is_sender=True,
            is_draft=False,
            is_trashed=False,
        )
        recipient1 = factories.MessageRecipientFactory(
            message=message,
            delivery_status=None,
        )
        recipient2 = factories.MessageRecipientFactory(
            message=message,
            delivery_status=None,
        )

        with patch("core.models.Thread.update_stats") as mock_update_stats:
            with ThreadStatsUpdateDeferrer.defer():
                recipient1.delivery_status = enums.MessageDeliveryStatusChoices.SENT
                recipient1.save(update_fields=["delivery_status"])

                recipient2.delivery_status = enums.MessageDeliveryStatusChoices.FAILED
                recipient2.save(update_fields=["delivery_status"])

                # Should not have been called yet
                mock_update_stats.assert_not_called()

            # Should be called once after exiting context
            mock_update_stats.assert_called_once()

    def test_nested_contexts_only_update_once(self):
        """Test that nested contexts only trigger update at outermost exit."""
        thread = factories.ThreadFactory()
        message = factories.MessageFactory(
            thread=thread,
            is_sender=True,
            is_draft=False,
            is_trashed=False,
        )
        recipient = factories.MessageRecipientFactory(
            message=message,
            delivery_status=None,
        )

        with patch("core.models.Thread.update_stats") as mock_update_stats:
            with ThreadStatsUpdateDeferrer.defer():
                with ThreadStatsUpdateDeferrer.defer():
                    recipient.delivery_status = enums.MessageDeliveryStatusChoices.SENT
                    recipient.save(update_fields=["delivery_status"])

                # Inner context exited, should not have been called yet
                mock_update_stats.assert_not_called()

            # Outer context exited, should be called once
            mock_update_stats.assert_called_once()

    def test_multiple_threads_updated(self):
        """Test that multiple affected threads are all updated."""
        thread1 = factories.ThreadFactory()
        thread2 = factories.ThreadFactory()
        message1 = factories.MessageFactory(
            thread=thread1,
            is_sender=True,
            is_draft=False,
            is_trashed=False,
        )
        message2 = factories.MessageFactory(
            thread=thread2,
            is_sender=True,
            is_draft=False,
            is_trashed=False,
        )
        recipient1 = factories.MessageRecipientFactory(
            message=message1,
            delivery_status=None,
        )
        recipient2 = factories.MessageRecipientFactory(
            message=message2,
            delivery_status=None,
        )

        with patch("core.models.Thread.update_stats") as mock_update_stats:
            with ThreadStatsUpdateDeferrer.defer():
                recipient1.delivery_status = enums.MessageDeliveryStatusChoices.SENT
                recipient1.save(update_fields=["delivery_status"])

                recipient2.delivery_status = enums.MessageDeliveryStatusChoices.SENT
                recipient2.save(update_fields=["delivery_status"])

            # Should be called twice, once per thread
            assert mock_update_stats.call_count == 2

    def test_update_stats_error_does_not_propagate(self):
        """Test that errors in update_stats() are caught and logged, not propagated."""
        thread1 = factories.ThreadFactory()
        thread2 = factories.ThreadFactory()
        message1 = factories.MessageFactory(
            thread=thread1,
            is_sender=True,
            is_draft=False,
            is_trashed=False,
        )
        message2 = factories.MessageFactory(
            thread=thread2,
            is_sender=True,
            is_draft=False,
            is_trashed=False,
        )
        recipient1 = factories.MessageRecipientFactory(
            message=message1,
            delivery_status=None,
        )
        recipient2 = factories.MessageRecipientFactory(
            message=message2,
            delivery_status=None,
        )

        # Make update_stats() raise an error on first call, succeed on second
        with patch(
            "core.models.Thread.update_stats",
            side_effect=[Exception("Test error"), None],
        ) as mock_update_stats:
            # Should not raise, error is caught and logged
            with ThreadStatsUpdateDeferrer.defer():
                recipient1.delivery_status = enums.MessageDeliveryStatusChoices.SENT
                recipient1.save(update_fields=["delivery_status"])

                recipient2.delivery_status = enums.MessageDeliveryStatusChoices.SENT
                recipient2.save(update_fields=["delivery_status"])

            # Both should have been attempted
            assert mock_update_stats.call_count == 2
