"""Tests for label functionality in thread responses."""
# pylint: disable=redefined-outer-name, unused-argument

from django.urls import reverse

import pytest
from rest_framework import status

from core import enums, factories

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    """Create a test user."""
    return factories.UserFactory()


@pytest.fixture
def mailbox(user):
    """Create a mailbox with user access."""
    mailbox = factories.MailboxFactory()
    factories.MailboxAccessFactory(
        mailbox=mailbox,
        user=user,
        role=enums.MailboxRoleChoices.EDITOR,
    )
    return mailbox


@pytest.fixture
def thread(mailbox):
    """Create a thread with mailbox access and a message."""
    thread = factories.ThreadFactory()
    factories.ThreadAccessFactory(
        mailbox=mailbox,
        thread=thread,
        role=enums.ThreadAccessRoleChoices.EDITOR,
    )
    # Add a message to the thread
    factories.MessageFactory(thread=thread)
    thread.update_stats()
    return thread


@pytest.fixture
def label(mailbox):
    """Create a label in the mailbox."""
    return factories.LabelFactory(mailbox=mailbox)


def test_thread_includes_labels(api_client, user, thread, label, mailbox):
    """Test that thread responses include labels scoped to the requested mailbox."""
    # Add 2 labels to the thread
    thread.labels.add(label)
    thread.labels.add(factories.LabelFactory(mailbox=mailbox))

    api_client.force_authenticate(user=user)
    response = api_client.get(reverse("threads-list"), {"mailbox_id": str(mailbox.id)})

    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] == 1
    thread_data = response.data["results"][0]
    assert "labels" in thread_data
    assert len(thread_data["labels"]) == 2
    label_data = thread_data["labels"][0]
    assert label_data["id"] == str(label.id)
    assert label_data["name"] == label.name
    assert label_data["slug"] == label.slug
    assert label_data["color"] == label.color


def test_thread_labels_scoped_to_mailbox(api_client, user, thread, mailbox):
    """Test that thread labels are scoped to the requested mailbox only."""
    # Create a label in the user's mailbox
    own_label = factories.LabelFactory(mailbox=mailbox)

    # Create another mailbox with access for the same user
    other_mailbox = factories.MailboxFactory()
    factories.MailboxAccessFactory(
        mailbox=other_mailbox,
        user=user,
        role=enums.MailboxRoleChoices.EDITOR,
    )
    factories.ThreadAccessFactory(
        mailbox=other_mailbox,
        thread=thread,
        role=enums.ThreadAccessRoleChoices.EDITOR,
    )
    other_label = factories.LabelFactory(mailbox=other_mailbox)

    # Add both labels to the thread
    thread.labels.add(own_label, other_label)

    api_client.force_authenticate(user=user)

    # Request with first mailbox: should only see own_label
    response = api_client.get(reverse("threads-list"), {"mailbox_id": str(mailbox.id)})
    assert response.status_code == status.HTTP_200_OK
    thread_data = response.data["results"][0]
    assert len(thread_data["labels"]) == 1
    assert thread_data["labels"][0]["id"] == str(own_label.id)

    # Request with other mailbox: should only see other_label
    response = api_client.get(
        reverse("threads-list"), {"mailbox_id": str(other_mailbox.id)}
    )
    assert response.status_code == status.HTTP_200_OK
    thread_data = response.data["results"][0]
    assert len(thread_data["labels"]) == 1
    assert thread_data["labels"][0]["id"] == str(other_label.id)


def test_thread_labels_empty_when_no_mailbox_id(api_client, user, thread, label):
    """Test that labels are empty when no mailbox_id is provided."""
    thread.labels.add(label)

    api_client.force_authenticate(user=user)
    response = api_client.get(reverse("threads-list"))

    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] == 1
    thread_data = response.data["results"][0]
    assert "labels" in thread_data
    assert thread_data["labels"] == []


def test_thread_labels_empty_when_no_labels(api_client, user, thread, mailbox):
    """Test that thread responses include an empty labels list when the thread has no labels."""
    api_client.force_authenticate(user=user)
    response = api_client.get(reverse("threads-list"), {"mailbox_id": str(mailbox.id)})

    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] == 1
    thread_data = response.data["results"][0]
    assert "labels" in thread_data
    assert thread_data["labels"] == []


def test_thread_labels_updated_after_label_changes(
    api_client, user, thread, label, mailbox
):
    """Test that thread responses reflect label changes."""
    # Add the label to the thread
    thread.labels.add(label)

    api_client.force_authenticate(user=user)

    # Check initial state
    response = api_client.get(reverse("threads-list"), {"mailbox_id": str(mailbox.id)})
    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] == 1
    thread_data = response.data["results"][0]
    assert len(thread_data["labels"]) == 1

    # Remove the label
    thread.labels.remove(label)

    # Check updated state
    response = api_client.get(reverse("threads-list"), {"mailbox_id": str(mailbox.id)})
    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] == 1
    thread_data = response.data["results"][0]
    assert thread_data["labels"] == []


def test_thread_labels_in_detail_view(api_client, user, thread, label, mailbox):
    """Test that labels are included in thread detail view."""
    # Add the label to the thread
    thread.labels.add(label)

    api_client.force_authenticate(user=user)
    response = api_client.get(
        reverse("threads-detail", args=[thread.id]),
        {"mailbox_id": str(mailbox.id)},
    )

    assert response.status_code == status.HTTP_200_OK
    assert "labels" in response.data
    assert len(response.data["labels"]) == 1
    label_data = response.data["labels"][0]
    assert label_data["id"] == str(label.id)
    assert label_data["name"] == label.name
    assert label_data["slug"] == label.slug
    assert label_data["color"] == label.color
