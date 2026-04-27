"""Test signal handlers for core models."""
# pylint: disable=too-many-lines

from unittest.mock import patch

from django.db.models.signals import post_save

import pytest

from core import enums, factories, models
from core.signals import handle_thread_event_post_save
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


class TestHandleThreadEventPostSave:
    """Test the post_save signal handler for ThreadEvent."""

    def _setup_thread_with_mentioned_user(self):
        """Create a thread with a user who has access and can be mentioned.

        Returns (author, mentioned_user, thread, mailbox) tuple.
        The access chain: mentioned_user -> MailboxAccess -> mailbox -> ThreadAccess -> thread
        """
        author = factories.UserFactory()
        mailbox = factories.MailboxFactory()
        factories.MailboxAccessFactory(mailbox=mailbox, user=author)
        thread = factories.ThreadFactory()
        factories.ThreadAccessFactory(thread=thread, mailbox=mailbox)
        mentioned_user = factories.UserFactory()
        factories.MailboxAccessFactory(mailbox=mailbox, user=mentioned_user)
        return author, mentioned_user, thread, mailbox

    def test_signal_runs_without_error_on_create(self):
        """Signal should execute without error when a ThreadEvent is created."""
        event = factories.ThreadEventFactory()
        assert event.id is not None

    def test_signal_broad_catch_does_not_break_save(self):
        """Signal should catch exceptions and not block ThreadEvent creation."""
        with patch(
            "core.signals.sync_mention_user_events",
            side_effect=RuntimeError("test error"),
        ):
            author, mentioned_user, thread, _ = self._setup_thread_with_mentioned_user()
            event = factories.ThreadEventFactory(
                thread=thread,
                author=author,
                data={
                    "content": "Hello @John",
                    "mentions": [
                        {"id": str(mentioned_user.id), "name": "John"},
                    ],
                },
            )
            # ThreadEvent should still be saved despite exception
            assert event.id is not None

    def test_creates_user_event_for_valid_mention(self):
        """A ThreadEvent IM with a valid mention should create one UserEvent MENTION."""
        author, mentioned_user, thread, _ = self._setup_thread_with_mentioned_user()

        event = factories.ThreadEventFactory(
            thread=thread,
            author=author,
            data={
                "content": "Hello @John",
                "mentions": [{"id": str(mentioned_user.id), "name": "John"}],
            },
        )

        user_events = models.UserEvent.objects.filter(
            thread_event=event, user=mentioned_user, type="mention"
        )
        assert user_events.count() == 1

        user_event = user_events.first()
        assert user_event.read_at is None
        assert user_event.thread == thread

    def test_deduplicates_mentions_within_same_event(self):
        """Same user mentioned twice in one ThreadEvent should create only one UserEvent."""
        author, mentioned_user, thread, _ = self._setup_thread_with_mentioned_user()

        event = factories.ThreadEventFactory(
            thread=thread,
            author=author,
            data={
                "content": "Hello @John and @John again",
                "mentions": [
                    {"id": str(mentioned_user.id), "name": "John"},
                    {"id": str(mentioned_user.id), "name": "John"},
                ],
            },
        )

        assert (
            models.UserEvent.objects.filter(
                thread_event=event, user=mentioned_user
            ).count()
            == 1
        )

    def test_multiple_events_create_separate_user_events(self):
        """Same user mentioned in 2 different ThreadEvents should create 2 UserEvents."""
        author, mentioned_user, thread, _ = self._setup_thread_with_mentioned_user()
        mention_data = {
            "content": "Hello @John",
            "mentions": [{"id": str(mentioned_user.id), "name": "John"}],
        }

        event1 = factories.ThreadEventFactory(
            thread=thread, author=author, data=mention_data
        )
        event2 = factories.ThreadEventFactory(
            thread=thread, author=author, data=mention_data
        )

        user_events = models.UserEvent.objects.filter(
            user=mentioned_user, thread=thread, type="mention"
        )
        assert user_events.count() == 2

        thread_event_ids = set(user_events.values_list("thread_event_id", flat=True))
        assert thread_event_ids == {event1.id, event2.id}

    def test_skips_mention_without_thread_access(self):
        """User mentioned without ThreadAccess should not get a UserEvent."""
        author, _, thread, _ = self._setup_thread_with_mentioned_user()
        no_access_user = factories.UserFactory()

        with patch("core.signals.logger") as mock_logger:
            factories.ThreadEventFactory(
                thread=thread,
                author=author,
                data={
                    "content": "Hello @Ghost",
                    "mentions": [
                        {"id": str(no_access_user.id), "name": "Ghost"},
                    ],
                },
            )

        assert models.UserEvent.objects.filter(user=no_access_user).count() == 0
        mock_logger.warning.assert_called()
        warning_args = str(mock_logger.warning.call_args)
        assert str(no_access_user.id) in warning_args

    def test_skips_invalid_user_id(self):
        """Mention with non-existent UUID should not create a UserEvent."""
        author, _, thread, _ = self._setup_thread_with_mentioned_user()
        fake_uuid = "00000000-0000-0000-0000-000000000000"
        initial_count = models.UserEvent.objects.count()

        with patch("core.signals.logger") as mock_logger:
            factories.ThreadEventFactory(
                thread=thread,
                author=author,
                data={
                    "content": "Hello @Ghost",
                    "mentions": [{"id": fake_uuid, "name": "Ghost"}],
                },
            )

        assert models.UserEvent.objects.count() == initial_count
        mock_logger.warning.assert_called()

    def test_ignores_non_im_events(self):
        """Signal should return early for non-IM ThreadEvent types."""
        author, mentioned_user, thread, _ = self._setup_thread_with_mentioned_user()
        event = factories.ThreadEventFactory(
            thread=thread,
            author=author,
            data={
                "content": "Hello @John",
                "mentions": [{"id": str(mentioned_user.id), "name": "John"}],
            },
        )
        initial_count = models.UserEvent.objects.count()

        # Call handler directly with a mocked non-IM type
        with patch.object(event, "type", "other_type"):
            handle_thread_event_post_save(
                sender=models.ThreadEvent, instance=event, created=True
            )

        assert models.UserEvent.objects.count() == initial_count

    def test_ignores_im_without_mentions(self):
        """ThreadEvent IM without mentions key should not create any UserEvent."""
        author, _, thread, _ = self._setup_thread_with_mentioned_user()
        initial_count = models.UserEvent.objects.count()

        factories.ThreadEventFactory(
            thread=thread,
            author=author,
            data={"content": "Hello everyone"},
        )

        assert models.UserEvent.objects.count() == initial_count

    def test_ignores_im_with_empty_mentions(self):
        """ThreadEvent IM with empty mentions list should not create any UserEvent."""
        author, _, thread, _ = self._setup_thread_with_mentioned_user()
        initial_count = models.UserEvent.objects.count()

        factories.ThreadEventFactory(
            thread=thread,
            author=author,
            data={"content": "Hello everyone", "mentions": []},
        )

        assert models.UserEvent.objects.count() == initial_count


