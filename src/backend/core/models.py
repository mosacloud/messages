"""
Declare and configure the models for the messages core application
"""
# pylint: disable=too-many-lines,too-many-instance-attributes

import base64
import uuid
from logging import getLogger
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.contrib.auth import models as auth_models
from django.contrib.auth.base_user import AbstractBaseUser
from django.core import validators
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from timezone_field import TimeZoneField

from core.enums import (
    MailboxRoleChoices,
    MailDomainAccessRoleChoices,
    MessageDeliveryStatusChoices,
    MessageRecipientTypeChoices,
    ThreadAccessRoleChoices,
)
from core.mda.rfc5322 import parse_email_message

logger = getLogger(__name__)


class DuplicateEmailError(Exception):
    """Raised when an email is already associated with a pre-existing user."""

    def __init__(self, message=None, email=None):
        """Set message and email to describe the exception."""
        self.message = message
        self.email = email
        super().__init__(self.message)


class BaseModel(models.Model):
    """
    Serves as an abstract base model for other models, ensuring that records are validated
    before saving as Django doesn't do it by default.

    Includes fields common to all models: a UUID primary key and creation/update timestamps.
    """

    id = models.UUIDField(
        verbose_name=_("id"),
        help_text=_("primary key for the record as UUID"),
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    created_at = models.DateTimeField(
        verbose_name=_("created on"),
        help_text=_("date and time at which a record was created"),
        auto_now_add=True,
        editable=False,
    )
    updated_at = models.DateTimeField(
        verbose_name=_("updated on"),
        help_text=_("date and time at which a record was last updated"),
        auto_now=True,
        editable=False,
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        """Call `full_clean` before saving."""
        self.full_clean()
        super().save(*args, **kwargs)


class UserManager(auth_models.UserManager):
    """Custom manager for User model with additional methods."""

    def get_user_by_sub_or_email(self, sub, email):
        """Fetch existing user by sub or email."""
        try:
            return self.get(sub=sub)
        except self.model.DoesNotExist as err:
            if not email:
                return None

            if settings.OIDC_FALLBACK_TO_EMAIL_FOR_IDENTIFICATION:
                try:
                    return self.get(email=email)
                except self.model.DoesNotExist:
                    pass
            elif (
                self.filter(email=email).exists()
                and not settings.OIDC_ALLOW_DUPLICATE_EMAILS
            ):
                raise DuplicateEmailError(
                    _(
                        "We couldn't find a user with this sub but the email is already "
                        "associated with a registered user."
                    )
                ) from err
        return None


class User(AbstractBaseUser, BaseModel, auth_models.PermissionsMixin):
    """User model to work with OIDC only authentication."""

    sub_validator = validators.RegexValidator(
        regex=r"^[\w.@+-:]+\Z",
        message=_(
            "Enter a valid sub. This value may contain only letters, "
            "numbers, and @/./+/-/_/: characters."
        ),
    )

    sub = models.CharField(
        _("sub"),
        help_text=_(
            "Required. 255 characters or fewer. Letters, numbers, and @/./+/-/_/: characters only."
        ),
        max_length=255,
        unique=True,
        validators=[sub_validator],
        blank=True,
        null=True,
    )

    full_name = models.CharField(_("full name"), max_length=100, null=True, blank=True)
    short_name = models.CharField(_("short name"), max_length=20, null=True, blank=True)

    email = models.EmailField(_("identity email address"), blank=True, null=True)

    # Unlike the "email" field which stores the email coming from the OIDC token, this field
    # stores the email used by staff users to login to the admin site
    admin_email = models.EmailField(
        _("admin email address"), unique=True, blank=True, null=True
    )

    language = models.CharField(
        max_length=10,
        choices=settings.LANGUAGES,
        default=settings.LANGUAGE_CODE,
        verbose_name=_("language"),
        help_text=_("The language in which the user wants to see the interface."),
    )
    timezone = TimeZoneField(
        choices_display="WITH_GMT_OFFSET",
        use_pytz=False,
        default=settings.TIME_ZONE,
        help_text=_("The timezone in which the user wants to see times."),
    )
    is_device = models.BooleanField(
        _("device"),
        default=False,
        help_text=_("Whether the user is a device or a real user."),
    )
    is_staff = models.BooleanField(
        _("staff status"),
        default=False,
        help_text=_("Whether the user can log into this admin site."),
    )
    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_(
            "Whether this user should be treated as active. "
            "Unselect this instead of deleting accounts."
        ),
    )

    objects = UserManager()

    USERNAME_FIELD = "admin_email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "messages_user"
        verbose_name = _("user")
        verbose_name_plural = _("users")

    def __str__(self):
        return self.email or self.admin_email or str(self.id)


class MailDomain(BaseModel):
    """Mail domain model to store mail domain information."""

    name = models.CharField(_("name"), max_length=255, unique=True)

    alias_of = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True
    )

    oidc_autojoin = models.BooleanField(
        _("oidc autojoin"),
        default=False,
        help_text=_("Create mailboxes automatically based on OIDC emails."),
    )

    identity_sync = models.BooleanField(
        _("Identity sync"),
        default=False,
        help_text=_("Sync mailboxes to identity provider."),
    )

    # This contains French SIRETs
    identity_group_metadata = models.JSONField(
        _("Metadata to sync to the maildomain group in the identity provider"),
        default=None,
        null=True,
        blank=True,
        help_text=_(
            "Metadata to sync to the maildomain group in the identity provider."
        ),
    )

    class Meta:
        db_table = "messages_maildomain"
        verbose_name = _("mail domain")
        verbose_name_plural = _("mail domains")

    def __str__(self):
        return self.name

    def get_expected_dns_records(self) -> List[str]:
        """Get the list of DNS records we expect to be present for this domain."""
        records = [
            {"target": "", "type": "mx", "value": "TODO"},
            {
                "target": "",
                "type": "txt",
                "value": "v=spf1 include:_spf.TODO -all",
            },
            {
                "target": "_dmarc",
                "type": "txt",
                "value": "v=DMARC1; p=reject; adkim=s; aspf=s;",
            },
            {
                "target": "s1._domainkey",
                "type": "cname",
                "value": "TODO",
            },
        ]
        return records


