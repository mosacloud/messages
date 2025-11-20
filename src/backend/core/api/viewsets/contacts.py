"""API ViewSet for Contact model."""

from django.db.models import Q

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import mixins, viewsets
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
        return models.Contact.objects.filter(mailbox_id__in=user_mailbox_ids).order_by(
            "name", "email"
        )

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

        Query parameters:
        - mailbox_id: Optional UUID to filter contacts by mailbox
        - q: Optional search query for name or email (case insensitive)
        """
        queryset = self.get_queryset()

        # Filter by mailbox if specified
        mailbox_id = request.query_params.get("mailbox_id")
        if mailbox_id:
            queryset = queryset.filter(mailbox_id=mailbox_id)

        # Advanced search on name and email (multi-word)
        search_query = request.query_params.get("q", "")
        if search_query:
            search_words = search_query.strip().split()
            if search_words:
                search_filters = Q()
                for word in search_words:
                    word_filter = Q(name__unaccent__icontains=word) | Q(
                        email__unaccent__icontains=word
                    )
                    search_filters &= word_filter
                queryset = queryset.filter(search_filters)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
