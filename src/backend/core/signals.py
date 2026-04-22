"""Signal handlers for core models."""
# pylint: disable=unused-argument

import logging
import uuid

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver

from core import enums, models
from core.services.identity.keycloak import (
    sync_mailbox_to_keycloak_user,
    sync_maildomain_to_keycloak_group,
)
from core.services.search import MESSAGE_INDEX, get_opensearch_client
from core.services.search.tasks import (
    index_message_task,
    reindex_thread_task,
    update_threads_mailbox_flags_task,
)
from core.utils import ThreadStatsUpdateDeferrer

logger = logging.getLogger(__name__)


@receiver(post_save, sender=models.MailDomain)
def create_dkim_key(sender, instance, created, **kwargs):
    """Create a DKIM key for a new MailDomain."""
    if created:
        instance.generate_dkim_key()


@receiver(post_save, sender=models.MailDomain)
def sync_maildomain_to_keycloak(sender, instance, created, **kwargs):
    """Sync MailDomain to Keycloak as a group when saved."""
    if not instance.identity_sync or settings.IDENTITY_PROVIDER != "keycloak":
        return
    sync_maildomain_to_keycloak_group(instance)


@receiver(post_save, sender=models.Mailbox)
def sync_mailbox_to_keycloak(sender, instance, created, **kwargs):
    """Sync Mailbox to Keycloak as a user when saved."""
    if not instance.domain.identity_sync or settings.IDENTITY_PROVIDER != "keycloak":
        return

    # Ensure the maildomain group exists first
    sync_maildomain_to_keycloak_group(instance.domain)
    # Then sync the mailbox as a user
    sync_mailbox_to_keycloak_user(instance)


@receiver(post_save, sender=models.Message)
def index_message_post_save(sender, instance, created, **kwargs):
    """Index a message after it's saved."""
    if not settings.OPENSEARCH_INDEX_THREADS:
        return

    try:
        # Schedule the indexing task asynchronously
        index_message_task.delay(str(instance.id))
        # reindex_thread_task.delay(str(instance.thread.id))

    # pylint: disable=broad-exception-caught
    except Exception as e:
        logger.exception(
            "Error scheduling message indexing for message %s: %s",
            instance.id,
            e,
        )


@receiver(post_save, sender=models.MessageRecipient)
def index_message_recipient_post_save(sender, instance, created, **kwargs):
    """Index a message recipient after it's saved."""
    if not settings.OPENSEARCH_INDEX_THREADS:
        return

    try:
        # Schedule the indexing task asynchronously
        # TODO: deduplicate the indexing of the message!
        index_message_task.delay(str(instance.message.id))

    # pylint: disable=broad-exception-caught
    except Exception as e:
        logger.exception(
            "Error scheduling message indexing for message %s: %s",
            instance.message.id,
            e,
        )


@receiver(post_save, sender=models.MessageRecipient)
def update_thread_stats_on_delivery_status_change(sender, instance, **kwargs):
    """
    Update thread stats when a MessageRecipient delivery_status changes.

    Only triggers for outbound messages (is_sender=True) that are not drafts
    or trashed, since only those affect thread delivery stats.

    Supports batching via defer_thread_stats_update() context manager.
    """
    update_fields = kwargs.get("update_fields")

    # Only proceed if delivery_status was updated (or if update_fields is None,
    # meaning all fields were saved)
    if update_fields is not None and "delivery_status" not in update_fields:
        return

    message = instance.message

    # Only update stats for outbound messages that are not drafts or trashed
    # (matches the filter in Thread.update_stats())
    if not message.is_sender or message.is_draft or message.is_trashed:
        return

    thread = message.thread

    # If deferring is active, mark thread for later update
    if ThreadStatsUpdateDeferrer.defer_for(thread):
        return

    # Otherwise update immediately
    try:
        thread.update_stats()
    # pylint: disable=broad-exception-caught
    except Exception:
        logger.exception("Failed to update stats for thread %s", thread.id)


@receiver(post_save, sender=models.Thread)
def index_thread_post_save(sender, instance, created, **kwargs):
    """Index a thread after it's saved."""
    if not settings.OPENSEARCH_INDEX_THREADS:
        return

    try:
        # Schedule the indexing task asynchronously
        reindex_thread_task.delay(str(instance.id))

    # pylint: disable=broad-exception-caught
    except Exception as e:
        logger.exception(
            "Error scheduling thread indexing for thread %s: %s",
            instance.id,
            e,
        )


