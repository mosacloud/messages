"""
Core application enums declaration
"""

from django.conf import global_settings
from django.db import models
from django.utils.translation import gettext_lazy as _

# In Django's code base, `LANGUAGES` is set by default with all supported languages.
# We can use it for the choice of languages which should not be limited to the few languages
# active in the app.
# pylint: disable=no-member
ALL_LANGUAGES = {language: _(name) for language, name in global_settings.LANGUAGES}


class MailboxRoleChoices(models.TextChoices):
    """Defines the unique roles a user can have to access a mailbox."""

    VIEWER = "viewer", _("Viewer")
    EDITOR = "editor", _("Editor")
    ADMIN = "admin", _("Admin")


class ThreadAccessRoleChoices(models.TextChoices):
    """Defines the possible roles a mailbox can have to access to a thread."""

    VIEWER = "viewer", _("Viewer")
    EDITOR = "editor", _("Editor")


class MessageRecipientTypeChoices(models.TextChoices):
    """Defines the possible types of message recipients."""

    TO = "to", _("To")
    CC = "cc", _("Cc")
    BCC = "bcc", _("Bcc")


class MessageDeliveryStatusChoices(models.TextChoices):
    """Defines the possible statuses of a message delivery."""

    INTERNAL = "internal", _("Internal")
    SENT = "sent", _("Sent")
    FAILED = "failed", _("Failed")
    RETRY = "retry", _("Retry")


class MailDomainAccessRoleChoices(models.TextChoices):
    """Defines the unique roles a user can have to access a mail domain."""

    ADMIN = "ADMIN", _("Admin")


THREAD_STATS_FIELDS_MAP = {
    "all": "all",
    "all_unread": "all_unread",
}