class TestBackfillMentionUserEvents:
    """Test the backfill logic for UserEvent MENTION from existing ThreadEvent IM.

    These tests verify the same algorithm used in migration 0025, using
    application models instead of apps.get_model() for testability.
    """

    @staticmethod
    def _run_backfill_logic():
        """Simulate the migration backfill logic using real models.

        Uses the same algorithm as the data migration but with real model
        classes. This allows testing the core logic without the migration
        test runner complexity.
        """
        batch_size = 500
        queryset = models.ThreadEvent.objects.filter(
            type="im",
        ).select_related("thread")

        batch = []
        for event in queryset.iterator(chunk_size=batch_size):
            mentions = (event.data or {}).get("mentions")
            if not mentions:
                continue

            seen_user_ids = set()
            unique_user_ids = []
            for mention in mentions:
                raw_id = mention.get("id")
                if raw_id and raw_id not in seen_user_ids:
                    seen_user_ids.add(raw_id)
                    unique_user_ids.append(raw_id)

            if not unique_user_ids:
                continue

            valid_user_ids = set(
                models.MailboxAccess.objects.filter(
                    user_id__in=unique_user_ids,
                    mailbox__thread_accesses__thread=event.thread,
                ).values_list("user_id", flat=True)
            )

            if not valid_user_ids:
                continue

            existing = set(
                models.UserEvent.objects.filter(
                    thread_event=event,
                    type="mention",
                ).values_list("user_id", flat=True)
            )

            for user_id in valid_user_ids - existing:
                batch.append(
                    models.UserEvent(
                        user_id=user_id,
                        thread=event.thread,
                        thread_event=event,
                        type="mention",
                    )
                )

            if len(batch) >= batch_size:
                models.UserEvent.objects.bulk_create(batch)
                batch = []

        if batch:
            models.UserEvent.objects.bulk_create(batch)

    @staticmethod
    def _setup_thread_with_mentioned_user():
        """Create a thread with a user who has access and can be mentioned."""
        author = factories.UserFactory()
        mailbox = factories.MailboxFactory()
        factories.MailboxAccessFactory(mailbox=mailbox, user=author)
        thread = factories.ThreadFactory()
        factories.ThreadAccessFactory(thread=thread, mailbox=mailbox)
        mentioned_user = factories.UserFactory()
        factories.MailboxAccessFactory(mailbox=mailbox, user=mentioned_user)
        return author, mentioned_user, thread, mailbox

    def test_backfill_creates_user_events_for_existing_mentions(self):
        """Backfill should create UserEvents for pre-existing ThreadEvent IM with mentions."""
        author, mentioned_user, thread, _ = self._setup_thread_with_mentioned_user()

        # Create ThreadEvent without triggering the signal (simulate pre-existing data)
        event = models.ThreadEvent(
            thread=thread,
            author=author,
            type="im",
            data={
                "content": "Hello @John",
                "mentions": [{"id": str(mentioned_user.id), "name": "John"}],
            },
        )

        post_save.disconnect(handle_thread_event_post_save, sender=models.ThreadEvent)
        try:
            event.save()
        finally:
            post_save.connect(handle_thread_event_post_save, sender=models.ThreadEvent)

        # Verify no UserEvent was created by the signal
        assert models.UserEvent.objects.filter(thread_event=event).count() == 0

        # Run backfill
        self._run_backfill_logic()

        # Verify UserEvent was created
        user_events = models.UserEvent.objects.filter(
            thread_event=event, user=mentioned_user, type="mention"
        )
        assert user_events.count() == 1

    def test_backfill_deduplicates_within_same_event(self):
        """Backfill should create only one UserEvent when user is mentioned twice."""
        author, mentioned_user, thread, _ = self._setup_thread_with_mentioned_user()

        post_save.disconnect(handle_thread_event_post_save, sender=models.ThreadEvent)
        try:
            event = models.ThreadEvent.objects.create(
                thread=thread,
                author=author,
                type="im",
                data={
                    "content": "Hello @John and @John",
                    "mentions": [
                        {"id": str(mentioned_user.id), "name": "John"},
                        {"id": str(mentioned_user.id), "name": "John"},
                    ],
                },
            )
        finally:
            post_save.connect(handle_thread_event_post_save, sender=models.ThreadEvent)

        self._run_backfill_logic()

        assert (
            models.UserEvent.objects.filter(
                thread_event=event, user=mentioned_user
            ).count()
            == 1
        )

    def test_backfill_skips_users_without_access(self):
        """Backfill should not create UserEvent for users without ThreadAccess."""
        author, _, thread, _ = self._setup_thread_with_mentioned_user()
        no_access_user = factories.UserFactory()

        post_save.disconnect(handle_thread_event_post_save, sender=models.ThreadEvent)
        try:
            models.ThreadEvent.objects.create(
                thread=thread,
                author=author,
                type="im",
                data={
                    "content": "Hello @Ghost",
                    "mentions": [
                        {"id": str(no_access_user.id), "name": "Ghost"},
                    ],
                },
            )
        finally:
            post_save.connect(handle_thread_event_post_save, sender=models.ThreadEvent)

        self._run_backfill_logic()

        assert models.UserEvent.objects.filter(user=no_access_user).count() == 0

    def test_backfill_is_idempotent(self):
        """Running backfill twice should not create duplicate UserEvents."""
        author, mentioned_user, thread, _ = self._setup_thread_with_mentioned_user()

        post_save.disconnect(handle_thread_event_post_save, sender=models.ThreadEvent)
        try:
            event = models.ThreadEvent.objects.create(
                thread=thread,
                author=author,
                type="im",
                data={
                    "content": "Hello @John",
                    "mentions": [{"id": str(mentioned_user.id), "name": "John"}],
                },
            )
        finally:
            post_save.connect(handle_thread_event_post_save, sender=models.ThreadEvent)

        # Run backfill twice
        self._run_backfill_logic()
        self._run_backfill_logic()

        assert (
            models.UserEvent.objects.filter(
                thread_event=event, user=mentioned_user, type="mention"
            ).count()
            == 1
        )

    def test_backfill_ignores_events_without_mentions(self):
        """Backfill should not create UserEvents for ThreadEvent IM without mentions."""
        author, _, thread, _ = self._setup_thread_with_mentioned_user()

        post_save.disconnect(handle_thread_event_post_save, sender=models.ThreadEvent)
        try:
            models.ThreadEvent.objects.create(
                thread=thread,
                author=author,
                type="im",
                data={"content": "Hello everyone"},
            )
        finally:
            post_save.connect(handle_thread_event_post_save, sender=models.ThreadEvent)

        initial_count = models.UserEvent.objects.count()
        self._run_backfill_logic()

        assert models.UserEvent.objects.count() == initial_count