@receiver(pre_delete, sender=models.Message)
def delete_message_blobs(sender, instance, **kwargs):
    """Delete the blobs associated with a message."""
    if instance.blob:
        instance.blob.delete()
    if instance.draft_blob:
        instance.draft_blob.delete()


# @receiver(post_delete, sender=models.Attachment)
# def delete_attachments_blobs(sender, instance, **kwargs):
#     """Delete the blob associated with an attachment."""
#     if instance.blob:
#         instance.blob.delete()


@receiver(post_delete, sender=models.Message)
def delete_message_from_index(sender, instance, **kwargs):
    """Remove a message from the index after it's deleted."""
    if not settings.OPENSEARCH_INDEX_THREADS:
        return

    try:
        es = get_opensearch_client()
        # pylint: disable=unexpected-keyword-arg
        es.delete(
            index=MESSAGE_INDEX,
            id=str(instance.id),
            ignore=[404],  # Ignore if document doesn't exist or is already deleted
        )

    # pylint: disable=broad-exception-caught
    except Exception as e:
        logger.exception(
            "Error removing message %s from index: %s",
            instance.id,
            e,
        )


@receiver(post_delete, sender=models.Thread)
def delete_thread_from_index(sender, instance, **kwargs):
    """Remove a thread and its messages from the index after it's deleted."""
    if not settings.OPENSEARCH_INDEX_THREADS:
        return

    try:
        es = get_opensearch_client()

        # Delete the thread document
        # pylint: disable=unexpected-keyword-arg
        es.delete(
            index=MESSAGE_INDEX,
            id=str(instance.id),
            ignore=[404],  # Ignore if document doesn't exist
        )

        # Delete all child message documents using a query
        # pylint: disable=unexpected-keyword-arg
        es.delete_by_query(
            index=MESSAGE_INDEX,
            body={"query": {"term": {"thread_id": str(instance.id)}}},
            ignore=[404, 409],  # Ignore if no documents match
            conflicts="proceed",
        )
    # pylint: disable=broad-exception-caught
    except Exception as e:
        logger.exception(
            "Error removing thread %s and its messages from index: %s",
            instance.id,
            e,
        )


@receiver(pre_delete, sender=models.Message)
def delete_orphan_draft_attachments(sender, instance, **kwargs):
    """Remove orphan attachments after a draft message is deleted."""

    # Get all attachments that are not used by any other message
    if instance.is_draft:
        attachments = models.Attachment.objects.filter(messages=instance)

        for attachment in attachments:
            if attachment.messages.count() == 1:
                attachment.blob.delete()  # this will cascade delete the attachment

        if instance.draft_blob and instance.draft_blob.pk:
            instance.draft_blob.delete()

    if instance.blob and instance.blob.pk:
        if instance.blob.messages.count() == 1:
            instance.blob.delete()


@receiver(post_save, sender=models.ThreadAccess)
def update_mailbox_flags_on_access_save(sender, instance, created, **kwargs):
    """Update mailbox flags in OpenSearch when ThreadAccess read/starred state changes."""
    if not settings.OPENSEARCH_INDEX_THREADS:
        return

    update_fields = kwargs.get("update_fields")
    if update_fields is not None and not (
        {"read_at", "starred_at"} & set(update_fields)
    ):
        return

    thread_id = str(instance.thread_id)
    try:
        transaction.on_commit(
            lambda tid=thread_id: update_threads_mailbox_flags_task.delay([tid])
        )
    # pylint: disable=broad-exception-caught
    except Exception as e:
        logger.exception(
            "Error scheduling unread_mailboxes update for thread %s: %s",
            instance.thread_id,
            e,
        )


@receiver(post_delete, sender=models.ThreadAccess)
def update_unread_mailboxes_on_access_delete(sender, instance, **kwargs):
    """Update unread_mailboxes in OpenSearch when a ThreadAccess is deleted."""
    if not settings.OPENSEARCH_INDEX_THREADS:
        return

    thread_id = str(instance.thread_id)
    try:
        transaction.on_commit(
            lambda tid=thread_id: update_threads_mailbox_flags_task.delay([tid])
        )
    # pylint: disable=broad-exception-caught
    except Exception as e:
        logger.exception(
            "Error scheduling unread_mailboxes update for thread %s: %s",
            instance.thread_id,
            e,
        )


