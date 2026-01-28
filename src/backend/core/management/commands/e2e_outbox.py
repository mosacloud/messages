"""
Django management command to create outbox test data for E2E testing.

This command creates a message with failed delivery recipients to test
the outbox functionality.
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core import models
from core.enums import (
    MessageDeliveryStatusChoices,
    ThreadAccessRoleChoices,
)

DOMAIN_NAME = "example.local"


class Command(BaseCommand):
    """Create outbox test data for E2E testing."""

    help = "Create outbox test data (message with failed delivery)"

    def add_arguments(self, parser):
        """Add command arguments."""
        parser.add_argument(
            "--browser",
            type=str,
            default="chromium",
            help="Browser name for the test user (chromium, firefox, webkit)",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        """Execute the command."""
        if not settings.ENVIRONMENT == "e2e":
            self.stdout.write(self.style.WARNING("Not in E2E environment"))
            return

        browser = options["browser"]
        self.stdout.write(
            self.style.WARNING(f"\n\n|  Creating Outbox Test Data for {browser}\n")
        )

        # Get the domain
        try:
            domain = models.MailDomain.objects.get(name=DOMAIN_NAME)
        except models.MailDomain.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f"Domain {DOMAIN_NAME} not found. Run e2e_demo first.")
            )
            return

        # Get the user and mailbox
        user_email = f"user.e2e.{browser}@{DOMAIN_NAME}"
        try:
            mailbox = models.Mailbox.objects.get(
                local_part=f"user.e2e.{browser}", domain=domain
            )
        except (models.User.DoesNotExist, models.Mailbox.DoesNotExist):
            self.stdout.write(
                self.style.ERROR(f"User or mailbox not found: {user_email}")
            )
            return

        # Create the sender contact
        sender_contact, _ = models.Contact.objects.get_or_create(
            email=str(mailbox),
            mailbox=mailbox,
            defaults={"name": f"User E2E {browser}"},
        )

        # Create a thread for the failed message
        thread = models.Thread.objects.create(
            subject="Test message with delivery failure",
        )
        self.stdout.write(self.style.SUCCESS(f"  ✓ Created thread: {thread.id}"))

        # Create thread access
        models.ThreadAccess.objects.create(
            thread=thread,
            mailbox=mailbox,
            role=ThreadAccessRoleChoices.EDITOR,
        )

        # Create the message
        message = models.Message.objects.create(
            thread=thread,
            sender=sender_contact,
            subject="Test message with delivery failure",
            is_sender=True,
            is_draft=False,
            is_unread=False,
            sent_at=timezone.now(),
        )
        self.stdout.write(self.style.SUCCESS(f"  ✓ Created message: {message.id}"))

        # Create recipient contacts and message recipients with different statuses
        # 1. Failed recipient
        failed_contact, _ = models.Contact.objects.get_or_create(
            email="failed@external.invalid",
            mailbox=mailbox,
            defaults={"name": "Failed Recipient"},
        )
        models.MessageRecipient.objects.create(
            message=message,
            contact=failed_contact,
            delivery_status=MessageDeliveryStatusChoices.FAILED,
            delivery_message="Recipient address rejected: Domain not found",
        )
        self.stdout.write(
            self.style.SUCCESS("  ✓ Created FAILED recipient: failed@external.invalid")
        )

        # 2. Retry recipient
        retry_contact, _ = models.Contact.objects.get_or_create(
            email="retry@external.invalid",
            mailbox=mailbox,
            defaults={"name": "Retry Recipient"},
        )
        models.MessageRecipient.objects.create(
            message=message,
            contact=retry_contact,
            delivery_status=MessageDeliveryStatusChoices.RETRY,
            delivery_message="Temporary failure, will retry",
            retry_at=timezone.now() + timezone.timedelta(hours=1),
        )
        self.stdout.write(
            self.style.SUCCESS("  ✓ Created RETRY recipient: retry@external.invalid")
        )

        # 3. Sent recipient (success)
        sent_contact, _ = models.Contact.objects.get_or_create(
            email="sent@external.invalid",
            mailbox=mailbox,
            defaults={"name": "Sent Recipient"},
        )
        models.MessageRecipient.objects.create(
            message=message,
            contact=sent_contact,
            delivery_status=MessageDeliveryStatusChoices.SENT,
            delivered_at=timezone.now(),
        )
        self.stdout.write(
            self.style.SUCCESS("  ✓ Created SENT recipient: sent@external.invalid")
        )

        # Update thread stats
        thread.update_stats()
        self.stdout.write(
            self.style.SUCCESS(
                f"  ✓ Thread stats updated: has_delivery_pending={thread.has_delivery_pending}, "
                f"has_delivery_failed={thread.has_delivery_failed}"
            )
        )

        self.stdout.write(
            self.style.SUCCESS("\n✓ Outbox test data created successfully!\n")
        )
