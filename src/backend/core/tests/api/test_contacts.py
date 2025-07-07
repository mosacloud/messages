"""Test the ContactViewSet."""

from django.urls import reverse

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from core import factories, models


@pytest.mark.django_db
class TestContactViewSet:
    """Test the ContactViewSet."""

    def test_list_contacts(self):
        """Test listing all contacts for user's mailboxes."""
        # Create authenticated user with access to 2 mailboxes
        authenticated_user = factories.UserFactory()
        user_mailbox1 = factories.MailboxFactory()
        user_mailbox2 = factories.MailboxFactory()
        other_mailbox = factories.MailboxFactory()

        # Authenticated user has access to 2 mailboxes
        factories.MailboxAccessFactory(
            mailbox=user_mailbox1,
            user=authenticated_user,
            role=models.MailboxRoleChoices.VIEWER,
        )
        factories.MailboxAccessFactory(
            mailbox=user_mailbox2,
            user=authenticated_user,
            role=models.MailboxRoleChoices.EDITOR,
        )

        # Create contacts for user's mailboxes
        contact1 = factories.ContactFactory(
            mailbox=user_mailbox1, name="John Doe", email="john@example.com"
        )
        contact2 = factories.ContactFactory(
            mailbox=user_mailbox2, name="Jane Smith", email="jane@example.com"
        )
        contact3 = factories.ContactFactory(
            mailbox=user_mailbox2, name="Bob Wilson", email="bob@example.com"
        )

        # Create contact for other mailbox (should not appear in results)
        factories.ContactFactory(
            mailbox=other_mailbox, name="Other User", email="other@example.com"
        )

        # Authenticate user
        client = APIClient()
        client.force_authenticate(user=authenticated_user)

        # Get list of contacts
        response = client.get(reverse("contacts-list"))
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 3

        # Check response data (ordered by name, then email)
        expected_contacts = [
            {
                "id": str(contact3.id),
                "name": "Bob Wilson",
                "email": "bob@example.com",
            },
            {
                "id": str(contact2.id),
                "name": "Jane Smith",
                "email": "jane@example.com",
            },
            {
                "id": str(contact1.id),
                "name": "John Doe",
                "email": "john@example.com",
            },
        ]
        assert response.data == expected_contacts

    def test_list_contacts_unauthorized(self):
        """Anonymous user cannot access the list of contacts."""
        client = APIClient()
        response = client.get(reverse("contacts-list"))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_list_contacts_filter_by_mailbox(self):
        """Test filtering contacts by mailbox ID."""
        # Create authenticated user with access to 2 mailboxes
        authenticated_user = factories.UserFactory()
        user_mailbox1 = factories.MailboxFactory()
        user_mailbox2 = factories.MailboxFactory()

        # Authenticated user has access to both mailboxes
        factories.MailboxAccessFactory(
            mailbox=user_mailbox1,
            user=authenticated_user,
            role=models.MailboxRoleChoices.VIEWER,
        )
        factories.MailboxAccessFactory(
            mailbox=user_mailbox2,
            user=authenticated_user,
            role=models.MailboxRoleChoices.EDITOR,
        )

        # Create contacts for each mailbox
        contact1 = factories.ContactFactory(
            mailbox=user_mailbox1, name="John Doe", email="john@example.com"
        )
        contact2 = factories.ContactFactory(
            mailbox=user_mailbox2, name="Jane Smith", email="jane@example.com"
        )

        # Authenticate user
        client = APIClient()
        client.force_authenticate(user=authenticated_user)

        # Filter by first mailbox
        response = client.get(
            reverse("contacts-list"), {"mailbox_id": str(user_mailbox1.id)}
        )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["id"] == str(contact1.id)

        # Filter by second mailbox
        response = client.get(
            reverse("contacts-list"), {"mailbox_id": str(user_mailbox2.id)}
        )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["id"] == str(contact2.id)

    def test_list_contacts_search_by_name(self):
        """Test searching contacts by name (multi-words)."""
        authenticated_user = factories.UserFactory()
        mailbox = factories.MailboxFactory()
        factories.MailboxAccessFactory(
            mailbox=mailbox,
            user=authenticated_user,
            role=models.MailboxRoleChoices.EDITOR,
        )
        contact1 = factories.ContactFactory(
            mailbox=mailbox, name="John Doe", email="john@example.com"
        )
        contact2 = factories.ContactFactory(
            mailbox=mailbox, name="Jane Doe", email="jane@example.com"
        )
        factories.ContactFactory(
            mailbox=mailbox, name="Bob Smith", email="bob@example.com"
        )
        client = APIClient()
        client.force_authenticate(user=authenticated_user)
        # One word : "Doe" => both Doe
        response = client.get(reverse("contacts-list"), {"q": "Doe"})
        assert response.status_code == 200
        assert {c["id"] for c in response.data} == {str(contact1.id), str(contact2.id)}
        # Two words : "Jane Doe" => only Jane Doe
        response = client.get(reverse("contacts-list"), {"q": "Jane Doe"})
        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["id"] == str(contact2.id)
        # Two words : "Doe John" => only John Doe
        response = client.get(reverse("contacts-list"), {"q": "Doe John"})
        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["id"] == str(contact1.id)

    def test_list_contacts_search_by_email(self):
        """Test searching contacts by email (multi-words)."""
        authenticated_user = factories.UserFactory()
        mailbox = factories.MailboxFactory()
        factories.MailboxAccessFactory(
            mailbox=mailbox,
            user=authenticated_user,
            role=models.MailboxRoleChoices.EDITOR,
        )
        contact1 = factories.ContactFactory(
            mailbox=mailbox, name="John Doe", email="john.doe@example.com"
        )
        contact2 = factories.ContactFactory(
            mailbox=mailbox, name="Jane Smith", email="jane.smith@example.com"
        )
        factories.ContactFactory(
            mailbox=mailbox, name="Bob Wilson", email="bob.wilson@test.com"
        )
        client = APIClient()
        client.force_authenticate(user=authenticated_user)
        # One word : "example.com" => both Doe
        response = client.get(reverse("contacts-list"), {"q": "example.com"})
        assert response.status_code == 200
        assert {c["id"] for c in response.data} == {str(contact1.id), str(contact2.id)}
        # Two words : "jane example.com" => only Jane Smith
        response = client.get(reverse("contacts-list"), {"q": "jane example.com"})
        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["id"] == str(contact2.id)
        # Two words : "john example.com" => only John Doe
        response = client.get(reverse("contacts-list"), {"q": "john example.com"})
        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["id"] == str(contact1.id)

    def test_list_contacts_search_combined(self):
        """Test searching contacts with both mailbox filter and multi-words search query."""
        authenticated_user = factories.UserFactory()
        mailbox1 = factories.MailboxFactory()
        mailbox2 = factories.MailboxFactory()
        factories.MailboxAccessFactory(
            mailbox=mailbox1,
            user=authenticated_user,
            role=models.MailboxRoleChoices.EDITOR,
        )
        factories.MailboxAccessFactory(
            mailbox=mailbox2,
            user=authenticated_user,
            role=models.MailboxRoleChoices.EDITOR,
        )
        contact1 = factories.ContactFactory(
            mailbox=mailbox1, name="John Doe", email="john@example.com"
        )
        contact2 = factories.ContactFactory(
            mailbox=mailbox2, name="John Smith", email="john@test.com"
        )
        client = APIClient()
        client.force_authenticate(user=authenticated_user)
        # One word : "John" in mailbox1 => John Doe
        response = client.get(
            reverse("contacts-list"), {"mailbox_id": str(mailbox1.id), "q": "John"}
        )
        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["id"] == str(contact1.id)
        # Two words : "John Doe" in mailbox1 => John Doe
        response = client.get(
            reverse("contacts-list"), {"mailbox_id": str(mailbox1.id), "q": "John Doe"}
        )
        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["id"] == str(contact1.id)
        # Two words : "John test.com" in mailbox2 => John Smith
        response = client.get(
            reverse("contacts-list"),
            {"mailbox_id": str(mailbox2.id), "q": "John test.com"},
        )
        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["id"] == str(contact2.id)

    def test_list_contacts_search_multiword(self):
        """Test searching contacts with three words (first name, last name, email domain)."""
        authenticated_user = factories.UserFactory()
        mailbox = factories.MailboxFactory()
        factories.MailboxAccessFactory(
            mailbox=mailbox,
            user=authenticated_user,
            role=models.MailboxRoleChoices.EDITOR,
        )
        contact1 = factories.ContactFactory(
            mailbox=mailbox, name="John Doe", email="john.doe@example.com"
        )
        factories.ContactFactory(
            mailbox=mailbox, name="Jane Doe", email="jane.doe@example.com"
        )
        client = APIClient()
        client.force_authenticate(user=authenticated_user)
        # Three words : "John Doe example.com" => only John Doe
        response = client.get(reverse("contacts-list"), {"q": "John Doe example.com"})
        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["id"] == str(contact1.id)

    def test_list_contacts_no_results(self):
        """Test when no contacts match the search criteria."""
        # Create authenticated user with access to a mailbox
        authenticated_user = factories.UserFactory()
        mailbox = factories.MailboxFactory()
        factories.MailboxAccessFactory(
            mailbox=mailbox,
            user=authenticated_user,
            role=models.MailboxRoleChoices.EDITOR,
        )

        # Create a contact
        factories.ContactFactory(
            mailbox=mailbox, name="John Doe", email="john@example.com"
        )

        # Authenticate user
        client = APIClient()
        client.force_authenticate(user=authenticated_user)

        # Search for non-existent contact
        response = client.get(reverse("contacts-list"), {"q": "nonexistent"})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 0

    def test_retrieve_contact(self):
        """Test retrieving a specific contact."""
        # Create authenticated user with access to a mailbox
        authenticated_user = factories.UserFactory()
        mailbox = factories.MailboxFactory()
        factories.MailboxAccessFactory(
            mailbox=mailbox,
            user=authenticated_user,
            role=models.MailboxRoleChoices.EDITOR,
        )

        # Create a contact
        contact = factories.ContactFactory(
            mailbox=mailbox, name="John Doe", email="john@example.com"
        )

        # Authenticate user
        client = APIClient()
        client.force_authenticate(user=authenticated_user)

        # Retrieve the contact
        response = client.get(
            reverse("contacts-detail", kwargs={"pk": str(contact.id)})
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {
            "id": str(contact.id),
            "name": "John Doe",
            "email": "john@example.com",
        }

    def test_retrieve_contact_unauthorized(self):
        """Anonymous user cannot retrieve a contact."""
        contact = factories.ContactFactory()
        client = APIClient()
        response = client.get(
            reverse("contacts-detail", kwargs={"pk": str(contact.id)})
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_retrieve_contact_no_access(self):
        """User without access to the mailbox cannot retrieve the contact."""
        # Create user without access to the mailbox
        user = factories.UserFactory()
        contact = factories.ContactFactory()

        # Authenticate user
        client = APIClient()
        client.force_authenticate(user=user)

        # Try to retrieve the contact
        response = client.get(
            reverse("contacts-detail", kwargs={"pk": str(contact.id)})
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
