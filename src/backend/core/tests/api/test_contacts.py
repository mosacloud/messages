"""Test the ContactViewSet."""

from django.urls import reverse

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from core import factories, models


@pytest.mark.django_db
class TestContactViewSet:
    """Test the ContactViewSet."""

    def test_list_contacts_unauthorized(self):
        """Anonymous user cannot access the list of contacts."""
        client = APIClient()
        response = client.get(reverse("contacts-list"))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_list_contacts_no_access(self):
        """User without access to the mailbox cannot access the list of contacts."""
        user = factories.UserFactory()
        mailbox = factories.MailboxFactory()
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("contacts-list"), {"mailbox_id": str(mailbox.id)})
        assert response.status_code == status.HTTP_403_FORBIDDEN

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

    def test_list_contacts_filter_by_mailbox_includes_domain_contacts(
        self, django_assert_num_queries
    ):
        """Test filtering contacts by mailbox ID also includes contacts from other mailboxes in the same domain."""
        # create a domain for authenticated user
        brigny_domain = factories.MailDomainFactory(name="brigny.fr")

        # Create authenticated user with access to mailboxes
        dominique = factories.UserFactory()

        # Authenticate user
        client = APIClient()
        client.force_authenticate(user=dominique)

        # create a mailbox for authenticated user
        dominique_mailbox = factories.MailboxFactory(
            local_part="dominique.durand", domain=brigny_domain
        )
        factories.MailboxAccessFactory(
            mailbox=dominique_mailbox,
            user=dominique,
            role=models.MailboxRoleChoices.ADMIN,
        )
        dominique_contact = factories.ContactFactory(
            name="Dominique Durand", email="dominique.durand@brigny.fr"
        )
        dominique_mailbox.contact = dominique_contact
        dominique_mailbox.save()

        # Create 2 other mailboxes in the same domain
        alain_mailbox = factories.MailboxFactory(
            local_part="alain.verse", domain=brigny_domain
        )
        alain_contact = factories.ContactFactory(
            name="Alain Verse", email="alain@brigny.fr"
        )
        alain_mailbox.contact = alain_contact
        alain_mailbox.save()
        factories.ContactFactory.create_batch(
            3, mailbox=alain_mailbox
        )  # alain has 3 contacts in his mailbox

        michel_mailbox = factories.MailboxFactory(
            local_part="michel.chatel", domain=brigny_domain
        )
        michel_contact = factories.ContactFactory(
            name="Michel Chatel", email="michel@brigny.fr"
        )
        michel_mailbox.contact = michel_contact
        michel_mailbox.save()
        factories.ContactFactory.create_batch(
            3, mailbox=michel_mailbox
        )  # michel has 3 contacts in his mailbox

        sam_mailbox = factories.MailboxFactory(
            local_part="sam.suffit", domain=brigny_domain
        )
        sam_contact = factories.ContactFactory(name="Sam Suffit", email="sam@brigny.fr")
        sam_mailbox.contact = sam_contact
        sam_mailbox.save()
        factories.ContactFactory.create_batch(
            3, mailbox=sam_mailbox
        )  # sam has 3 contacts in his mailbox
        sam_contact_of_dominique = factories.ContactFactory(
            name="Sam Suffit :)", email="sam@brigny.fr"
        )
        # Sam is Dominique contact too
        dominique_mailbox.contacts.add(sam_contact_of_dominique)

        # Dominique has some external contacts (other domains)
        cecile_contact = factories.ContactFactory(
            name="Cecile Troyen", email="cecile@otherdomain1.com"
        )
        dominique_mailbox.contacts.add(cecile_contact)
        jean_contact = factories.ContactFactory(
            name="Jean Bon", email="jean@otherdomain2.com"
        )
        dominique_mailbox.contacts.add(jean_contact)

        # create random contacts
        factories.ContactFactory.create_batch(10)

        # Filter by first mailbox - should return all mailboxes contacts and contacts
        # from same domain as user authenticated
        # search by name
        with django_assert_num_queries(2):
            response = client.get(
                reverse("contacts-list"), {"mailbox_id": str(dominique_mailbox.id)}
            )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 6  # 4 internal contacts + 2 external contacts
        contact_ids = {c["id"] for c in response.data}
        assert contact_ids == {
            str(dominique_contact.id),
            str(alain_contact.id),
            str(michel_contact.id),
            str(cecile_contact.id),
            str(jean_contact.id),
            str(sam_contact_of_dominique.id),
        }

        # search by name
        response = client.get(reverse("contacts-list"), {"q": "Verse"})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 0

        with django_assert_num_queries(2):
            response = client.get(
                reverse("contacts-list"),
                {"mailbox_id": str(dominique_mailbox.id), "q": "Troyen"},
            )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        contact_ids = {c["id"] for c in response.data}
        assert contact_ids == {str(cecile_contact.id)}

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
