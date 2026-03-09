"""Celery tasks for CalDAV calendar operations."""

from typing import Any, Dict

from celery.utils.log import get_task_logger
from sentry_sdk import capture_exception

from core.models import Channel

from messages.celery_app import app as celery_app

logger = get_task_logger(__name__)


@celery_app.task(bind=True)
def calendar_rsvp_task(
    self,
    channel_id: str,
    ics_data: str,
    response: str,
    attendee_email: str,
    calendar_id: str | None = None,
) -> Dict[str, Any]:
    """
    Respond to a calendar event via CalDAV (RSVP).

    Args:
        channel_id: UUID of the CalDAV channel
        ics_data: Raw ICS content
        response: ACCEPTED, DECLINED, or TENTATIVE
        attendee_email: Email of the responding attendee
        calendar_id: Optional specific calendar URL to use
    """
    from core.services.calendar.service import CalDAVService

    try:
        channel = Channel.objects.get(id=channel_id, type="caldav")
    except Channel.DoesNotExist:
        return {
            "status": "FAILURE",
            "result": None,
            "error": "CalDAV channel not found.",
        }

    try:
        service = CalDAVService.from_channel(channel)
        service.respond_to_event(
            ics_data=ics_data,
            response=response,
            attendee_email=attendee_email,
            calendar_id=calendar_id,
        )

        return {
            "status": "SUCCESS",
            "result": {"response": response},
            "error": None,
        }
    except Exception as e:
        capture_exception(e)
        logger.exception("Error responding to calendar event: %s", e)
        return {
            "status": "FAILURE",
            "result": None,
            "error": f"Failed to send RSVP: {e}",
        }


@celery_app.task(bind=True)
def calendar_add_event_task(
    self,
    channel_id: str,
    ics_data: str,
    calendar_id: str | None = None,
) -> Dict[str, Any]:
    """
    Add a calendar event to a CalDAV calendar.

    Args:
        channel_id: UUID of the CalDAV channel
        ics_data: Raw ICS content
        calendar_id: Optional specific calendar URL to use
    """
    from core.services.calendar.service import CalDAVService

    try:
        channel = Channel.objects.get(id=channel_id, type="caldav")
    except Channel.DoesNotExist:
        return {
            "status": "FAILURE",
            "result": None,
            "error": "CalDAV channel not found.",
        }

    try:
        service = CalDAVService.from_channel(channel)
        service.add_event(ics_data=ics_data, calendar_id=calendar_id)

        return {
            "status": "SUCCESS",
            "result": {"added": True},
            "error": None,
        }
    except Exception as e:
        capture_exception(e)
        logger.exception("Error adding calendar event: %s", e)
        return {
            "status": "FAILURE",
            "result": None,
            "error": f"Failed to add event: {e}",
        }