class Mailbox(BaseModel):
    """Mailbox model to store mailbox information."""

    local_part = models.CharField(
        _("local part"),
        max_length=255,
        validators=[validators.RegexValidator(regex=r"^[a-zA-Z0-9_.-]+$")],
    )
    domain = models.ForeignKey("MailDomain", on_delete=models.CASCADE)
    contact = models.ForeignKey(
        "Contact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mailboxes",
    )

    alias_of = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        db_table = "messages_mailbox"
        verbose_name = _("mailbox")
        verbose_name_plural = _("mailboxes")
        unique_together = ("local_part", "domain")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.local_part}@{self.domain.name}"

    @property
    def threads_viewer(self):
        """Return queryset of threads where the mailbox has at least viewer access."""
        return Thread.objects.filter(
            accesses__mailbox=self,
        )

    @property
    def threads_editor(self):
        """Return queryset of threads where the mailbox has editor access."""
        return Thread.objects.filter(
            accesses__mailbox=self,
            accesses__role=ThreadAccessRoleChoices.EDITOR,
        )


class MailboxAccess(BaseModel):
    """Mailbox access model to store mailbox access information."""

    mailbox = models.ForeignKey(
        "Mailbox", on_delete=models.CASCADE, related_name="accesses"
    )
    user = models.ForeignKey(
        "User", on_delete=models.CASCADE, related_name="mailbox_accesses"
    )
    role = models.CharField(
        _("role"),
        max_length=20,
        choices=MailboxRoleChoices.choices,
        default=MailboxRoleChoices.VIEWER,
    )

    class Meta:
        db_table = "messages_mailboxaccess"
        verbose_name = _("mailbox access")
        verbose_name_plural = _("mailbox accesses")
        unique_together = ("mailbox", "user")

    def __str__(self):
        return f"Access to {self.mailbox} for {self.user} with {self.role} role"


