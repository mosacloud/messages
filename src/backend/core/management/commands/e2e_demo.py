"""
Django management command to bootstrap E2E demo data.

This command creates demo users, mailboxes, and shared mailboxes for E2E testing
across different BROWSERS (chromium, firefox, webkit).
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from core import models
from core.enums import MailboxRoleChoices, MailDomainAccessRoleChoices
from core.services.identity.keycloak import get_keycloak_admin_client

BROWSERS = ["chromium", "firefox", "webkit"]
DOMAIN_NAME = "example.local"
SHARED_MAILBOX_LOCAL_PART = "shared.e2e"


class Command(BaseCommand):
    """Create data for E2E demo data for testing."""

    help = "Create data for E2E demo (users and mailboxes)"

    @transaction.atomic
    def handle(self, *args, **options):
        """Execute the command."""
        if not settings.ENVIRONMENT == "e2e":
            self.stdout.write(self.style.WARNING("Not in E2E environment"))
            return

        self.stdout.write(self.style.WARNING("\n\n|  Creating E2E Demo Data\n"))

        # Step 1: Get or create the domain
        self.stdout.write(f"\n-- 1/4 📦 Setting up domain: {DOMAIN_NAME}")
        domain, domain_created = models.MailDomain.objects.get_or_create(
            name=DOMAIN_NAME,
            defaults={
                "oidc_autojoin": True,
                "identity_sync": True,
            },
        )
        if domain_created:
            self.stdout.write(self.style.SUCCESS(f"  ✓ Created domain: {DOMAIN_NAME}"))
        else:
            self.stdout.write(
                self.style.SUCCESS(f"  ✓ Domain already exists: {DOMAIN_NAME}")
            )

        # Step 2: Create users per browser
        self.stdout.write(
            f"\n-- 2/4 👥 Creating users for BROWSERS: {', '.join(BROWSERS)}"
        )

        regular_users = []
        mailbox_admin_users = []

        for browser in BROWSERS:
            self.stdout.write(f"\n----  Browser: {browser}")

            # Create superuser
            superuser_email = f"super_admin.e2e.{browser}@{DOMAIN_NAME}"
            self._create_user_with_mailbox(superuser_email, domain, is_superuser=True)

            # Create domain admin user and mailbox
            domain_admin_email = f"domain_admin.e2e.{browser}@{DOMAIN_NAME}"
            domain_admin_user, domain_admin_mailbox = self._create_user_with_mailbox(
                domain_admin_email, domain, is_domain_admin=True
            )

            # Create regular user and mailbox
            regular_email = f"user.e2e.{browser}@{DOMAIN_NAME}"
            regular_user, regular_mailbox = self._create_user_with_mailbox(
                regular_email, domain
            )
            regular_users.append((regular_user, regular_mailbox))

            # Create mailbox admin user and mailbox
            mailbox_admin_email = f"mailbox_admin.e2e.{browser}@{DOMAIN_NAME}"
            mailbox_admin_user, mailbox_admin_mailbox = self._create_user_with_mailbox(
                mailbox_admin_email, domain
            )
            mailbox_admin_users.append((mailbox_admin_user, mailbox_admin_mailbox))
            self.stdout.write(
                self.style.SUCCESS(f"    ✓ Mailbox admin: {mailbox_admin_email}")
            )

        # Step 3: Create shared mailbox
        self.stdout.write(
            f"\n-- 3/4 📥 Creating shared mailbox: {SHARED_MAILBOX_LOCAL_PART}@{DOMAIN_NAME}"
        )
        shared_mailbox = self._create_shared_mailbox(SHARED_MAILBOX_LOCAL_PART, domain)
        self.stdout.write(
            self.style.SUCCESS(
                f"  ✓ Shared mailbox created: {SHARED_MAILBOX_LOCAL_PART}@{DOMAIN_NAME}"
            )
        )

        # Step 4: Add all regular users with sender role to the shared mailbox
        self.stdout.write(
            "\n-- 4/4 🔐 Adding users to shared mailbox with appropriate roles"
        )
        for user, _ in regular_users:
            self._add_mailbox_access(shared_mailbox, user, MailboxRoleChoices.SENDER)
            self.stdout.write(
                self.style.SUCCESS(
                    f"  ✓ Added {user.email} as SENDER to shared mailbox"
                )
            )

        # Step 5: Add mailbox admin users with admin role to the shared mailbox
        for user, _ in mailbox_admin_users:
            self._add_mailbox_access(shared_mailbox, user, MailboxRoleChoices.ADMIN)
            self.stdout.write(
                self.style.SUCCESS(f"  ✓ Added {user.email} as ADMIN to shared mailbox")
            )

    def _create_user_with_mailbox(
        self, email, domain, is_domain_admin=False, is_superuser=False
    ):
        """Create a user with a personal mailbox."""
        local_part = email.split("@")[0]
        full_name = local_part.replace(".", " ").replace("-", " ").title()

        # Create or get user
        user, user_created = models.User.objects.get_or_create(
            email=email,
            defaults={
                "is_superuser": is_superuser,
                "full_name": full_name,
                "password": "!",
            },
        )

        keycloak_admin = get_keycloak_admin_client()
        user_id = None

        # Create or get mailbox
        mailbox, mailbox_created = models.Mailbox.objects.get_or_create(
            local_part=local_part,
            domain=domain,
            defaults={
                "is_identity": True,
            },
        )

        # Create or get contact
        contact, _ = models.Contact.objects.get_or_create(
            email=email,
            mailbox=mailbox,
            defaults={"name": full_name},
        )
        if not mailbox.contact:
            mailbox.contact = contact
            mailbox.save()

        # Give the user admin access to their own mailbox
        models.MailboxAccess.objects.get_or_create(
            mailbox=mailbox,
            user=user,
            defaults={"role": MailboxRoleChoices.ADMIN},
        )

        # If this is a domain admin, grant domain access
        if is_domain_admin:
            models.MailDomainAccess.objects.get_or_create(
                maildomain=domain,
                user=user,
                defaults={"role": MailDomainAccessRoleChoices.ADMIN},
            )

        # Set password for user in OIDC
        users = get_keycloak_admin_client().get_users({"email": str(mailbox)})
        if len(users) > 0:
            user_id = users[0].get("id")
            keycloak_admin.set_user_password(
                user_id=user_id,
                password="e2e",  # noqa: S106
                temporary=False,
            )
            self.stdout.write(
                self.style.SUCCESS(f"✓ Password set for user {user.email} in Keycloak.")
            )
        else:
            self.stdout.write(
                self.style.WARNING(f"✗ User {user.email} not found in Keycloak.")
            )

        return user, mailbox

    def _create_shared_mailbox(self, local_part, domain):
        """Create a shared mailbox."""
        email = f"{local_part}@{domain.name}"
        mailbox_name = local_part.replace("-", " ").title()

        # Create or get mailbox
        mailbox, mailbox_created = models.Mailbox.objects.get_or_create(
            local_part=local_part,
            domain=domain,
            defaults={
                "is_identity": False,  # Shared mailbox
            },
        )

        # Create or get contact for the shared mailbox
        contact, _ = models.Contact.objects.get_or_create(
            email=email,
            mailbox=mailbox,
            defaults={"name": mailbox_name},
        )
        if not mailbox.contact:
            mailbox.contact = contact
            mailbox.save()

        return mailbox

    def _add_mailbox_access(self, mailbox, user, role):
        """Add or update mailbox access for a user."""
        access, created = models.MailboxAccess.objects.get_or_create(
            mailbox=mailbox,
            user=user,
            defaults={"role": role},
        )
        if not created and access.role != role:
            access.role = role
            access.save()
        return access