@receiver(pre_delete, sender=models.User)
def delete_user_scope_channels_on_user_delete(sender, instance, **kwargs):
    """Delete the user's personal (scope_level=user) Channels before the
    user row is removed.

    Channel.user uses on_delete=SET_NULL deliberately — the FK alone must
    not blanket-cascade, because a future relaxation of the
    channel_scope_level_targets check constraint could otherwise let a
    user delete silently sweep up unrelated channels. This handler is the
    *only* place where user-scope channels are removed in response to a
    user deletion. The query is filtered explicitly on
    ``scope_level=user``, never on the FK alone.

    If we did not delete these rows here, SET_NULL on the FK would null
    ``user_id`` on the user-scope rows, immediately violating the check
    constraint and aborting the user delete with an IntegrityError — so
    this signal is also load-bearing for user deletion to succeed at all.
    """
    models.Channel.objects.filter(
        user=instance,
        scope_level=enums.ChannelScopeLevel.USER,
    ).delete()


def _parse_and_dedupe_user_ids(thread_event, users_data):
    """Extract unique, well-formed UUIDs from a list of user-shape dicts.

    Skips entries with missing or malformed ``id`` fields, logging a warning
    for UUID parse errors. Order is preserved for the first occurrence of
    each id so callers that diff against existing state remain stable.
    """
    seen_user_ids = set()
    unique_user_ids = []
    for entry in users_data or []:
        raw_id = entry.get("id")
        if not raw_id:
            continue
        try:
            user_id = uuid.UUID(raw_id)
        except (ValueError, AttributeError):
            logger.warning(
                "Skipping user with invalid UUID '%s' in ThreadEvent %s",
                raw_id,
                thread_event.id,
            )
            continue
        if user_id not in seen_user_ids:
            seen_user_ids.add(user_id)
            unique_user_ids.append(user_id)
    return unique_user_ids


def _validate_user_ids_with_access(thread_event, thread, users_data):
    """Validate user IDs have any ThreadAccess on ``thread`` (viewer included).

    Used by MENTION: posting an internal comment on a thread makes sense for
    any user who can read it, so VIEWER access is enough. Silently drops and
    logs users that do not match.
    """
    unique_user_ids = _parse_and_dedupe_user_ids(thread_event, users_data)
    if not unique_user_ids:
        return set()

    # Chain: User -> MailboxAccess.user -> MailboxAccess.mailbox -> ThreadAccess.mailbox
    valid_user_ids = set(
        models.ThreadAccess.objects.filter(
            thread=thread,
            mailbox__accesses__user_id__in=unique_user_ids,
        ).values_list("mailbox__accesses__user_id", flat=True)
    )

    for user_id in unique_user_ids:
        if user_id not in valid_user_ids:
            logger.warning(
                "Skipping user %s in ThreadEvent %s: "
                "user not found or no thread access",
                user_id,
                thread_event.id,
            )

    return valid_user_ids


def _validate_user_ids_with_edit_rights(thread_event, thread, users_data):
    """Validate user IDs have full edit rights on ``thread``.

    Used by ASSIGN: the API layer enforces the same rule upstream, so this
    is a defence-in-depth filter for events created outside the viewset
    (admin, batch jobs, data migrations) where the invariant may otherwise
    be silently violated. Uses :meth:`ThreadAccessQuerySet.editor_user_ids`
    as the single source of truth for the "editor" rule.
    """
    unique_user_ids = _parse_and_dedupe_user_ids(thread_event, users_data)
    if not unique_user_ids:
        return set()

    valid_user_ids = set(
        models.ThreadAccess.objects.editor_user_ids(thread.id, user_ids=unique_user_ids)
    )

    for user_id in unique_user_ids:
        if user_id not in valid_user_ids:
            logger.warning(
                "Skipping user %s in ThreadEvent %s: "
                "user does not have edit rights on the thread",
                user_id,
                thread_event.id,
            )

    return valid_user_ids