class Thread(BaseModel):
    """Thread model to group messages."""

    subject = models.CharField(_("subject"), max_length=255)
    snippet = models.TextField(_("snippet"), blank=True)
    has_unread = models.BooleanField(_("has unread"), default=False)
    has_trashed = models.BooleanField(_("has trashed"), default=False)
    has_draft = models.BooleanField(_("has draft"), default=False)
    has_starred = models.BooleanField(_("has starred"), default=False)
    has_sender = models.BooleanField(_("has sender"), default=False)
    has_messages = models.BooleanField(_("has messages"), default=True)
    is_spam = models.BooleanField(_("is spam"), default=False)
    has_active = models.BooleanField(_("has active"), default=False)
    messaged_at = models.DateTimeField(_("messaged at"), null=True, blank=True)
    sender_names = models.JSONField(_("sender names"), null=True, blank=True)

    class Meta:
        db_table = "messages_thread"
        verbose_name = _("thread")
        verbose_name_plural = _("threads")

    def __str__(self):
        return self.subject

    def update_stats(self):
        """Update the denormalized stats of the thread."""
        # Fetch all message metadata in a single query to avoid multiple DB hits
        message_data = list(
            self.messages.select_related("sender")
            .values(
                "is_unread",
                "is_trashed",
                "is_draft",
                "is_starred",
                "is_sender",
                "is_spam",
                "is_archived",
                "created_at",
                "sender__name",
            )
            .order_by("created_at")
        )

        if not message_data:
            # No messages in thread
            self.has_unread = False
            self.has_trashed = False
            self.has_draft = False
            self.has_starred = False
            self.has_sender = False
            self.has_messages = False
            self.is_spam = False
            self.has_active = False
            self.messaged_at = None
            self.sender_names = None
        else:
            # Compute stats in Python
            self.has_unread = any(
                msg["is_unread"] and not msg["is_trashed"] for msg in message_data
            )
            self.has_trashed = any(msg["is_trashed"] for msg in message_data)
            self.has_draft = any(
                msg["is_draft"] and not msg["is_trashed"] for msg in message_data
            )
            self.has_starred = any(
                msg["is_starred"] and not msg["is_trashed"] for msg in message_data
            )
            self.has_sender = any(
                msg["is_sender"] and not msg["is_trashed"] and not msg["is_draft"]
                for msg in message_data
            )

            # Check if we have any non-trashed, non-spam messages
            active_messages = [
                msg
                for msg in message_data
                if not msg["is_trashed"] and not msg["is_spam"]
            ]
            self.has_messages = len(active_messages) > 0

            # Set is_spam based on first message
            self.is_spam = message_data[0]["is_spam"]

            # Check if thread has active messages (!is_sender && !is_spam && !is_archived && !is_trashed && !is_draft)
            self.has_active = any(
                not msg["is_sender"]
                and not msg["is_spam"]
                and not msg["is_archived"]
                and not msg["is_trashed"]
                and not msg["is_draft"]
                for msg in message_data
            )

            # Set messaged_at to the creation time of the most recent non-trashed message
            non_trashed_messages = [
                msg for msg in message_data if not msg["is_trashed"]
            ]
            if non_trashed_messages:
                self.messaged_at = max(
                    msg["created_at"] for msg in non_trashed_messages
                )
            elif len(message_data) > 0:
                self.messaged_at = max(msg["created_at"] for msg in message_data)
            else:
                self.messaged_at = None

            # Set sender names (first and last sender names)
            sender_names = None
            if len(active_messages) > 0:
                sender_names = [
                    active_messages[0]["sender__name"],
                    active_messages[-1]["sender__name"],
                ]
            elif len(message_data) > 0:
                sender_names = [
                    message_data[0]["sender__name"],
                    message_data[-1]["sender__name"],
                ]

            if sender_names:
                # Get unique sender names from first and last messages
                first_sender = sender_names[0]
                last_sender = sender_names[-1]
                if last_sender is not None and first_sender != last_sender:
                    self.sender_names = [first_sender, last_sender]
                else:
                    self.sender_names = [first_sender]

        self.save(
            update_fields=[
                "has_unread",
                "has_trashed",
                "has_draft",
                "has_starred",
                "has_sender",
                "has_messages",
                "is_spam",
                "has_active",
                "messaged_at",
                "sender_names",
            ]
        )