class TestAssignUserEvents:
    """Test the create_assign_user_events helper and ASSIGN signal dispatch."""

    def _setup_thread_with_assigned_user(self):
        """Create a thread with a user who has full edit rights on it.

        Returns (author, target_user, thread, mailbox) tuple. Both author and
        target_user get ADMIN MailboxAccess and the shared ThreadAccess is
        EDITOR, so the assignment rule (full edit rights on the assignee) is
        satisfied deterministically. The default fuzzy role on
        ThreadAccessFactory/MailboxAccessFactory would otherwise make these
        tests flaky against the new editor-only assignment policy.
        """
        author = factories.UserFactory()
        mailbox = factories.MailboxFactory()
        factories.MailboxAccessFactory(
            mailbox=mailbox, user=author, role=enums.MailboxRoleChoices.ADMIN
        )
        thread = factories.ThreadFactory()
        factories.ThreadAccessFactory(
            thread=thread,
            mailbox=mailbox,
            role=enums.ThreadAccessRoleChoices.EDITOR,
        )
        target_user = factories.UserFactory()
        factories.MailboxAccessFactory(
            mailbox=mailbox,
            user=target_user,
            role=enums.MailboxRoleChoices.ADMIN,
        )
        return author, target_user, thread, mailbox

    def test_assign_creates_user_event(self):
        """ThreadEvent ASSIGN with valid assignee creates one UserEvent ASSIGN."""
        author, target_user, thread, _ = self._setup_thread_with_assigned_user()

        event = factories.ThreadEventFactory(
            thread=thread,
            author=author,
            type="assign",
            data={"assignees": [{"id": str(target_user.id), "name": "Target"}]},
        )

        user_events = models.UserEvent.objects.filter(
            thread_event=event,
            user=target_user,
            type=enums.UserEventTypeChoices.ASSIGN,
        )
        assert user_events.count() == 1

        user_event = user_events.first()
        assert user_event.read_at is None
        assert user_event.thread == thread

    def test_assign_with_two_valid_assignees_creates_two_user_events(self):
        """ThreadEvent ASSIGN with 2 valid assignees creates 2 UserEvent ASSIGN records."""
        author, target_user, thread, mailbox = self._setup_thread_with_assigned_user()
        target_user2 = factories.UserFactory()
        factories.MailboxAccessFactory(
            mailbox=mailbox,
            user=target_user2,
            role=enums.MailboxRoleChoices.ADMIN,
        )

        event = factories.ThreadEventFactory(
            thread=thread,
            author=author,
            type="assign",
            data={
                "assignees": [
                    {"id": str(target_user.id), "name": "Target1"},
                    {"id": str(target_user2.id), "name": "Target2"},
                ]
            },
        )

        assert (
            models.UserEvent.objects.filter(
                thread_event=event,
                type=enums.UserEventTypeChoices.ASSIGN,
            ).count()
            == 2
        )

    def test_assign_deduplicates_assignee_ids(self):
        """ThreadEvent ASSIGN with duplicate assignee IDs creates only 1 UserEvent."""
        author, target_user, thread, _ = self._setup_thread_with_assigned_user()

        event = factories.ThreadEventFactory(
            thread=thread,
            author=author,
            type="assign",
            data={
                "assignees": [
                    {"id": str(target_user.id), "name": "Target"},
                    {"id": str(target_user.id), "name": "Target"},
                ]
            },
        )

        assert (
            models.UserEvent.objects.filter(
                thread_event=event,
                user=target_user,
                type=enums.UserEventTypeChoices.ASSIGN,
            ).count()
            == 1
        )

    def test_assign_skips_assignee_without_thread_access(self):
        """Assignee without ThreadAccess should not get a UserEvent.

        Defence in depth: the API layer rejects such payloads with 400, but a
        ThreadEvent created outside the viewset (admin, migration, test) must
        still be filtered silently so the invariant never breaks.
        """
        author, _, thread, _ = self._setup_thread_with_assigned_user()
        no_access_user = factories.UserFactory()

        with patch("core.signals.logger") as mock_logger:
            factories.ThreadEventFactory(
                thread=thread,
                author=author,
                type="assign",
                data={
                    "assignees": [
                        {"id": str(no_access_user.id), "name": "NoAccess"},
                    ]
                },
            )

        assert (
            models.UserEvent.objects.filter(
                user=no_access_user,
                type=enums.UserEventTypeChoices.ASSIGN,
            ).count()
            == 0
        )
        mock_logger.warning.assert_called()

    def test_assign_skips_assignee_with_viewer_mailbox_access(self):
        """Assignee reachable only via a VIEWER MailboxAccess is filtered silently."""
        author, _, thread, mailbox = self._setup_thread_with_assigned_user()
        viewer_user = factories.UserFactory()
        factories.MailboxAccessFactory(
            mailbox=mailbox,
            user=viewer_user,
            role=enums.MailboxRoleChoices.VIEWER,
        )

        with patch("core.signals.logger") as mock_logger:
            factories.ThreadEventFactory(
                thread=thread,
                author=author,
                type="assign",
                data={"assignees": [{"id": str(viewer_user.id), "name": "Viewer"}]},
            )

        assert (
            models.UserEvent.objects.filter(
                user=viewer_user, type=enums.UserEventTypeChoices.ASSIGN
            ).count()
            == 0
        )
        mock_logger.warning.assert_called()

    def test_assign_skips_invalid_uuid(self):
        """Assignee with invalid UUID should not create a UserEvent."""
        author, _, thread, _ = self._setup_thread_with_assigned_user()
        initial_count = models.UserEvent.objects.filter(
            type=enums.UserEventTypeChoices.ASSIGN,
        ).count()

        with patch("core.signals.logger") as mock_logger:
            factories.ThreadEventFactory(
                thread=thread,
                author=author,
                type="assign",
                data={"assignees": [{"id": "not-a-valid-uuid", "name": "Bad"}]},
            )

        assert (
            models.UserEvent.objects.filter(
                type=enums.UserEventTypeChoices.ASSIGN,
            ).count()
            == initial_count
        )
        mock_logger.warning.assert_called()

    def test_signal_dispatches_assign(self):
        """Signal handler should call create_assign_user_events for ASSIGN events."""
        author, target_user, thread, _ = self._setup_thread_with_assigned_user()

        with patch("core.signals.create_assign_user_events") as mock_create:
            mock_create.return_value = []
            factories.ThreadEventFactory(
                thread=thread,
                author=author,
                type="assign",
                data={
                    "assignees": [
                        {"id": str(target_user.id), "name": "Target"},
                    ]
                },
            )
            mock_create.assert_called_once()

    @patch(
        "core.signals.create_assign_user_events",
        side_effect=RuntimeError("DB error"),
    )
    def test_assign_helper_failure_does_not_rollback_thread_event(self, mock_helper):
        """Verify SC-5 atomicity model: if create_assign_user_events fails,
        the broad catch in handle_thread_event_post_save protects the ThreadEvent save.
        The ThreadEvent persists but no UserEvent is created. Error is logged.
        """
        author, target_user, thread, _ = self._setup_thread_with_assigned_user()

        event = factories.ThreadEventFactory(
            thread=thread,
            author=author,
            type="assign",
            data={
                "assignees": [
                    {"id": str(target_user.id), "name": "Target"},
                ]
            },
        )
        # ThreadEvent IS persisted (broad catch protected it)
        assert models.ThreadEvent.objects.filter(id=event.id).exists()
        # No UserEvent was created (helper raised before bulk_create)
        assert (
            models.UserEvent.objects.filter(
                thread=thread, type=enums.UserEventTypeChoices.ASSIGN
            ).count()
            == 0
        )
        # Helper was called
        mock_helper.assert_called_once()