def sync_mention_user_events(thread_event, thread, mentions_data):
    """Sync UserEvent MENTION records to match the current mentions payload.

    Diffs the currently mentioned users against the existing UserEvent MENTION
    records for this ThreadEvent and reconciles the two:
    - Creates UserEvent records for newly mentioned users.
    - Deletes UserEvent records for users who are no longer mentioned so that
      stale entries do not linger in the "Mentioned" folder after an edit.
    - Leaves existing records untouched when the user is still mentioned, which
      preserves their ``read_at`` state across edits.

    Invalid or unauthorized mentions are silently skipped with a warning log.

    Args:
        thread_event: The ThreadEvent instance containing mentions.
        thread: The Thread instance.
        mentions_data: List of mention dicts with 'id' and 'name' keys.
    """
    new_valid_user_ids = _validate_user_ids_with_access(
        thread_event, thread, mentions_data
    )

    existing_user_ids = set(
        models.UserEvent.objects.filter(
            thread_event=thread_event,
            type=enums.UserEventTypeChoices.MENTION,
        ).values_list("user_id", flat=True)
    )

    to_add = new_valid_user_ids - existing_user_ids
    to_remove = existing_user_ids - new_valid_user_ids

    if to_remove:
        deleted_count, _ = models.UserEvent.objects.filter(
            thread_event=thread_event,
            type=enums.UserEventTypeChoices.MENTION,
            user_id__in=to_remove,
        ).delete()
        if deleted_count:
            logger.info(
                "Deleted %d UserEvent MENTION(s) for ThreadEvent %s",
                deleted_count,
                thread_event.id,
            )

    if to_add:
        user_events = [
            models.UserEvent(
                user_id=user_id,
                thread=thread,
                thread_event=thread_event,
                type=enums.UserEventTypeChoices.MENTION,
            )
            for user_id in to_add
        ]
        # ignore_conflicts=True lets the UniqueConstraint on
        # (user, thread_event, type) absorb races between concurrent
        # post_save signals on the same ThreadEvent (e.g. two PATCH in flight).
        models.UserEvent.objects.bulk_create(user_events, ignore_conflicts=True)
        logger.info(
            "Created %d UserEvent MENTION(s) for ThreadEvent %s",
            len(user_events),
            thread_event.id,
        )


def create_assign_user_events(thread_event, thread, assignees_data):
    """Create UserEvent ASSIGN records for valid assignees.

    Each valid assignee gets a UserEvent(type=ASSIGN, read_at=None). Assignees
    that do not have full edit rights on the thread are silently dropped
    (defence in depth — the API layer enforces the same rule upstream).

    Args:
        thread_event: The ThreadEvent instance containing assignment data.
        thread: The Thread instance.
        assignees_data: List of assignee dicts with 'id' and 'name' keys.

    Returns:
        List of created UserEvent instances.
    """
    valid_user_ids = _validate_user_ids_with_edit_rights(
        thread_event, thread, assignees_data
    )
    if not valid_user_ids:
        return []

    user_events = [
        models.UserEvent(
            user_id=user_id,
            thread=thread,
            thread_event=thread_event,
            type=enums.UserEventTypeChoices.ASSIGN,
        )
        for user_id in valid_user_ids
    ]
    # ignore_conflicts=True lets the partial UniqueConstraint on
    # (user, thread) WHERE type=ASSIGN absorb races between concurrent ASSIGN
    # requests: the viewset's "already_assigned" check and the bulk_create are
    # not atomic, so two requests can both decide to create a UserEvent for
    # the same (user, thread); the DB is the final arbiter.
    models.UserEvent.objects.bulk_create(user_events, ignore_conflicts=True)
    return user_events


def delete_assign_user_events(thread_event, thread, assignees_data):
    """Delete UserEvent ASSIGN records for specified assignees.

    Removing the UserEvent is the source of truth for "no longer assigned":
    the ThreadEvent UNASSIGN entry itself carries the historical trace, so we
    do not keep a deactivated copy around.

    Args:
        thread_event: The ThreadEvent instance (for logging context). May be
            ``None`` when the deletion is triggered by the undo-window absorbing
            an UNASSIGN before any ThreadEvent is created.
        thread: The Thread instance.
        assignees_data: List of assignee dicts with 'id' and 'name' keys.

    Returns:
        Number of UserEvent records deleted.
    """
    if not assignees_data:
        return 0

    context = thread_event.id if thread_event else "<undo-window>"

    user_ids = set()
    for assignee in assignees_data:
        raw_id = assignee.get("id")
        if not raw_id:
            continue
        try:
            user_ids.add(uuid.UUID(raw_id))
        except (ValueError, AttributeError):
            logger.warning(
                "Skipping unassign with invalid UUID '%s' in context %s",
                raw_id,
                context,
            )

    if not user_ids:
        return 0

    deleted, _ = models.UserEvent.objects.filter(
        thread=thread,
        user_id__in=user_ids,
        type=enums.UserEventTypeChoices.ASSIGN,
    ).delete()

    if deleted:
        logger.info(
            "Deleted %d UserEvent ASSIGN(s) in context %s",
            deleted,
            context,
        )

    return deleted


