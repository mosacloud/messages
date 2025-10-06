"""Test marking messages as read/unread."""

# pylint: disable=redefined-outer-name

import json

from django.urls import reverse
from django.utils import timezone

import pytest
from rest_framework import status

from core import enums
from core.factories import (
    MailboxFactory,
    MessageFactory,
    ThreadAccessFactory,
    ThreadFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db

API_URL = reverse("change-flag")


def test_api_flag_mark_messages_unread_success(api_client):
    """Test marking messages as unread successfully."""
    user = UserFactory()
    api_client.force_authenticate(user=user)
    mailbox = MailboxFactory(users_read=[user])
    thread = ThreadFactory()
    ThreadAccessFactory(
        mailbox=mailbox, thread=thread, role=enums.ThreadAccessRoleChoices.EDITOR
    )
    # Start with messages marked as read (read_at is set, is_unread=False)
    msg1 = MessageFactory(
        thread=thread, is_unread=False, read_at=timezone.now(), is_trashed=False
    )
    msg2 = MessageFactory(
        thread=thread, is_unread=False, read_at=timezone.now(), is_trashed=False
    )
    msg3 = MessageFactory(
        thread=thread, is_unread=True, read_at=None, is_trashed=False
    )  # Already unread

    # Check initial thread state
    thread.update_stats()
    thread.refresh_from_db()
    assert thread.has_unread is True

    message_ids = [str(msg1.id), str(msg2.id)]
    data = {"flag": "unread", "value": True, "message_ids": message_ids}
    response = api_client.post(API_URL, data=data, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["updated_threads"] == 1

    # Verify messages are marked as unread (is_unread=True, read_at=None)
    msg1.refresh_from_db()
    msg2.refresh_from_db()
    msg3.refresh_from_db()
    assert msg1.is_unread is True
    assert msg1.read_at is None
    assert msg2.is_unread is True
    assert msg2.read_at is None
    assert msg3.is_unread is True  # Remained unread

    # Verify thread unread flag updated
    thread.refresh_from_db()
    assert thread.has_unread is True


def test_api_flag_mark_messages_read_success(api_client):
    """Test marking messages as read successfully."""
    user = UserFactory()
    api_client.force_authenticate(user=user)
    mailbox = MailboxFactory(users_read=[user])
    thread = ThreadFactory()
    ThreadAccessFactory(
        mailbox=mailbox, thread=thread, role=enums.ThreadAccessRoleChoices.EDITOR
    )
    # Start with messages marked as unread (is_unread=True, read_at=None)
    msg1 = MessageFactory(thread=thread, is_unread=True, read_at=None, is_trashed=False)
    msg2 = MessageFactory(thread=thread, is_unread=True, read_at=None, is_trashed=False)
    msg3 = MessageFactory(
        thread=thread, is_unread=False, read_at=timezone.now(), is_trashed=False
    )  # Already read

    # Check initial thread state
    thread.update_stats()
    thread.refresh_from_db()
    assert thread.has_unread is True

    message_ids = [str(msg1.id), str(msg2.id)]
    data = {"flag": "unread", "value": False, "message_ids": message_ids}
    response = api_client.post(API_URL, data=data, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["updated_threads"] == 1

    # Verify messages are marked as read (is_unread=False, read_at is set)
    msg1.refresh_from_db()
    msg2.refresh_from_db()
    msg3.refresh_from_db()
    assert msg1.is_unread is False
    assert msg1.read_at is not None
    assert msg2.is_unread is False
    assert msg2.read_at is not None
    assert msg3.is_unread is False  # Remained read

    # Verify thread unread flag updated
    thread.refresh_from_db()
    assert thread.has_unread is False


def test_api_flag_mark_thread_messages_unread_success(api_client):
    """Test marking all messages in a thread as unread."""
    user = UserFactory()
    api_client.force_authenticate(user=user)
    mailbox = MailboxFactory(users_read=[user])
    thread = ThreadFactory()
    ThreadAccessFactory(
        mailbox=mailbox, thread=thread, role=enums.ThreadAccessRoleChoices.EDITOR
    )
    # Messages start as read
    msg1 = MessageFactory(thread=thread, is_unread=False, read_at=timezone.now())
    msg2 = MessageFactory(thread=thread, is_unread=False, read_at=timezone.now())

    thread.refresh_from_db()
    thread.update_stats()
    assert thread.has_unread is False

    data = {"flag": "unread", "value": True, "thread_ids": [str(thread.id)]}
    response = api_client.post(API_URL, data=data, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["updated_threads"] == 1

    msg1.refresh_from_db()
    msg2.refresh_from_db()
    assert msg1.is_unread is True
    assert msg1.read_at is None
    assert msg2.is_unread is True
    assert msg2.read_at is None

    thread.refresh_from_db()
    assert thread.has_unread is True


def test_api_flag_mark_thread_messages_read_success(api_client):
    """Test marking all messages in a thread as read."""
    user = UserFactory()
    api_client.force_authenticate(user=user)
    mailbox = MailboxFactory(users_read=[user])
    thread = ThreadFactory()
    ThreadAccessFactory(
        mailbox=mailbox, thread=thread, role=enums.ThreadAccessRoleChoices.EDITOR
    )
    # Messages start as unread
    msg1 = MessageFactory(thread=thread, is_unread=True, read_at=None)
    msg2 = MessageFactory(thread=thread, is_unread=True, read_at=None)

    thread.refresh_from_db()
    thread.update_stats()
    assert thread.has_unread is True

    data = {"flag": "unread", "value": False, "thread_ids": [str(thread.id)]}
    response = api_client.post(API_URL, data=data, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["updated_threads"] == 1

    msg1.refresh_from_db()
    msg2.refresh_from_db()
    assert msg1.is_unread is False
    assert msg1.read_at is not None
    assert msg2.is_unread is False
    assert msg2.read_at is not None

    thread.refresh_from_db()
    assert thread.has_unread is False


def test_api_flag_mark_multiple_threads_read_success(api_client):
    """Test marking all messages in multiple threads as read."""
    user = UserFactory()
    api_client.force_authenticate(user=user)
    mailbox = MailboxFactory(users_read=[user])
    # Threads start with unread messages
    thread1 = ThreadFactory()
    ThreadAccessFactory(
        mailbox=mailbox, thread=thread1, role=enums.ThreadAccessRoleChoices.EDITOR
    )
    MessageFactory(thread=thread1, is_unread=True)
    thread2 = ThreadFactory()
    ThreadAccessFactory(
        mailbox=mailbox, thread=thread2, role=enums.ThreadAccessRoleChoices.EDITOR
    )
    MessageFactory(thread=thread2, is_unread=True)
    thread3 = ThreadFactory()  # No messages initially
    ThreadAccessFactory(
        mailbox=mailbox, thread=thread3, role=enums.ThreadAccessRoleChoices.EDITOR
    )
    MessageFactory(
        thread=thread3, is_unread=False, read_at=timezone.now()
    )  # Already read

    thread1.refresh_from_db()
    thread1.update_stats()
    thread2.refresh_from_db()
    thread2.update_stats()
    thread3.refresh_from_db()
    thread3.update_stats()
    assert thread1.has_unread is True
    assert thread2.has_unread is True
    assert thread3.has_unread is False

    thread_ids = [str(thread1.id), str(thread2.id)]
    data = {"flag": "unread", "value": False, "thread_ids": thread_ids}
    response = api_client.post(API_URL, data=data, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["updated_threads"] == 2

    thread1.refresh_from_db()
    thread2.refresh_from_db()
    thread3.refresh_from_db()  # Should remain unchanged
    assert thread1.has_unread is False
    assert thread2.has_unread is False
    assert thread3.has_unread is False


def test_api_flag_mark_messages_unauthorized(api_client):
    """Test marking messages without authentication."""
    response = api_client.post(API_URL, data={}, format="json")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_api_flag_mark_messages_no_permission(api_client):
    """Test marking messages in a mailbox the user doesn't have access to."""
    user = UserFactory()
    api_client.force_authenticate(user=user)
    other_mailbox = MailboxFactory()  # User does not have access
    thread = ThreadFactory()
    ThreadAccessFactory(
        mailbox=other_mailbox, thread=thread, role=enums.ThreadAccessRoleChoices.EDITOR
    )
    msg = MessageFactory(thread=thread, is_unread=True)

    data = {"flag": "unread", "value": False, "message_ids": [str(msg.id)]}
    response = api_client.post(API_URL, data=data, format="json")

    # The endpoint should process successfully but update 0 messages as the filter excludes them
    assert response.status_code == status.HTTP_200_OK
    assert response.data["updated_threads"] == 0

    # Verify message state hasn't changed
    msg.refresh_from_db()
    assert msg.is_unread is True


@pytest.mark.parametrize(
    "data",
    [
        {"value": True, "message_ids": lambda msg: [str(msg.id)]},  # missing flag
        {"flag": "unread", "message_ids": lambda msg: [str(msg.id)]},  # missing value
        {"flag": "unread", "value": True},  # missing message_ids and thread_ids
        {
            "flag": "invalid_flag",
            "value": True,
            "message_ids": lambda msg: [str(msg.id)],
        },  # invalid flag
        {
            "flag": "unread",
            "value": "maybe",
            "message_ids": lambda msg: [str(msg.id)],
        },  # invalid value
        {
            "flag": "unread",
            "value": True,
            "message_ids": [],
            "thread_ids": [],
        },  # empty ids
        {"flag": "unread", "value": True, "message_ids": ["aa"]},  # invalid message ids
        {
            "flag": "unread",
            "value": True,
            "message_ids": {"test": "test"},
        },  # invalid message ids
    ],
)
def test_api_flag_mark_messages_invalid_requests(api_client, data):
    """
    Parametrized test for invalid flag, missing ids, and invalid value.
    """
    user = UserFactory()
    api_client.force_authenticate(user=user)
    mailbox = MailboxFactory(users_read=[user])
    thread = ThreadFactory()
    ThreadAccessFactory(
        mailbox=mailbox, thread=thread, role=enums.ThreadAccessRoleChoices.EDITOR
    )
    msg = MessageFactory(thread=thread)
    if callable(data.get("message_ids", None)):
        data["message_ids"] = json.loads(json.dumps(data["message_ids"](msg)))
    if callable(data.get("thread_ids", None)):
        data["thread_ids"] = json.loads(json.dumps(data["thread_ids"](thread)))
    response = api_client.post(API_URL, data=data, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST


# --- Tests for Starred Flag ---


def test_api_flag_mark_messages_starred_success(api_client):
    """Test marking messages as starred successfully."""
    user = UserFactory()
    api_client.force_authenticate(user=user)
    mailbox = MailboxFactory(users_read=[user])
    thread = ThreadFactory()
    ThreadAccessFactory(
        mailbox=mailbox, thread=thread, role=enums.ThreadAccessRoleChoices.EDITOR
    )
    msg1 = MessageFactory(thread=thread, is_starred=False)
    msg2 = MessageFactory(thread=thread, is_starred=True)  # Already starred

    thread.refresh_from_db()
    thread.update_stats()
    assert thread.has_starred is True

    message_ids = [str(msg1.id)]
    data = {"flag": "starred", "value": True, "message_ids": message_ids}
    response = api_client.post(API_URL, data=data, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["updated_threads"] == 1

    msg1.refresh_from_db()
    msg2.refresh_from_db()
    assert msg1.is_starred is True
    assert msg2.is_starred is True

    thread.refresh_from_db()
    assert thread.has_starred is True


def test_api_flag_mark_messages_unstarred_success(api_client):
    """Test marking messages as unstarred successfully."""
    user = UserFactory()
    api_client.force_authenticate(user=user)
    mailbox = MailboxFactory(users_read=[user])
    thread = ThreadFactory()
    ThreadAccessFactory(
        mailbox=mailbox, thread=thread, role=enums.ThreadAccessRoleChoices.EDITOR
    )
    msg1 = MessageFactory(thread=thread, is_starred=True)
    msg2 = MessageFactory(thread=thread, is_starred=False)  # Already unstarred

    thread.refresh_from_db()
    thread.update_stats()
    assert thread.has_starred is True

    message_ids = [str(msg1.id)]
    data = {"flag": "starred", "value": False, "message_ids": message_ids}
    response = api_client.post(API_URL, data=data, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["updated_threads"] == 1

    msg1.refresh_from_db()
    msg2.refresh_from_db()
    assert msg1.is_starred is False
    assert msg2.is_starred is False

    thread.refresh_from_db()
    assert thread.has_starred is False


# --- Tests for Trashed Flag ---


def test_api_flag_mark_messages_trashed_success(api_client):
    """Test marking messages as trashed successfully."""
    user = UserFactory()
    api_client.force_authenticate(user=user)
    mailbox = MailboxFactory(users_read=[user])  # Ensure correct permission if needed
    thread = ThreadFactory()
    ThreadAccessFactory(
        mailbox=mailbox, thread=thread, role=enums.ThreadAccessRoleChoices.EDITOR
    )
    msg1 = MessageFactory(thread=thread, is_trashed=False)
    msg2 = MessageFactory(thread=thread, is_trashed=True)  # Already trashed

    thread.refresh_from_db()
    thread.update_stats()
    assert thread.has_trashed is True

    message_ids = [str(msg1.id)]
    data = {"flag": "trashed", "value": True, "message_ids": message_ids}
    response = api_client.post(API_URL, data=data, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["updated_threads"] == 1

    msg1.refresh_from_db()
    msg2.refresh_from_db()
    assert msg1.is_trashed is True
    assert msg1.trashed_at is not None
    assert msg2.is_trashed is True

    thread.refresh_from_db()
    assert thread.has_trashed is True


def test_api_flag_mark_messages_untrashed_success(api_client):
    """Test marking messages as untrashed successfully."""
    user = UserFactory()
    api_client.force_authenticate(user=user)
    mailbox = MailboxFactory(users_read=[user])
    thread = ThreadFactory()
    ThreadAccessFactory(
        mailbox=mailbox, thread=thread, role=enums.ThreadAccessRoleChoices.EDITOR
    )
    msg1 = MessageFactory(thread=thread, is_trashed=True, trashed_at=timezone.now())
    msg2 = MessageFactory(thread=thread, is_trashed=False)  # Already untrashed

    thread.refresh_from_db()
    thread.update_stats()
    assert thread.has_trashed is True

    message_ids = [str(msg1.id)]
    data = {"flag": "trashed", "value": False, "message_ids": message_ids}
    response = api_client.post(API_URL, data=data, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["updated_threads"] == 1

    msg1.refresh_from_db()
    msg2.refresh_from_db()
    assert msg1.is_trashed is False
    assert msg1.trashed_at is None
    assert msg2.is_trashed is False

    thread.refresh_from_db()
    assert thread.has_trashed is False


# --- Tests for Archived Flag ---


def test_api_flag_mark_messages_archived_success(api_client):
    """Test marking messages as archived successfully."""
    user = UserFactory()
    api_client.force_authenticate(user=user)
    mailbox = MailboxFactory(users_read=[user])  # Ensure correct permission if needed
    thread = ThreadFactory()
    ThreadAccessFactory(
        mailbox=mailbox, thread=thread, role=enums.ThreadAccessRoleChoices.EDITOR
    )
    msg1 = MessageFactory(thread=thread, is_archived=False)
    msg2 = MessageFactory(thread=thread, is_archived=True)  # Already archived

    thread.refresh_from_db()
    thread.update_stats()
    assert thread.has_archived is True

    message_ids = [str(msg1.id)]
    data = {"flag": "archived", "value": True, "message_ids": message_ids}
    response = api_client.post(API_URL, data=data, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["updated_threads"] == 1

    msg1.refresh_from_db()
    msg2.refresh_from_db()
    assert msg1.is_archived is True
    assert msg1.archived_at is not None
    assert msg2.is_archived is True

    thread.refresh_from_db()
    assert thread.has_archived is True


def test_api_flag_mark_messages_unarchived_success(api_client):
    """Test marking messages as unarchived successfully."""
    user = UserFactory()
    api_client.force_authenticate(user=user)
    mailbox = MailboxFactory(users_read=[user])
    thread = ThreadFactory()
    ThreadAccessFactory(
        mailbox=mailbox, thread=thread, role=enums.ThreadAccessRoleChoices.EDITOR
    )
    msg1 = MessageFactory(thread=thread, is_archived=True, archived_at=timezone.now())
    msg2 = MessageFactory(thread=thread, is_archived=False)  # Already unarchived

    thread.refresh_from_db()
    thread.update_stats()
    assert thread.has_archived is True

    message_ids = [str(msg1.id)]
    data = {"flag": "archived", "value": False, "message_ids": message_ids}
    response = api_client.post(API_URL, data=data, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["updated_threads"] == 1

    msg1.refresh_from_db()
    msg2.refresh_from_db()
    assert msg1.is_archived is False
    assert msg1.archived_at is None
    assert msg2.is_archived is False

    thread.refresh_from_db()
    assert thread.has_archived is False
