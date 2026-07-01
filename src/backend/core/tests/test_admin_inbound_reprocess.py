"""Regression tests for the InboundMessage ``reprocess`` admin action.

The action re-dispatches ``process_inbound_message_task`` for any selected row.
For an abandoned row it must clear ``abandoned_at`` *before* it dispatches the
task: ``process_inbound_message_task`` skips any row that is still abandoned, so
publishing first would let a fast worker no-op on the stale marker.
"""

from unittest.mock import patch

from django.contrib import admin as dj_admin
from django.utils import timezone

import pytest

from core import factories, models
from core.admin import InboundMessageAdmin


def _make_abandoned(mailbox):
    blob = factories.BlobFactory(
        mailbox=mailbox, content=b"raw", content_type="message/rfc822"
    )
    return models.InboundMessage.objects.create(
        mailbox=mailbox,
        blob=blob,
        abandoned_at=timezone.now(),
        error_message="boom",
    )


def _make_live(mailbox):
    blob = factories.BlobFactory(
        mailbox=mailbox, content=b"raw", content_type="message/rfc822"
    )
    return models.InboundMessage.objects.create(mailbox=mailbox, blob=blob)


@pytest.mark.django_db
class TestReprocess:
    """``reprocess`` re-queues any selected row, clearing abandoned markers."""

    def _admin(self):
        return InboundMessageAdmin(models.InboundMessage, dj_admin.site)

    def test_clears_abandoned_before_dispatch(self, rf):
        """abandoned_at is NULL by the time the task is dispatched."""
        mailbox = factories.MailboxFactory()
        inbound = _make_abandoned(mailbox)
        seen = {}

        def _capture(message_id):
            # Read the row as the worker would: abandoned_at must already be
            # NULL at dispatch time, otherwise the task guard would skip it.
            row = models.InboundMessage.objects.get(id=message_id)
            seen["abandoned_at"] = row.abandoned_at

        admin_obj = self._admin()
        with (
            patch.object(admin_obj, "message_user"),
            patch(
                "core.mda.inbound_tasks.process_inbound_message_task.delay",
                side_effect=_capture,
            ) as mock_delay,
        ):
            admin_obj.reprocess(rf.post("/admin/"), models.InboundMessage.objects.all())

        mock_delay.assert_called_once_with(str(inbound.id))
        assert seen["abandoned_at"] is None
        inbound.refresh_from_db()
        assert inbound.abandoned_at is None
        assert inbound.error_message == ""

    def test_publish_failure_does_not_revert_clear(self, rf):
        """A broker error is swallowed and the clear is not rolled back."""
        mailbox = factories.MailboxFactory()
        inbound = _make_abandoned(mailbox)

        admin_obj = self._admin()
        with (
            patch.object(admin_obj, "message_user"),
            patch(
                "core.mda.inbound_tasks.process_inbound_message_task.delay",
                side_effect=RuntimeError("broker down"),
            ),
        ):
            # The broker error is swallowed; the clear stands so the retry
            # sweep can pick the now-live row up.
            admin_obj.reprocess(rf.post("/admin/"), models.InboundMessage.objects.all())

        inbound.refresh_from_db()
        assert inbound.abandoned_at is None
        assert inbound.error_message == ""

    def test_reprocesses_live_rows(self, rf):
        """A live (non-abandoned) row is re-queued and left otherwise untouched."""
        mailbox = factories.MailboxFactory()
        live = _make_live(mailbox)

        admin_obj = self._admin()
        with (
            patch.object(admin_obj, "message_user"),
            patch(
                "core.mda.inbound_tasks.process_inbound_message_task.delay"
            ) as mock_delay,
        ):
            admin_obj.reprocess(rf.post("/admin/"), models.InboundMessage.objects.all())

        mock_delay.assert_called_once_with(str(live.id))
        live.refresh_from_db()
        assert live.abandoned_at is None

    def test_dispatches_every_selected_row(self, rf):
        """A mixed selection re-queues both the abandoned and the live row."""
        mailbox = factories.MailboxFactory()
        abandoned = _make_abandoned(mailbox)
        live = _make_live(mailbox)

        admin_obj = self._admin()
        with (
            patch.object(admin_obj, "message_user"),
            patch(
                "core.mda.inbound_tasks.process_inbound_message_task.delay"
            ) as mock_delay,
        ):
            admin_obj.reprocess(rf.post("/admin/"), models.InboundMessage.objects.all())

        dispatched = {call.args[0] for call in mock_delay.call_args_list}
        assert dispatched == {str(abandoned.id), str(live.id)}