def cleanup_invalid_assignments(thread, user_ids):
    """Unassign users that lost full edit rights on ``thread``.

    Called from the access-change signals (ThreadAccess / MailboxAccess
    delete or downgrade). Among ``user_ids``, keeps only those currently
    assigned *and* no longer qualifying as editors, then records a single
    system ``ThreadEvent(type=UNASSIGN, author=None)`` grouping all of them.
    The existing ``ThreadEvent`` post_save handler takes care of deleting
    the matching ``UserEvent ASSIGN`` rows.

    Uses :meth:`ThreadAccessQuerySet.editor_user_ids` as the single source
    of truth for the editor rule — a user reachable through multiple
    mailboxes keeps their assignment as long as at least one path still
    grants editor rights.
    """
    user_ids = set(user_ids)
    if not user_ids:
        return

    assigned_user_ids = set(
        models.UserEvent.objects.filter(
            thread=thread,
            user_id__in=user_ids,
            type=enums.UserEventTypeChoices.ASSIGN,
        ).values_list("user_id", flat=True)
    )
    if not assigned_user_ids:
        return

    still_editors = set(
        models.ThreadAccess.objects.editor_user_ids(
            thread.id, user_ids=assigned_user_ids
        )
    )
    to_unassign = assigned_user_ids - still_editors
    if not to_unassign:
        return

    users = models.User.objects.filter(id__in=to_unassign).values(
        "id", "full_name", "email"
    )
    assignees_data = [
        {"id": str(u["id"]), "name": u["full_name"] or u["email"] or ""} for u in users
    ]
    if not assignees_data:
        return

    models.ThreadEvent.objects.create(
        thread=thread,
        type=enums.ThreadEventTypeChoices.UNASSIGN,
        author=None,
        data={"assignees": assignees_data},
    )
    logger.info(
        "Auto-unassigned %d user(s) on thread %s after access change",
        len(assignees_data),
        thread.id,
    )


# post_save does not expose the previous field values, so we read them from
# the DB in pre_save and stash them on the instance for the post_save handler.
# A DB read rather than ``update_fields`` inspection because callers can omit
# ``update_fields`` entirely, which would then silently skip cleanup.
@receiver(pre_save, sender=models.ThreadAccess)
@receiver(pre_save, sender=models.MailboxAccess)
def stash_previous_role(sender, instance, **kwargs):
    """Stash the pre-save ``role`` value so post_save can detect downgrades."""
    if not instance.pk:
        instance._previous_role = None  # noqa: SLF001 pylint: disable=protected-access
        return
    try:
        previous = sender.objects.only("role").get(pk=instance.pk)
    except sender.DoesNotExist:
        instance._previous_role = None  # noqa: SLF001 pylint: disable=protected-access
        return
    instance._previous_role = previous.role  # noqa: SLF001 pylint: disable=protected-access


@receiver(post_save, sender=models.ThreadAccess)
def cleanup_assignments_on_thread_access_downgrade(sender, instance, created, **kwargs):
    """Unassign users of this mailbox when ThreadAccess loses EDITOR role."""
    if created:
        return
    previous_role = getattr(instance, "_previous_role", None)
    if previous_role != enums.ThreadAccessRoleChoices.EDITOR:
        return
    if instance.role == enums.ThreadAccessRoleChoices.EDITOR:
        return
    user_ids = list(instance.mailbox.accesses.values_list("user_id", flat=True))
    try:
        cleanup_invalid_assignments(instance.thread, user_ids)
    # pylint: disable=broad-exception-caught
    except Exception as e:
        logger.exception(
            "Error cleaning assignments on ThreadAccess downgrade %s: %s",
            instance.pk,
            e,
        )