class Label(BaseModel):
    """Label model to organize threads into folders using slash-based naming."""

    name = models.CharField(
        _("name"),
        max_length=255,
        help_text=_(
            "Name of the label/folder (can use slashes for hierarchy, e.g. 'Work/Projects')"
        ),
    )
    slug = models.SlugField(
        _("slug"),
        max_length=255,
        help_text=_("URL-friendly version of the name"),
    )
    color = models.CharField(
        _("color"),
        max_length=7,
        default="#E3E3FD",
        help_text=_("Color of the label in hex format (e.g. #FF0000)"),
    )
    mailbox = models.ForeignKey(
        "Mailbox",
        on_delete=models.CASCADE,
        related_name="labels",
        help_text=_("Mailbox that owns this label"),
    )
    threads = models.ManyToManyField(
        "Thread",
        related_name="labels",
        help_text=_("Threads that have this label"),
        blank=True,
    )

    class Meta:
        db_table = "messages_label"
        verbose_name = _("label")
        verbose_name_plural = _("labels")
        unique_together = ("slug", "mailbox")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.mailbox})"

    def save(self, *args, **kwargs):
        """
        Ensure all parent labels exist before saving this label.
        """
        # Create parent labels if they don't exist
        if self.name and self.mailbox:
            parts = self.name.split("/")
            current_path = []
            for part in parts[:-1]:  # Exclude the last part (the actual label)
                current_path.append(part)
                parent_name = "/".join(current_path)
                Label.objects.get_or_create(
                    name=parent_name,
                    mailbox=self.mailbox,
                    defaults={"color": self.color},
                )
        # Generate slug from name before saving
        if not self.slug:
            self.slug = slugify(self.name.replace("/", "-"))
        super().save(*args, **kwargs)

    @property
    def parent_name(self):
        """Get the parent label name if this is a subfolder."""
        if "/" not in self.name:
            return None
        return self.name.rsplit("/", 1)[0]

    @property
    def basename(self):
        """Get the base name of the label without parent path."""
        return self.name.rsplit("/", maxsplit=1)[-1]

    @property
    def depth(self):
        """Get the depth of the label in the hierarchy."""
        return self.name.count("/")

    @classmethod
    def get_children(cls, mailbox, parent_name):
        """Get all direct children of a parent label."""
        if parent_name:
            prefix = f"{parent_name}/"
            # Get all labels that start with the parent prefix
            labels = cls.objects.filter(
                mailbox=mailbox,
                name__startswith=prefix,
            )
            # Filter to only get direct children (one level deeper)
            return [
                label for label in labels if label.depth == parent_name.count("/") + 1
            ]

        # Get root level labels (no slashes)
        return cls.objects.filter(
            mailbox=mailbox,
        ).exclude(name__contains="/")

    def get_display_name(self):
        """Return the display name of the label."""
        if "/" not in self.name:
            return self.name
        return self.name.rsplit("/", maxsplit=1)[-1]

    def delete(self, *args, **kwargs):
        """Delete this label and all its child labels (cascading deletion)."""
        # Find all child labels that start with this label's name followed by a slash
        child_labels = Label.objects.filter(
            mailbox=self.mailbox, name__startswith=f"{self.name}/"
        )

        # Delete all child labels first (to maintain referential integrity)
        child_count = child_labels.count()
        if child_count > 0:
            logger.info(
                "Deleting %d child labels for parent label '%s' (mailbox: %s)",
                child_count,
                self.name,
                self.mailbox,
            )
            child_labels.delete()

        # Delete the parent label
        logger.info("Deleting parent label '%s' (mailbox: %s)", self.name, self.mailbox)
        super().delete(*args, **kwargs)


class ThreadAccess(BaseModel):
    """Thread access model to store thread access information for a mailbox."""

    thread = models.ForeignKey(
        "Thread", on_delete=models.CASCADE, related_name="accesses"
    )
    mailbox = models.ForeignKey(
        "Mailbox", on_delete=models.CASCADE, related_name="thread_accesses"
    )
    role = models.CharField(
        _("role"),
        max_length=20,
        choices=ThreadAccessRoleChoices.choices,
        default=ThreadAccessRoleChoices.VIEWER,
    )

    class Meta:
        db_table = "messages_threadaccess"
        verbose_name = _("thread access")
        verbose_name_plural = _("thread accesses")
        unique_together = ("thread", "mailbox")

    def __str__(self):
        return f"{self.thread} - {self.mailbox} - {self.role}"


