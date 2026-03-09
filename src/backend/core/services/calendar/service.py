"""CalDAV calendar service for RSVP and event management."""

import logging

import caldav
from caldav.elements import dav

logger = logging.getLogger(__name__)


class CalDAVService:
    """Service for interacting with a CalDAV server."""

    def __init__(self, url: str, username: str, password: str):
        self.url = url
        self.username = username
        self.password = password
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = caldav.DAVClient(
                url=self.url,
                username=self.username,
                password=self.password,
            )
        return self._client

    @property
    def principal(self):
        return self.client.principal()

    def list_calendars(self):
        """List all available calendars.

        Returns:
            List of dicts with id, name, and color for each calendar.
        """
        calendars = self.principal.calendars()
        result = []
        for cal in calendars:
            props = cal.get_properties([dav.DisplayName()])
            display_name = props.get("{DAV:}displayname", str(cal.url))
            result.append({
                "id": str(cal.url),
                "name": display_name,
            })
        return result

    def get_calendar(self, calendar_id=None):
        """Get a specific calendar by ID, or the first one available."""
        calendars = self.principal.calendars()
        if not calendars:
            raise ValueError("No calendars available on this CalDAV server.")

        if calendar_id:
            for cal in calendars:
                if str(cal.url) == calendar_id:
                    return cal
            raise ValueError(f"Calendar '{calendar_id}' not found.")

        return calendars[0]

    def check_conflicts(self, start, end):
        """Check for events that conflict with the given time range across all calendars.

        Args:
            start: Start datetime (UTC)
            end: End datetime (UTC)

        Returns:
            List of conflicting events as dicts with summary, start, end, calendar_name.
        """
        calendars = self.principal.calendars()
        conflicts = []

        for cal in calendars:
            props = cal.get_properties([dav.DisplayName()])
            calendar_name = props.get("{DAV:}displayname", str(cal.url))

            try:
                events = cal.date_search(start=start, end=end, expand=True)
            except Exception:
                logger.exception(
                    "Error searching for conflicts on calendar %s", calendar_name
                )
                continue

            for event in events:
                try:
                    vevent = event.vobject_instance.vevent
                    conflicts.append({
                        "summary": str(getattr(vevent, "summary", "Untitled event")),
                        "start": vevent.dtstart.value.isoformat() if hasattr(vevent, "dtstart") else None,
                        "end": vevent.dtend.value.isoformat() if hasattr(vevent, "dtend") else None,
                        "calendar_name": calendar_name,
                    })
                except Exception:
                    logger.warning("Could not parse conflicting event", exc_info=True)
                    continue

        return conflicts

    def add_event(self, ics_data, calendar_id=None):
        """Add an ICS event to a calendar.

        Args:
            ics_data: Raw ICS content string
            calendar_id: Optional specific calendar to add to

        Returns:
            True if successful
        """
        calendar = self.get_calendar(calendar_id)
        calendar.save_event(ics_data)
        return True

    def respond_to_event(self, ics_data, response, attendee_email, calendar_id=None):
        """Respond to a calendar event invitation (RSVP).

        This adds the event to the calendar with the attendee's PARTSTAT updated.

        Args:
            ics_data: Raw ICS content string
            response: One of "ACCEPTED", "DECLINED", "TENTATIVE"
            attendee_email: The email of the responding attendee
            calendar_id: Optional specific calendar to use

        Returns:
            True if successful
        """
        import re

        # Update PARTSTAT in the ICS data for the responding attendee
        modified_ics = self._update_partstat(ics_data, attendee_email, response)

        # Change METHOD from REQUEST to REPLY
        modified_ics = re.sub(
            r"METHOD:REQUEST",
            "METHOD:REPLY",
            modified_ics,
        )

        # Add the event to the calendar (with updated status)
        if response != "DECLINED":
            calendar = self.get_calendar(calendar_id)
            # For the calendar copy, remove METHOD line (it should be stored as a regular event)
            calendar_ics = re.sub(r"METHOD:.*\r?\n", "", modified_ics)
            calendar.save_event(calendar_ics)

        return True

    @staticmethod
    def _update_partstat(ics_data, attendee_email, new_partstat):
        """Update the PARTSTAT for a specific attendee in ICS data."""
        import re

        lines = ics_data.splitlines(keepends=True)
        result = []
        i = 0
        while i < len(lines):
            line = lines[i]
            # Unfold continuation lines
            full_line = line
            while i + 1 < len(lines) and lines[i + 1].startswith((' ', '\t')):
                i += 1
                full_line += lines[i]

            # Check if this is an ATTENDEE line for our email
            if full_line.upper().startswith("ATTENDEE") and attendee_email.lower() in full_line.lower():
                # Update or add PARTSTAT
                if "PARTSTAT=" in full_line.upper():
                    full_line = re.sub(
                        r"PARTSTAT=[^;:\r\n]+",
                        f"PARTSTAT={new_partstat}",
                        full_line,
                        flags=re.IGNORECASE,
                    )
                else:
                    # Add PARTSTAT before the colon separator
                    full_line = full_line.replace(
                        ":MAILTO:",
                        f";PARTSTAT={new_partstat}:MAILTO:",
                        1,
                    )
                # Remove RSVP=TRUE since we're responding
                full_line = re.sub(r";?RSVP=TRUE", "", full_line, flags=re.IGNORECASE)

            result.append(full_line)
            i += 1

        return "".join(result)

    @classmethod
    def from_channel(cls, channel):
        """Create a CalDAVService from a Channel model instance.

        The channel settings should contain:
        - url: CalDAV server URL
        - username: Authentication username
        - password: Authentication password
        """
        settings = channel.settings
        url = settings.get("url")
        username = settings.get("username")
        password = settings.get("password")

        if not url:
            raise ValueError("CalDAV channel is missing 'url' in settings.")

        return cls(url=url, username=username or "", password=password or "")