@receiver(post_delete, sender=models.ThreadAccess)
def cleanup_assignments_on_thread_access_delete(sender, instance, **kwargs):
    """Unassign users of this mailbox when their ThreadAccess is deleted.

    The row is gone by the time the signal fires, but ``instance.mailbox`` and
    ``instance.thread`` remain accessible on the in-memory instance so we can
    still enumerate the impacted users.
    """
    try:
        user_ids = list(instance.mailbox.accesses.values_list("user_id", flat=True))
        cleanup_invalid_assignments(instance.thread, user_ids)
    # pylint: disable=broad-exception-caught
    except Exception as e:
        logger.exception(
            "Error cleaning assignments on ThreadAccess delete %s: %s",
            instance.pk,
            e,
        )


def _cleanup_threads_for_mailbox_user(mailbox_id, user_id):
    """Cleanup assignments of ``user_id`` across threads of ``mailbox_id``.

    Narrows to threads where the user has an active ASSIGN to avoid iterating
    over the full set of threads shared with the mailbox — a user may be
    assigned only on a small subset.
    """
    threads = models.Thread.objects.filter(
        accesses__mailbox_id=mailbox_id,
        user_events__user_id=user_id,
        user_events__type=enums.UserEventTypeChoices.ASSIGN,
    ).distinct()
    for thread in threads:
        cleanup_invalid_assignments(thread, [user_id])


@receiver(post_save, sender=models.MailboxAccess)
def cleanup_assignments_on_mailbox_access_downgrade(
    sender, instance, created, **kwargs
):
    """Unassign this user when their MailboxAccess leaves MAILBOX_ROLES_CAN_EDIT."""
    if created:
        return
    previous_role = getattr(instance, "_previous_role", None)
    was_editor = previous_role in enums.MAILBOX_ROLES_CAN_EDIT
    is_editor = instance.role in enums.MAILBOX_ROLES_CAN_EDIT
    if not was_editor or is_editor:
        return
    try:
        _cleanup_threads_for_mailbox_user(instance.mailbox_id, instance.user_id)
    # pylint: disable=broad-exception-caught
    except Exception as e:
        logger.exception(
            "Error cleaning assignments on MailboxAccess downgrade %s: %s",
            instance.pk,
            e,
        )


@receiver(post_delete, sender=models.MailboxAccess)
def cleanup_assignments_on_mailbox_access_delete(sender, instance, **kwargs):
    """Unassign this user across threads of the mailbox they just left."""
    try:
        _cleanup_threads_for_mailbox_user(instance.mailbox_id, instance.user_id)
    # pylint: disable=broad-exception-caught
    except Exception as e:
        logger.exception(
            "Error cleaning assignments on MailboxAccess delete %s: %s",
            instance.pk,
            e,
        )


@receiver(post_save, sender=models.ThreadEvent)
def handle_thread_event_post_save(sender, instance, created, **kwargs):
    """Handle post-save signal for ThreadEvent to sync UserEvent records.

    Dispatches by ThreadEvent type:
    - IM: Creates UserEvent MENTION for mentioned users
    - ASSIGN: Creates UserEvent ASSIGN for assignees
    - UNASSIGN: Deactivates existing UserEvent ASSIGN for assignees
    """
    try:
        if instance.type == enums.ThreadEventTypeChoices.IM:
            sync_mention_user_events(
                thread_event=instance,
                thread=instance.thread,
                mentions_data=(instance.data or {}).get("mentions", []),
            )

        elif instance.type == enums.ThreadEventTypeChoices.ASSIGN:
            assignees_data = (instance.data or {}).get("assignees", [])
            if assignees_data:
                created_events = create_assign_user_events(
                    thread_event=instance,
                    thread=instance.thread,
                    assignees_data=assignees_data,
                )
                if created_events:
                    logger.info(
                        "Created %d UserEvent ASSIGN(s) for ThreadEvent %s",
                        len(created_events),
                        instance.id,
                    )

        elif instance.type == enums.ThreadEventTypeChoices.UNASSIGN:
            assignees_data = (instance.data or {}).get("assignees", [])
            if assignees_data:
                delete_assign_user_events(
                    thread_event=instance,
                    thread=instance.thread,
                    assignees_data=assignees_data,
                )

    # pylint: disable=broad-exception-caught
    except Exception as e:
        logger.exception(
            "Error in ThreadEvent post_save handler for event %s: %s",
            instance.id,
            e,
        )