class Contact(BaseModel):
    """Contact model to store contact information."""

    name = models.CharField(_("name"), max_length=255, null=True, blank=True)
    email = models.EmailField(_("email"))
    mailbox = models.ForeignKey(
        "Mailbox",
        on_delete=models.CASCADE,
        related_name="contacts",
    )

    class Meta:
        db_table = "messages_contact"
        verbose_name = _("contact")
        verbose_name_plural = _("contacts")
        unique_together = ("email", "mailbox")

    def __str__(self):
        if self.name:
            return f"{self.name} <{self.email}>"
        return self.email

    def __repr__(self):
        return str(self)


class MessageRecipient(BaseModel):
    """Message recipient model to store message recipient information."""

    message = models.ForeignKey(
        "Message", on_delete=models.CASCADE, related_name="recipients"
    )
    contact = models.ForeignKey(
        "Contact", on_delete=models.CASCADE, related_name="messages"
    )
    type = models.CharField(
        _("type"),
        max_length=20,
        choices=MessageRecipientTypeChoices.choices,
        default=MessageRecipientTypeChoices.TO,
    )

    delivered_at = models.DateTimeField(_("delivered at"), null=True, blank=True)
    delivery_status = models.CharField(
        _("delivery status"),
        max_length=20,
        null=True,
        blank=True,
        choices=MessageDeliveryStatusChoices.choices,
    )
    delivery_message = models.TextField(_("delivery message"), null=True, blank=True)
    retry_count = models.IntegerField(_("retry count"), default=0)
    retry_at = models.DateTimeField(_("retry at"), null=True, blank=True)

    class Meta:
        db_table = "messages_messagerecipient"
        verbose_name = _("message recipient")
        verbose_name_plural = _("message recipients")
        unique_together = ("message", "contact", "type")

    def __str__(self):
        return f"{self.message} - {self.contact} - {self.type}"


class Message(BaseModel):
    """Message model to store received and sent messages."""

    thread = models.ForeignKey(
        Thread, on_delete=models.CASCADE, related_name="messages"
    )
    subject = models.CharField(_("subject"), max_length=255)
    sender = models.ForeignKey("Contact", on_delete=models.CASCADE)
    parent = models.ForeignKey(
        "Message", on_delete=models.SET_NULL, null=True, blank=True
    )

    # Flags
    is_draft = models.BooleanField(_("is draft"), default=False)
    is_sender = models.BooleanField(_("is sender"), default=False)
    is_starred = models.BooleanField(_("is starred"), default=False)
    is_trashed = models.BooleanField(_("is trashed"), default=False)
    is_unread = models.BooleanField(_("is unread"), default=False)
    is_spam = models.BooleanField(_("is spam"), default=False)
    is_archived = models.BooleanField(_("is archived"), default=False)

    trashed_at = models.DateTimeField(_("trashed at"), null=True, blank=True)
    sent_at = models.DateTimeField(_("sent at"), null=True, blank=True)
    read_at = models.DateTimeField(_("read at"), null=True, blank=True)
    archived_at = models.DateTimeField(_("archived at"), null=True, blank=True)

    mime_id = models.CharField(_("mime id"), max_length=998, null=True, blank=True)

    # Stores the raw MIME message. This will be optimized and offloaded
    # to object storage in the future.
    raw_mime = models.BinaryField(blank=True, default=b"")

    # Store the draft body as arbitrary JSON text. Might be offloaded
    # somewhere else as well.
    draft_body = models.TextField(_("draft body"), blank=True, null=True)

    # Internal cache for parsed data
    _parsed_email_cache: Optional[Dict[str, Any]] = None

    class Meta:
        db_table = "messages_message"
        verbose_name = _("message")
        verbose_name_plural = _("messages")
        ordering = ["-created_at"]

    def __str__(self):
        return self.subject

    def get_parsed_data(self) -> Dict[str, Any]:
        """Parse raw_mime using parser and cache the result."""
        if self._parsed_email_cache is not None:
            return self._parsed_email_cache

        if self.raw_mime:
            self._parsed_email_cache = parse_email_message(self.raw_mime)
        else:
            self._parsed_email_cache = {}
        return self._parsed_email_cache

    def get_parsed_field(self, field_name: str) -> Any:
        """Get a parsed field from the parsed email data."""
        return (self.get_parsed_data() or {}).get(field_name)

    def generate_mime_id(self) -> str:
        """Get the RFC5322 Message-ID of the message."""
        _id = base64.urlsafe_b64encode(uuid.uuid4().bytes).rstrip(b"=").decode("ascii")
        return f"{_id}@_lst.{self.sender.email.split('@')[1]}"

    def get_all_recipient_contacts(self) -> Dict[str, List[Contact]]:
        """Get all recipients of the message."""
        recipients_by_type = {
            kind: [] for kind, _ in MessageRecipientTypeChoices.choices
        }
        for mr in self.recipients.select_related("contact").all():
            recipients_by_type[mr.type].append(mr.contact)
        return recipients_by_type


