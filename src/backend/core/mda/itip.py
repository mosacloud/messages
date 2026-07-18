"""Inbound iTIP (RFC 5546) ``METHOD:REPLY`` detection and trust gating."""

import logging

from icalendar import Calendar as ICalendar
from jmap_email import body_part_text, first_address_email

logger = logging.getLogger(__name__)

_VERDICT_UNVERIFIED = "none"
_VERDICT_FORGED = "fail"

FLAG_VERIFIED = "verified"
FLAG_UNVERIFIED = "unverified"

_CALENDAR_TYPE = "text/calendar"


def _iter_calendar_parts(parsed_email):
    """Yield every ``text/calendar`` EmailBodyPart in the message tree."""
    root = parsed_email.get("bodyStructure")
    if root:
        stack = [root]
        while stack:
            part = stack.pop()
            if not isinstance(part, dict):
                continue
            sub = part.get("subParts")
            if sub:
                stack.extend(sub)
                continue
            if (part.get("type") or "").lower() == _CALENDAR_TYPE:
                yield part
        return
    for key in ("attachments", "textBody"):
        for part in parsed_email.get(key) or []:
            if isinstance(part, dict) and (part.get("type") or "").lower() == (
                _CALENDAR_TYPE
            ):
                yield part


def _part_ics_text(parsed_email, part):
    """Decode a calendar part to text across both parser projections."""
    text = body_part_text(parsed_email, part)
    if text:
        return text
    raw = part.get("content")
    if isinstance(raw, (bytes, bytearray)):
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    return ""


def find_reply_ics(parsed_email):
    """Return the ICS text of the first ``METHOD:REPLY`` calendar part, or None."""
    for part in _iter_calendar_parts(parsed_email):
        ics = _part_ics_text(parsed_email, part)
        if not ics:
            continue
        try:
            cal = ICalendar.from_ical(ics)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.debug("Skipping unparseable text/calendar part", exc_info=True)
            continue
        if str(cal.get("METHOD") or "").upper() == "REPLY":
            return ics
    return None


def reply_attendee(ics_text):
    """The bare, lower-cased ATTENDEE address of a REPLY, or None."""
    try:
        cal = ICalendar.from_ical(ics_text)
    except Exception:  # pylint: disable=broad-exception-caught
        return None
    for comp in cal.walk("VEVENT"):
        att = comp.get("ATTENDEE")
        if att is None:
            continue
        if isinstance(att, list):
            att = att[0] if att else None
        if att is None:
            continue
        addr = str(att).strip()
        if addr.lower().startswith("mailto:"):
            addr = addr[len("mailto:") :]
        return addr.strip().lower()
    return None


def decide(from_addr, attendee_addr, auth_verdict):
    """Trust decision for an inbound REPLY. Returns ``(should_apply, flag)``."""
    from_norm = (from_addr or "").strip().lower()
    att_norm = (attendee_addr or "").strip().lower()

    if not from_norm or not att_norm or from_norm != att_norm:
        logger.info(
            "iTIP REPLY From/ATTENDEE mismatch (from=%r attendee=%r); skipping",
            from_norm,
            att_norm,
        )
        return False, None

    if auth_verdict == _VERDICT_FORGED:
        logger.info("iTIP REPLY from %s failed DMARC; skipping", from_norm)
        return False, None

    if auth_verdict == _VERDICT_UNVERIFIED:
        return True, FLAG_UNVERIFIED

    return True, FLAG_VERIFIED


def evaluate_inbound_reply(parsed_email, auth_verdict):
    """Detect + gate an inbound REPLY. Returns ``(ics_text, flag)`` or ``(None, None)``."""
    ics = find_reply_ics(parsed_email)
    if ics is None:
        return None, None
    attendee = reply_attendee(ics)
    from_addr = first_address_email(parsed_email.get("from"))
    should_apply, flag = decide(from_addr, attendee, auth_verdict)
    if not should_apply:
        return None, None
    return ics, flag