class TestDeleteAssignUserEvents:
    """Test the delete_assign_user_events helper and UNASSIGN signal dispatch."""

    def _setup_thread_with_assigned_user(self):
        """Create a thread with a user who has full edit rights on it."""
        author = factories.UserFactory()
        mailbox = factories.MailboxFactory()
        factories.MailboxAccessFactory(
            mailbox=mailbox, user=author, role=enums.MailboxRoleChoices.ADMIN
        )
        thread = factories.ThreadFactory()
        factories.ThreadAccessFactory(
            thread=thread,
            mailbox=mailbox,
            role=enums.ThreadAccessRoleChoices.EDITOR,
        )
        target_user = factories.UserFactory()
        factories.MailboxAccessFactory(
            mailbox=mailbox,
            user=target_user,
            role=enums.MailboxRoleChoices.ADMIN,
        )
        return author, target_user, thread, mailbox

    def test_unassign_deletes_existing_assign_user_event(self):
        """ThreadEvent UNASSIGN deletes existing UserEvent ASSIGN for the targeted users."""
        author, target_user, thread, _ = self._setup_thread_with_assigned_user()

        # First, create an ASSIGN event
        factories.ThreadEventFactory(
            thread=thread,
            author=author,
            type="assign",
            data={"assignees": [{"id": str(target_user.id), "name": "Target"}]},
        )

        # Verify ASSIGN exists
        assert (
            models.UserEvent.objects.filter(
                thread=thread,
                user=target_user,
                type=enums.UserEventTypeChoices.ASSIGN,
            ).count()
            == 1
        )

        # Now UNASSIGN
        factories.ThreadEventFactory(
            thread=thread,
            author=author,
            type="unassign",
            data={"assignees": [{"id": str(target_user.id), "name": "Target"}]},
        )

        # Verify ASSIGN is deleted
        assert (
            models.UserEvent.objects.filter(
                thread=thread,
                user=target_user,
                type=enums.UserEventTypeChoices.ASSIGN,
            ).count()
            == 0
        )

    def test_unassign_on_user_with_no_active_assign_updates_zero(self):
        """ThreadEvent UNASSIGN on user with no active ASSIGN updates 0 records."""
        author, target_user, thread, _ = self._setup_thread_with_assigned_user()

        # UNASSIGN without any prior ASSIGN
        factories.ThreadEventFactory(
            thread=thread,
            author=author,
            type="unassign",
            data={"assignees": [{"id": str(target_user.id), "name": "Target"}]},
        )

        # No UserEvent should exist
        assert (
            models.UserEvent.objects.filter(
                thread=thread,
                user=target_user,
                type=enums.UserEventTypeChoices.ASSIGN,
            ).count()
            == 0
        )

    def test_unassign_does_not_create_new_user_event(self):
        """ThreadEvent UNASSIGN removes the ASSIGN UserEvent and does not create
        any new UserEvent row (per D-12).

        The historical trace lives on the ThreadEvent UNASSIGN; we neither keep
        a deactivated copy of the UserEvent ASSIGN nor mint a new row of a
        different type.
        """
        author, target_user, thread, _ = self._setup_thread_with_assigned_user()

        # ASSIGN first — creates exactly one UserEvent ASSIGN.
        factories.ThreadEventFactory(
            thread=thread,
            author=author,
            type="assign",
            data={"assignees": [{"id": str(target_user.id), "name": "Target"}]},
        )
        assert models.UserEvent.objects.filter(thread=thread).count() == 1

        # UNASSIGN — deletes the existing ASSIGN row without creating new ones.
        factories.ThreadEventFactory(
            thread=thread,
            author=author,
            type="unassign",
            data={"assignees": [{"id": str(target_user.id), "name": "Target"}]},
        )

        assert models.UserEvent.objects.filter(thread=thread).count() == 0

    def test_signal_dispatches_unassign(self):
        """Signal handler should call delete_assign_user_events for UNASSIGN events."""
        author, target_user, thread, _ = self._setup_thread_with_assigned_user()

        with patch("core.signals.delete_assign_user_events") as mock_delete:
            mock_delete.return_value = 0
            factories.ThreadEventFactory(
                thread=thread,
                author=author,
                type="unassign",
                data={
                    "assignees": [
                        {"id": str(target_user.id), "name": "Target"},
                    ]
                },
            )
            mock_delete.assert_called_once()

    def test_unassign_with_invalid_uuid_logs_warning(self):
        """UNASSIGN with invalid UUID should log warning and update 0 records."""
        author, _, thread, _ = self._setup_thread_with_assigned_user()

        with patch("core.signals.logger") as mock_logger:
            factories.ThreadEventFactory(
                thread=thread,
                author=author,
                type="unassign",
                data={
                    "assignees": [
                        {"id": "not-a-valid-uuid", "name": "Bad"},
                    ]
                },
            )
        mock_logger.warning.assert_called()