class Blob(BaseModel):
    """
    Blob model to store immutable binary data.

    This model follows the JMAP blob design, storing raw content that can
    be referenced by multiple attachments.
    """

    sha256 = models.CharField(
        _("sha256 hash"),
        max_length=64,
        db_index=True,
        help_text=_("SHA-256 hash of the blob content"),
    )

    size = models.PositiveIntegerField(
        _("file size"), help_text=_("Size of the blob in bytes")
    )

    type = models.CharField(
        _("content type"), max_length=255, help_text=_("MIME type of the blob")
    )

    raw_content = models.BinaryField(
        _("raw content"),
        help_text=_(
            "Binary content of the blob, will be offloaded to object storage in the future"
        ),
    )

    mailbox = models.ForeignKey(
        "Mailbox",
        on_delete=models.CASCADE,
        related_name="blobs",
        help_text=_("Mailbox that owns this blob"),
    )

    class Meta:
        db_table = "messages_blob"
        verbose_name = _("blob")
        verbose_name_plural = _("blobs")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Blob {self.id} ({self.size} bytes)"


class Attachment(BaseModel):
    """Attachment model to link messages with blobs."""

    name = models.CharField(
        _("file name"),
        max_length=255,
        help_text=_("Original filename of the attachment"),
    )

    blob = models.ForeignKey(
        "Blob",
        on_delete=models.CASCADE,
        related_name="attachments",
        help_text=_("Reference to the blob containing the attachment data"),
    )

    mailbox = models.ForeignKey(
        "Mailbox",
        on_delete=models.CASCADE,
        related_name="attachments",
        help_text=_("Mailbox that owns this attachment"),
    )

    messages = models.ManyToManyField(
        "Message",
        related_name="attachments",
        help_text=_("Messages that use this attachment"),
    )

    class Meta:
        db_table = "messages_attachment"
        verbose_name = _("attachment")
        verbose_name_plural = _("attachments")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.blob.size} bytes)"

    @property
    def content_type(self):
        """Return the content type of the associated blob."""
        return self.blob.type

    @property
    def size(self) -> int:
        """Return the size of the associated blob."""
        return self.blob.size

    @property
    def sha256(self):
        """Return the SHA-256 hash of the associated blob."""
        return self.blob.sha256


class MailDomainAccess(BaseModel):
    """Mail domain access model to store mail domain access information for a user."""

    maildomain = models.ForeignKey(
        "MailDomain", on_delete=models.CASCADE, related_name="accesses"
    )
    user = models.ForeignKey(
        "User", on_delete=models.CASCADE, related_name="maildomain_accesses"
    )
    role = models.CharField(
        _("role"),
        max_length=20,
        choices=MailDomainAccessRoleChoices.choices,
        default=MailDomainAccessRoleChoices.ADMIN,
    )

    class Meta:
        db_table = "messages_maildomainaccess"
        verbose_name = _("mail domain access")
        verbose_name_plural = _("mail domain accesses")
        unique_together = ("maildomain", "user")

    def __str__(self):
        return f"Access to {self.maildomain} for {self.user} with {self.role} role"
