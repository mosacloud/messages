"""API ViewSet for Contact model."""

from django.db.models import Q

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.response import Response

from core import models

from .. import permissions, serializers


class ContactViewSet(
    viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin
):
    """ViewSet for Contact model."""

    serializer_class = serializers.ContactSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        """Restrict results to contacts of mailboxes the current user has access to."""
        user_mailbox_ids = self.request.user.mailbox_accesses.values_list(
            "mailbox_id", flat=True
        )
        return models.Contact.objects.filter(
            mailbox_id__in=user_mailbox_ids
        ).select_related("mailbox", "mailbox__domain")

    @extend_schema(
        tags=["contacts"],
        parameters=[
            OpenApiParameter(
                name="mailbox_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description="Filter contacts by mailbox ID.",
                required=False,
            ),
            OpenApiParameter(
                name="q",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Search contacts by name or email (case insensitive).",
                required=False,
            ),
        ],
        responses=serializers.ContactSerializer(many=True),
    )
    def list(self, request, *args, **kwargs):
        """
        List contacts with optional filtering by mailbox and search query.
        For a mailbox, it returns all contacts in the mailbox and all contacts
        in the same domain as the mailbox.

        Query parameters:
        - mailbox_id: Optional UUID to filter contacts by mailbox
        - q: Optional search query for name or email (case insensitive)
        """
        # base queryset will be used to store contacts of the selected mailbox
        queryset = self.get_queryset()

        # extended_queryset will be used to store contacts from the same domain
        # as the selected mailbox
        extended_queryset = models.Contact.objects.none()

        # filter by search query on name and email (multi-word)
        search_query = request.query_params.get("q", "")
        queryset = (
            self.filter_by_search(queryset, search_query) if search_query else queryset
        )

        # Filter by mailbox if specified
        if mailbox_id := request.query_params.get("mailbox_id"):
            # check if the current user has access to the selected mailbox
            try:
                mailbox_access = (
                    self.request.user.mailbox_accesses.filter(mailbox_id=mailbox_id)
                    .select_related("mailbox", "mailbox__domain")
                    .get()
                )
            except models.MailboxAccess.DoesNotExist:
                return Response(
                    {"detail": "Invalid mailbox_id or access denied."},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # get all contacts of the selected mailbox
            queryset = queryset.filter(mailbox=mailbox_access.mailbox)

            # get all contacts with same domain as the selected mailbox
            domain_contacts_ids = models.Mailbox.objects.filter(
                domain=mailbox_access.mailbox.domain
            ).values_list("contact__id", flat=True)
            extended_queryset = models.Contact.objects.filter(
                id__in=domain_contacts_ids
            ).select_related("mailbox", "mailbox__domain")

            # some contacts from the same domain may appear in the contacts
            # of the selected mailbox, so we need to exclude them
            extended_queryset = extended_queryset.exclude(
                email__in=queryset.values_list("email", flat=True)
            )
            # apply search filter to extended queryset
            if search_query:
                extended_queryset = self.filter_by_search(
                    extended_queryset, search_query
                )

        # finally merge base and extended querysets
        queryset = queryset.union(extended_queryset).order_by("name", "email")
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def filter_by_search(self, queryset, search_query):
        """Search contacts by name or email (case insensitive)."""
        search_words = search_query.strip().split()
        if search_words:
            search_filters = Q()
            for word in search_words:
                word_filter = Q(name__unaccent__icontains=word) | Q(
                    email__unaccent__icontains=word
                )
                search_filters &= word_filter
            queryset = queryset.filter(search_filters)
        return queryset
