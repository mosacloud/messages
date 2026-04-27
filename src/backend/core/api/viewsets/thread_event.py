"""API ViewSet for ThreadEvent model."""

import uuid
from datetime import timedelta

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.shortcuts import get_object_or_404
from django.utils import timezone

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from core import enums, models
from core.signals import delete_assign_user_events

from .. import permissions, serializers

# Window during which an UNASSIGN request by the same author that targets a
# user freshly assigned via a recent ASSIGN ThreadEvent is treated as an
# "undo": the offending users are stripped from the original ASSIGN event
# (deleted if it becomes empty) and no UNASSIGN event is emitted. Mirrors a
# classic "undo a misclick" pattern and avoids cluttering the thread timeline
# with back-to-back noise.
UNDO_WINDOW_SECONDS = 120


@extend_schema(tags=["thread-events"])
class ThreadEventViewSet(
    viewsets.GenericViewSet,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
):
    """ViewSet for ThreadEvent model."""

    serializer_class = serializers.ThreadEventSerializer
    pagination_class = None
    permission_classes = [
        permissions.IsAuthenticated,
        permissions.IsAllowedToAccess,
    ]
    lookup_field = "id"
    lookup_url_kwarg = "id"

    def get_permissions(self):
        """Route write actions through the type-aware permission class.

        Reads (``list``, ``retrieve``) and the personal ``read_mention``
        acknowledgement only need read access on the thread. Writes are
        gated by :class:`HasThreadEventWriteAccess`, which relaxes the
        ThreadAccess role for ``im`` (comment) events while keeping the
        stricter full-edit-rights rule for every other event type.
        """
        if self.action in ["list", "retrieve", "read_mention"]:
            return [permissions.IsAuthenticated(), permissions.IsAllowedToAccess()]

        return [permissions.HasThreadEventWriteAccess()]

    def get_queryset(self):
        """Restrict results to events for the specified thread."""
        thread_id = self.kwargs.get("thread_id")
        if not thread_id:
            return models.ThreadEvent.objects.none()

        queryset = models.ThreadEvent.objects.filter(
            thread_id=thread_id
        ).select_related("author", "channel", "message")

        # Annotate with unread mention status for the current user
        if self.request.user.is_authenticated:
            queryset = queryset.annotate(
                _has_unread_mention=Exists(
                    models.UserEvent.objects.filter(
                        thread_event=OuterRef("pk"),
                        user=self.request.user,
                        type=enums.UserEventTypeChoices.MENTION,
                        read_at__isnull=True,
                    )
                )
            )

        return queryset.order_by("created_at")

    def perform_update(self, serializer):
        """
        For IM : Reject updates made after the configured edit delay elapsed.
        """
        if not serializer.instance.is_editable():
            raise PermissionDenied(
                "This event can no longer be edited (edit delay expired)."
            )
        serializer.save()

    def perform_destroy(self, instance):
        """Reject deletions made after the configured edit delay elapsed.

        Deletion is gated alongside edits so users cannot circumvent the
        window by deleting and recreating an event.
        """
        if not instance.is_editable():
            raise PermissionDenied(
                "This event can no longer be deleted (edit delay expired)."
            )
        instance.delete()

    @extend_schema(
        request=None,
        responses={
            204: OpenApiResponse(description="No response body"),
            404: OpenApiResponse(description="Thread event not found"),
        },
    )
    @action(detail=True, methods=["patch"], url_path="read-mention")
    def read_mention(self, request, **kwargs):
        """Mark the current user's unread MENTION on this ThreadEvent as read.

        Returns 204 even when no UserEvent matches (idempotent); the thread
        event itself is resolved via the standard ``get_object`` lookup so a
        missing event yields 404.
        """
        thread_event = self.get_object()
        models.UserEvent.objects.filter(
            user=request.user,
            thread_event=thread_event,
            type=enums.UserEventTypeChoices.MENTION,
            read_at__isnull=True,
        ).update(read_at=timezone.now())
        return Response(status=status.HTTP_204_NO_CONTENT)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """
        Create a ThreadEvent

        For ASSIGN: if all assignees already have a UserEvent ASSIGN
        on this thread, return 204 without creating a ThreadEvent. If some
        are new, filter data.assignees to new ones only and create.

        For UNASSIGN: if no assignee has a UserEvent ASSIGN on this thread,
        return 204 without creating a ThreadEvent.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        event_type = serializer.validated_data.get("type")
        thread = get_object_or_404(
            models.Thread.objects.select_for_update(),
            id=self.kwargs["thread_id"],
        )

        if event_type in (
            enums.ThreadEventTypeChoices.ASSIGN,
            enums.ThreadEventTypeChoices.UNASSIGN,
        ):
            assignees_data = serializer.validated_data.get("data", {}).get(
                "assignees", []
            )
            assignee_ids = []
            for assignee in assignees_data:
                try:
                    assignee_ids.append(uuid.UUID(assignee["id"]))
                except (ValueError, KeyError):
                    continue

            if not assignee_ids:
                return Response(
                    {"error": f"No valid assignees provided for {event_type} event"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if event_type == enums.ThreadEventTypeChoices.ASSIGN:
                already_assigned = set(
                    models.UserEvent.objects.filter(
                        thread=thread,
                        user_id__in=assignee_ids,
                        type=enums.UserEventTypeChoices.ASSIGN,
                    ).values_list("user_id", flat=True)
                )
                new_assignees = [
                    a
                    for a in assignees_data
                    if uuid.UUID(a["id"]) not in already_assigned
                ]
                if not new_assignees:
                    # All already assigned - Nothing to do
                    return Response(status=status.HTTP_204_NO_CONTENT)

                # Enforce that every new assignee has full edit rights on the
                # thread. Applied after the idempotence filter so that a stale
                # "already assigned" user who lost their rights does not block
                # a request that also adds a valid new assignee — the stale
                # row will be cleaned up by the access-change signals
                # independently.
                new_assignee_ids = {uuid.UUID(a["id"]) for a in new_assignees}
                editable_user_ids = set(
                    models.ThreadAccess.objects.editor_user_ids(
                        thread.id, user_ids=new_assignee_ids
                    )
                )
                if editable_user_ids != new_assignee_ids:
                    raise ValidationError(
                        "Assignee must have editor access on the thread"
                    )

                # Update data to only include new assignees
                serializer.validated_data["data"]["assignees"] = new_assignees

            elif event_type == enums.ThreadEventTypeChoices.UNASSIGN:
                absorbed = self._absorb_unassign_in_undo_window(
                    thread=thread,
                    author=request.user,
                    assignee_ids=assignee_ids,
                    assignees_data=assignees_data,
                )
                if absorbed:
                    remaining_data = [
                        a for a in assignees_data if uuid.UUID(a["id"]) not in absorbed
                    ]
                    if not remaining_data:
                        # Entire unassign absorbed by undo - no new event emitted
                        return Response(status=status.HTTP_204_NO_CONTENT)
                    # Some assignees fell outside the undo window: narrow the
                    # payload and let the regular UNASSIGN path handle them.
                    serializer.validated_data["data"]["assignees"] = remaining_data
                    assignees_data = remaining_data
                    assignee_ids = [uuid.UUID(a["id"]) for a in remaining_data]

                # Try to retrieve ASSIGN UserEvents for the targeted assignees
                has_active_assignment = models.UserEvent.objects.filter(
                    thread=thread,
                    user_id__in=assignee_ids,
                    type=enums.UserEventTypeChoices.ASSIGN,
                ).exists()

                if not has_active_assignment:
                    # No one to unassign - Nothing to do
                    return Response(status=status.HTTP_204_NO_CONTENT)

        serializer.save(thread=thread, author=request.user)
        headers = self.get_success_headers(serializer.data)

        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )

    def _absorb_unassign_in_undo_window(
        self, *, thread, author, assignee_ids, assignees_data
    ):
        """Absorb an UNASSIGN request against recent ASSIGN events by the same author.

        When an UNASSIGN arrives within ``UNDO_WINDOW_SECONDS`` after an ASSIGN
        by the same author for the same user, we treat it as an undo: the user
        is stripped from the original ASSIGN event (the event is deleted if it
        becomes empty) and the matching ``UserEvent(ASSIGN)`` is removed. No
        UNASSIGN ThreadEvent is emitted for these users.

        Returns a set of absorbed user UUIDs. The caller is responsible for
        narrowing the UNASSIGN payload accordingly or returning 204 if fully
        absorbed. Rows are locked with ``select_for_update`` so concurrent
        requests cannot double-undo the same ASSIGN event.
        """
        if not assignee_ids:
            return set()

        cutoff = timezone.now() - timedelta(seconds=UNDO_WINDOW_SECONDS)
        target_ids = set(assignee_ids)
        recent_assigns = list(
            models.ThreadEvent.objects.select_for_update()
            .filter(
                thread=thread,
                author=author,
                type=enums.ThreadEventTypeChoices.ASSIGN,
                created_at__gte=cutoff,
            )
            .order_by("-created_at")
        )

        absorbed = set()
        for event in recent_assigns:
            original_assignees = (event.data or {}).get("assignees", [])
            if not original_assignees:
                continue
            remaining = []
            changed = False
            for assignee in original_assignees:
                try:
                    aid = uuid.UUID(assignee["id"])
                except (ValueError, KeyError, TypeError):
                    remaining.append(assignee)
                    continue
                if aid in target_ids and aid not in absorbed:
                    absorbed.add(aid)
                    changed = True
                else:
                    remaining.append(assignee)
            if not changed:
                continue
            if remaining:
                event.data = {**event.data, "assignees": remaining}
                event.save()
            else:
                event.delete()

        if absorbed:
            absorbed_data = [
                a
                for a in assignees_data
                if a.get("id") and uuid.UUID(a["id"]) in absorbed
            ]
            delete_assign_user_events(None, thread, absorbed_data)

        return absorbed
