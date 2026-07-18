"""Unit tests for inbound iTIP REPLY detection + trust gating (core.mda.itip)."""
# pylint: disable=missing-function-docstring

from core.mda import itip

REPLY_ICS = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
METHOD:REPLY
BEGIN:VEVENT
UID:evt-1@example.com
DTSTAMP:20260101T120000Z
DTSTART:20260601T100000Z
DTEND:20260601T110000Z
SEQUENCE:0
ORGANIZER:mailto:org@example.com
ATTENDEE;PARTSTAT=ACCEPTED:mailto:Alice@Corp.example
END:VEVENT
END:VCALENDAR"""

REQUEST_ICS = REPLY_ICS.replace("METHOD:REPLY", "METHOD:REQUEST")


def _parsed(ics, from_email):
    """Minimal JmapEmail-shaped dict with a single text/calendar leaf."""
    return {
        "from": [{"email": from_email}],
        "bodyStructure": {
            "type": "text/calendar",
            "content": ics,
            "subParts": None,
        },
    }


class TestDecide:
    def test_verified_aligned_applies_verified(self):
        assert itip.decide("alice@corp.example", "alice@corp.example", None) == (
            True,
            itip.FLAG_VERIFIED,
        )

    def test_unverifiable_aligned_applies_unverified(self):
        assert itip.decide("alice@corp.example", "alice@corp.example", "none") == (
            True,
            itip.FLAG_UNVERIFIED,
        )

    def test_forged_never_applies(self):
        assert itip.decide("alice@corp.example", "alice@corp.example", "fail") == (
            False,
            None,
        )

    def test_from_attendee_mismatch_never_applies(self):
        assert itip.decide("bob@corp.example", "alice@corp.example", None) == (
            False,
            None,
        )

    def test_case_insensitive_alignment(self):
        assert itip.decide("Alice@Corp.Example", "alice@corp.example", None) == (
            True,
            itip.FLAG_VERIFIED,
        )

    def test_empty_addresses_never_apply(self):
        assert itip.decide("", "", None) == (False, None)


class TestFindReplyIcs:
    def test_finds_reply_part(self):
        parsed = _parsed(REPLY_ICS, "alice@corp.example")
        assert itip.find_reply_ics(parsed) is not None

    def test_ignores_request_method(self):
        parsed = _parsed(REQUEST_ICS, "org@example.com")
        assert itip.find_reply_ics(parsed) is None

    def test_no_calendar_part(self):
        parsed = {
            "from": [{"email": "a@b.example"}],
            "bodyStructure": {"type": "text/plain", "content": "hi", "subParts": None},
        }
        assert itip.find_reply_ics(parsed) is None

    def test_finds_in_attachments_fallback(self):
        parsed = {
            "from": [{"email": "alice@corp.example"}],
            "attachments": [{"type": "text/calendar", "content": REPLY_ICS}],
        }
        assert itip.find_reply_ics(parsed) is not None


class TestReplyAttendee:
    def test_strips_mailto_and_lowercases(self):
        assert itip.reply_attendee(REPLY_ICS) == "alice@corp.example"

    def test_none_when_unparseable(self):
        assert itip.reply_attendee("not an ics") is None


class TestEvaluateInboundReply:
    def test_verified_aligned(self):
        parsed = _parsed(REPLY_ICS, "alice@corp.example")
        ics, flag = itip.evaluate_inbound_reply(parsed, None)
        assert ics is not None
        assert flag == itip.FLAG_VERIFIED

    def test_mismatch_rejected(self):
        parsed = _parsed(REPLY_ICS, "bob@corp.example")
        assert itip.evaluate_inbound_reply(parsed, None) == (None, None)

    def test_forged_rejected(self):
        parsed = _parsed(REPLY_ICS, "alice@corp.example")
        assert itip.evaluate_inbound_reply(parsed, "fail") == (None, None)

    def test_no_reply_part(self):
        parsed = _parsed(REQUEST_ICS, "org@example.com")
        assert itip.evaluate_inbound_reply(parsed, None) == (None, None)
