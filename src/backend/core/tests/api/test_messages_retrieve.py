"""Test retrieving a message."""
# pylint: disable=redefined-outer-name

from django.urls import reverse

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from core import factories, models

pytestmark = pytest.mark.django_db


@pytest.fixture
def message_url(message):
    """Get the url for a message."""
    return reverse("messages-detail", kwargs={"id": message.id})


@pytest.fixture
def message_url_eml(message):
    """Get the url for a message."""
    return reverse("messages-eml", kwargs={"id": message.id})


class TestRetrieveMessage:
    """Test retrieving a message."""

    def test_retrieve_message(self, message, message_url, mailbox_access):
        """Test retrieving a message."""
        client = APIClient()
        client.force_authenticate(user=mailbox_access.user)
        response = client.get(message_url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == str(message.id)

    def test_retrieve_message_delegated_to_other_mailbox(
        self, message, message_url, other_user
    ):
        """Test retrieving a message."""
        client = APIClient()
        client.force_authenticate(user=other_user)
        # create a mailbox access for the other user
        other_mailbox = factories.MailboxFactory()
        factories.MailboxAccessFactory(
            mailbox=other_mailbox,
            user=other_user,
            role=models.MailboxRoleChoices.VIEWER,
        )
        # create a thread access for the other user
        factories.ThreadAccessFactory(
            thread=message.thread,
            mailbox=other_mailbox,
            role=models.ThreadAccessRoleChoices.VIEWER,
        )
        response = client.get(message_url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == str(message.id)

    def test_retrieve_message_unauthorized(self, message_url, other_user):
        """Test retrieving a message."""
        client = APIClient()
        client.force_authenticate(user=other_user)
        response = client.get(message_url)
        # we should get a 404 because the message is not accessible by the other user
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_retrieve_message_sender_user_null(
        self, message, message_url, mailbox_access
    ):
        """A message without a sender_user should return null for the field."""
        assert message.sender_user is None

        client = APIClient()
        client.force_authenticate(user=mailbox_access.user)
        response = client.get(message_url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["sender_user"] is None

    def test_retrieve_message_sender_user(self, message, message_url, mailbox_access):
        """A message with a sender_user should return the user's id, full_name and email."""
        sender_user = factories.UserFactory(
            full_name="Alice Martin", email="alice@example.com"
        )
        message.sender_user = sender_user
        message.save()

        client = APIClient()
        client.force_authenticate(user=mailbox_access.user)
        response = client.get(message_url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["sender_user"] == {
            "id": str(sender_user.id),
            "full_name": sender_user.full_name,
            "email": sender_user.email,
        }

    def test_retrieve_message_eml(self, message_url_eml, message, mailbox_access):
        """Test retrieving a message EML."""
        client = APIClient()
        client.force_authenticate(user=mailbox_access.user)
        response = client.get(message_url_eml)
        assert response.status_code == status.HTTP_200_OK
        assert response.content == message.blob.get_content()
