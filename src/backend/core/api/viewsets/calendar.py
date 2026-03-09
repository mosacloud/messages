"""API ViewSet for calendar operations (RSVP, conflict detection, calendar listing)."""

import logging
from datetime import datetime

from django.shortcuts import get_object_or_404
from django.utils.functional import cached_property

from drf_spectacular.utils import (
    extend_schema,
    inline_serializer,
)
from rest_framework import permissions, status
from rest_framework import serializers as drf_serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from core import models
from core.api.viewsets.task import register_task_owner
from core.services.calendar.tasks import calendar_add_event_task, calendar_rsvp_task

logger = logging.getLogger(__name__)


class CalDAVChannelMixin:
    """Mixin to get the CalDAV channel for a mailbox."""

    @cached_property
    def mailbox(self):
        return get_object_or_404(models.Mailbox, id=self.kwargs["mailbox_id"])

    def get_caldav_channel(self):
        """Get the CalDAV channel for the mailbox, or None."""
        return (
            models.Channel.objects.filter(
                mailbox=self.mailbox, type="caldav"
            ).first()
        )

    def require_caldav_channel(self):
        """Get the CalDAV channel or raise 404."""
        channel = self.get_caldav_channel()
        if not channel:
            from rest_framework.exceptions import NotFound
            raise NotFound("No CalDAV calendar is configured for this mailbox.")
        return channel


@extend_schema(tags=["calendar"])
class CalendarRsvpView(CalDAVChannelMixin, APIView):
    """Submit an RSVP response to a calendar event."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=inline_serializer(
            name="CalendarRsvpRequest",
            fields={
                "ics_data": drf_serializers.CharField(
                    help_text="Raw ICS content of the event"
                ),
                "response": drf_serializers.ChoiceField(
                    choices=["ACCEPTED", "DECLINED", "TENTATIVE"],
                    help_text="RSVP response",
                ),
                "calendar_id": drf_serializers.CharField(
                    required=False,
                    allow_null=True,
                    help_text="Optional specific calendar URL",
                ),
            },
        ),
        responses={
            200: inline_serializer(
                name="CalendarRsvpResponse",
                fields={
                    "task_id": drf_serializers.CharField(),
                },
            ),
        },
    )
    def post(self, request, mailbox_id):
        ics_data = request.data.get("ics_data")
        response_type = request.data.get("response")
        calendar_id = request.data.get("calendar_id")

        if not ics_data or not response_type:
            return Response(
                {"detail": "ics_data and response are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if response_type not in ("ACCEPTED", "DECLINED", "TENTATIVE"):
            return Response(
                {"detail": "response must be ACCEPTED, DECLINED, or TENTATIVE."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        channel = self.require_caldav_channel()

        # Use the mailbox email as the attendee email
        attendee_email = str(self.mailbox)

        task = calendar_rsvp_task.delay(
            channel_id=str(channel.id),
            ics_data=ics_data,
            response=response_type,
            attendee_email=attendee_email,
            calendar_id=calendar_id,
        )
        register_task_owner(task.id, request.user.id)

        return Response({"task_id": task.id}, status=status.HTTP_200_OK)


@extend_schema(tags=["calendar"])
class CalendarAddEventView(CalDAVChannelMixin, APIView):
    """Add an event to a CalDAV calendar."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=inline_serializer(
            name="CalendarAddEventRequest",
            fields={
                "ics_data": drf_serializers.CharField(
                    help_text="Raw ICS content of the event"
                ),
                "calendar_id": drf_serializers.CharField(
                    required=False,
                    allow_null=True,
                    help_text="Optional specific calendar URL",
                ),
            },
        ),
        responses={
            200: inline_serializer(
                name="CalendarAddEventResponse",
                fields={
                    "task_id": drf_serializers.CharField(),
                },
            ),
        },
    )
    def post(self, request, mailbox_id):
        ics_data = request.data.get("ics_data")
        calendar_id = request.data.get("calendar_id")

        if not ics_data:
            return Response(
                {"detail": "ics_data is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        channel = self.require_caldav_channel()

        task = calendar_add_event_task.delay(
            channel_id=str(channel.id),
            ics_data=ics_data,
            calendar_id=calendar_id,
        )
        register_task_owner(task.id, request.user.id)

        return Response({"task_id": task.id}, status=status.HTTP_200_OK)


@extend_schema(tags=["calendar"])
class CalendarConflictsView(CalDAVChannelMixin, APIView):
    """Check for conflicting events in a given time range."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=inline_serializer(
            name="CalendarConflictsRequest",
            fields={
                "start": drf_serializers.DateTimeField(
                    help_text="Start of the time range (ISO 8601)"
                ),
                "end": drf_serializers.DateTimeField(
                    help_text="End of the time range (ISO 8601)"
                ),
            },
        ),
        responses={
            200: inline_serializer(
                name="CalendarConflictsResponse",
                fields={
                    "conflicts": drf_serializers.ListField(
                        child=drf_serializers.DictField()
                    ),
                },
            ),
        },
    )
    def post(self, request, mailbox_id):
        start = request.data.get("start")
        end = request.data.get("end")

        if not start or not end:
            return Response(
                {"detail": "start and end are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            if isinstance(start, str):
                start = datetime.fromisoformat(start)
            if isinstance(end, str):
                end = datetime.fromisoformat(end)
        except (ValueError, TypeError):
            return Response(
                {"detail": "start and end must be valid ISO 8601 datetimes."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        channel = self.require_caldav_channel()

        from core.services.calendar.service import CalDAVService

        try:
            service = CalDAVService.from_channel(channel)
            conflicts = service.check_conflicts(start=start, end=end)
        except Exception as e:
            logger.exception("Error checking calendar conflicts: %s", e)
            return Response(
                {"detail": "Failed to check for conflicts."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"conflicts": conflicts}, status=status.HTTP_200_OK)


@extend_schema(tags=["calendar"])
class CalendarListView(CalDAVChannelMixin, APIView):
    """List available calendars on the CalDAV server."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        responses={
            200: inline_serializer(
                name="CalendarListResponse",
                fields={
                    "calendars": drf_serializers.ListField(
                        child=drf_serializers.DictField()
                    ),
                },
            ),
        },
    )
    def get(self, request, mailbox_id):
        channel = self.get_caldav_channel()
        if not channel:
            return Response({"calendars": []}, status=status.HTTP_200_OK)

        from core.services.calendar.service import CalDAVService

        try:
            service = CalDAVService.from_channel(channel)
            calendars = service.list_calendars()
        except Exception as e:
            logger.exception("Error listing calendars: %s", e)
            return Response(
                {"detail": "Failed to list calendars."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"calendars": calendars}, status=status.HTTP_200_OK)