class TestCleanupInvalidAssignments:
    """Auto-unassign on ThreadAccess / MailboxAccess delete or downgrade.

    The expected outcome is always the same: a system ``ThreadEvent(type=UNASSIGN,
    author=None)`` is created and the matching ``UserEvent(ASSIGN)`` row is gone.
    """

    def _setup_assigned_user(self):
        """Set up an author, an assigned user, and assign that user to the thread.

        Returns (author, assignee, thread, mailbox). Both author and assignee
        get full edit rights so the assignment itself is a valid starting
        point — the cleanup signals are what the tests are checking.
        """
        author = factories.UserFactory()
        mailbox = factories.MailboxFactory()
        factories.MailboxAccessFactory(
            mailbox=mailbox, user=author, role=enums.MailboxRoleChoices.ADMIN
        )
        assignee = factories.UserFactory()
        factories.MailboxAccessFactory(
            mailbox=mailbox, user=assignee, role=enums.MailboxRoleChoices.ADMIN
        )
        thread = factories.ThreadFactory()
        factories.ThreadAccessFactory(
            thread=thread,
            mailbox=mailbox,
            role=enums.ThreadAccessRoleChoices.EDITOR,
        )
        factories.ThreadEventFactory(
            thread=thread,
            author=author,
            type="assign",
            data={"assignees": [{"id": str(assignee.id), "name": "Assignee"}]},
        )
        assert models.UserEvent.objects.filter(
            user=assignee,
            thread=thread,
            type=enums.UserEventTypeChoices.ASSIGN,
        ).exists()
        return author, assignee, thread, mailbox

    def _assert_auto_unassigned(self, thread, assignee):
        """Check the UserEvent ASSIGN is gone and a system UNASSIGN was recorded."""
        assert not models.UserEvent.objects.filter(
            user=assignee,
            thread=thread,
            type=enums.UserEventTypeChoices.ASSIGN,
        ).exists()
        system_unassign = models.ThreadEvent.objects.filter(
            thread=thread,
            type=enums.ThreadEventTypeChoices.UNASSIGN,
            author__isnull=True,
        ).last()
        assert system_unassign is not None
        assignee_ids = [a["id"] for a in system_unassign.data["assignees"]]
        assert str(assignee.id) in assignee_ids

    def test_cleanup_on_thread_access_delete(self):
        """Deleting the ThreadAccess unassigns every user of that mailbox."""
        _author, assignee, thread, mailbox = self._setup_assigned_user()
        models.ThreadAccess.objects.filter(thread=thread, mailbox=mailbox).delete()
        self._assert_auto_unassigned(thread, assignee)

    def test_cleanup_on_thread_access_downgrade_to_viewer(self):
        """ThreadAccess role EDITOR -> VIEWER unassigns every user of that mailbox."""
        _author, assignee, thread, mailbox = self._setup_assigned_user()
        access = models.ThreadAccess.objects.get(thread=thread, mailbox=mailbox)
        access.role = enums.ThreadAccessRoleChoices.VIEWER
        access.save()
        self._assert_auto_unassigned(thread, assignee)

    def test_cleanup_on_mailbox_access_delete(self):
        """Removing the assignee's MailboxAccess unassigns them."""
        _author, assignee, thread, mailbox = self._setup_assigned_user()
        models.MailboxAccess.objects.filter(user=assignee, mailbox=mailbox).delete()
        self._assert_auto_unassigned(thread, assignee)

    def test_cleanup_on_mailbox_access_downgrade_to_viewer(self):
        """MailboxAccess role leaving MAILBOX_ROLES_CAN_EDIT unassigns the user."""
        _author, assignee, thread, mailbox = self._setup_assigned_user()
        access = models.MailboxAccess.objects.get(user=assignee, mailbox=mailbox)
        access.role = enums.MailboxRoleChoices.VIEWER
        access.save()
        self._assert_auto_unassigned(thread, assignee)

    def test_cleanup_skips_user_still_editor_via_other_mailbox(self):
        """No cleanup when the user still has full edit rights through another mailbox."""
        _author, assignee, thread, mailbox = self._setup_assigned_user()
        # Give the assignee a second mailbox + EDITOR ThreadAccess on the same thread
        other_mailbox = factories.MailboxFactory()
        factories.MailboxAccessFactory(
            mailbox=other_mailbox,
            user=assignee,
            role=enums.MailboxRoleChoices.ADMIN,
        )
        factories.ThreadAccessFactory(
            thread=thread,
            mailbox=other_mailbox,
            role=enums.ThreadAccessRoleChoices.EDITOR,
        )

        # Remove the first MailboxAccess — assignee keeps edit rights via the other.
        models.MailboxAccess.objects.filter(user=assignee, mailbox=mailbox).delete()

        # Assignment still active, no system UNASSIGN created.
        assert models.UserEvent.objects.filter(
            user=assignee,
            thread=thread,
            type=enums.UserEventTypeChoices.ASSIGN,
        ).exists()
        assert not models.ThreadEvent.objects.filter(
            thread=thread,
            type=enums.ThreadEventTypeChoices.UNASSIGN,
            author__isnull=True,
        ).exists()

    def test_cleanup_no_op_on_non_downgrade_role_change(self):
        """Role change within MAILBOX_ROLES_CAN_EDIT triggers no cleanup."""
        _author, assignee, thread, mailbox = self._setup_assigned_user()
        access = models.MailboxAccess.objects.get(user=assignee, mailbox=mailbox)
        access.role = enums.MailboxRoleChoices.SENDER
        access.save()

        assert models.UserEvent.objects.filter(
            user=assignee,
            thread=thread,
            type=enums.UserEventTypeChoices.ASSIGN,
        ).exists()
        assert not models.ThreadEvent.objects.filter(
            thread=thread,
            type=enums.ThreadEventTypeChoices.UNASSIGN,
            author__isnull=True,
        ).exists()

    def test_cleanup_no_op_when_user_not_assigned(self):
        """Deleting a ThreadAccess whose users are not assigned triggers no event."""
        author = factories.UserFactory()
        mailbox = factories.MailboxFactory()
        factories.MailboxAccessFactory(
            mailbox=mailbox, user=author, role=enums.MailboxRoleChoices.ADMIN
        )
        thread = factories.ThreadFactory()
        factories.ThreadAccessFactory(
            thread=thread,
            mailbox=mailbox,
            role=enums.ThreadAccessRoleChoices.EDITOR,
        )

        models.ThreadAccess.objects.filter(thread=thread, mailbox=mailbox).delete()

        assert not models.ThreadEvent.objects.filter(
            thread=thread,
            type=enums.ThreadEventTypeChoices.UNASSIGN,
        ).exists()
