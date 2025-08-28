"""Signal handlers for core models."""
# pylint: disable=unused-argument

import logging

from django.conf import settings
from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver

from core import models
from core.services.identity.keycloak import (
    sync_mailbox_to_keycloak_user,
    sync_maildomain_to_keycloak_group,
)
from core.services.search import MESSAGE_INDEX, get_opensearch_client
from core.services.search.tasks import index_message_task, reindex_thread_task

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
    if not getattr(settings, "OPENSEARCH_INDEX_THREADS", False):
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
    if not getattr(settings, "OPENSEARCH_INDEX_THREADS", False):
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


@receiver(post_save, sender=models.Thread)
def index_thread_post_save(sender, instance, created, **kwargs):
    """Index a thread after it's saved."""
    if not getattr(settings, "OPENSEARCH_INDEX_THREADS", False):
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


@receiver(post_delete, sender=models.Message)
def delete_message_from_index(sender, instance, **kwargs):
    """Remove a message from the index after it's deleted."""
    if not getattr(settings, "OPENSEARCH_INDEX_THREADS", False):
        return

    try:
        es = get_opensearch_client()
        # pylint: disable=unexpected-keyword-arg
        es.delete(
            index=MESSAGE_INDEX,
            id=str(instance.id),
            ignore=[404],  # Ignore if document doesn't exist
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
    if not getattr(settings, "OPENSEARCH_INDEX_THREADS", False):
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
            ignore=[404],  # Ignore if no documents match
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

        if instance.draft_blob:
            instance.draft_blob.delete()

    if instance.blob:
        if instance.blob.messages.count() == 1:
            instance.blob.delete()
