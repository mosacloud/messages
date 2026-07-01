"""Unit tests for :mod:`pymta.handler`.

These tests cover the *session-state* invariants of the handler (counter
bumps, gate paths). They run the handler against fake session/envelope/MDA
stand-ins — no Docker stack, no real SMTP traffic.
"""

from __future__ import annotations

import types
from ipaddress import ip_address

import pytest

from pymta import settings
from pymta.handler import (
    _RCPT_MISSES_ATTR,
    _SOFT_ERRORS_ATTR,
    InboundHandler,
    NULL_SENDER_SENTINEL,
)
from pymta.mda_async import MDAResult


class _FakeMDA:
    """Stand-in for MDAClient — returns whatever the test wires up."""

    def __init__(self, check_result: MDAResult | None = None):
        self.check_result = check_result or MDAResult(
            ok=True, temp_fail=False, payload={}, status_code=200
        )
        self.deliver_kwargs: dict | None = None

    async def check_recipient(self, address: str) -> MDAResult:
        return self.check_result

    async def deliver(self, **kwargs) -> MDAResult:
        self.deliver_kwargs = kwargs
        return MDAResult(
            ok=True, temp_fail=False, payload={"status": "ok"}, status_code=200
        )


def _session():
    return types.SimpleNamespace(host_name=None, peer=("203.0.113.5", 12345))


def _envelope():
    return types.SimpleNamespace(
        mail_from=None, rcpt_tos=[], mail_options=[], rcpt_options=[], content=b""
    )


def _handler(mda=None) -> InboundHandler:
    return InboundHandler(mda or _FakeMDA())


# ---------------------------------------------------------------------------
# MAIL SIZE= path bumps the soft-error counter on both rejection branches.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mail_size_bad_value_bumps_soft_errors():
    session, envelope = _session(), _envelope()
    reply = await _handler().handle_MAIL(
        None, session, envelope, "<a@example.com>", ["SIZE=not-a-number"]
    )
    assert reply.startswith("501")
    assert getattr(session, _SOFT_ERRORS_ATTR) == 1


@pytest.mark.asyncio
async def test_mail_size_oversize_bumps_soft_errors():
    session, envelope = _session(), _envelope()
    too_big = settings.MAX_INCOMING_EMAIL_SIZE + 1
    reply = await _handler().handle_MAIL(
        None, session, envelope, "<a@example.com>", [f"SIZE={too_big}"]
    )
    assert reply.startswith("552")
    assert getattr(session, _SOFT_ERRORS_ATTR) == 1


# ---------------------------------------------------------------------------
# DATA negative paths bump the soft-error counter.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_data_nul_byte_bumps_soft_errors():
    session, envelope = _session(), _envelope()
    envelope.content = b"Subject: x\r\n\r\nhello\x00world\r\n"
    reply = await _handler().handle_DATA(None, session, envelope)
    assert reply.startswith("554")
    assert getattr(session, _SOFT_ERRORS_ATTR) == 1


@pytest.mark.asyncio
async def test_data_oversize_bumps_soft_errors():
    session, envelope = _session(), _envelope()
    envelope.content = b"x" * (settings.MAX_INCOMING_EMAIL_SIZE + 10)
    reply = await _handler().handle_DATA(None, session, envelope)
    assert reply.startswith("552")
    assert getattr(session, _SOFT_ERRORS_ATTR) == 1


@pytest.mark.asyncio
async def test_data_max_envelopes_bumps_soft_errors():
    session, envelope = _session(), _envelope()
    setattr(session, "_pymta_envelopes", settings.PYMTA_MAX_ENVELOPES_PER_CONNECTION)
    reply = await _handler().handle_DATA(None, session, envelope)
    assert reply.startswith("451")
    assert getattr(session, _SOFT_ERRORS_ATTR) == 1


# ---------------------------------------------------------------------------
# RCPT miss counter / dedicated cutoff (S3).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rcpt_miss_counter_triggers_421_at_limit(monkeypatch):
    # Tight limit so we don't have to do many round-trips.
    monkeypatch.setattr(settings, "PYMTA_MAX_RCPT_MISSES_PER_SESSION", 3)
    mda = _FakeMDA(
        check_result=MDAResult(
            ok=True, temp_fail=False, payload={}, status_code=200
        )  # exists=False for every address
    )
    handler, session, envelope = _handler(mda), _session(), _envelope()

    # First two misses get the normal 550.
    for i in range(2):
        reply = await handler.handle_RCPT(
            None, session, envelope, f"<miss{i}@example.com>", []
        )
        assert reply.startswith("550"), reply
    # Third miss hits the per-session cap and forces 421.
    reply = await handler.handle_RCPT(
        None, session, envelope, "<miss3@example.com>", []
    )
    assert reply.startswith("421")
    assert getattr(session, _RCPT_MISSES_ATTR) == 3


@pytest.mark.asyncio
async def test_rcpt_existence_does_not_increment_miss_counter():
    mda = _FakeMDA(
        check_result=MDAResult(
            ok=True,
            temp_fail=False,
            payload={"hit@example.com": True},
            status_code=200,
        )
    )
    handler, session, envelope = _handler(mda), _session(), _envelope()
    reply = await handler.handle_RCPT(
        None, session, envelope, "<hit@example.com>", []
    )
    assert reply.startswith("250")
    assert getattr(session, _RCPT_MISSES_ATTR, 0) == 0


# ---------------------------------------------------------------------------
# Hard-error budget cutoff still fires from the existing gate.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hard_error_limit_blocks_further_rcpts(monkeypatch):
    monkeypatch.setattr(settings, "PYMTA_HARD_ERROR_LIMIT", 2)
    handler, session, envelope = _handler(), _session(), _envelope()
    setattr(session, _SOFT_ERRORS_ATTR, 2)
    reply = await handler.handle_RCPT(
        None, session, envelope, "<anyone@example.com>", []
    )
    assert reply.startswith("421")


# ---------------------------------------------------------------------------
# Null sender survives the round-trip via the sentinel.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_null_sender_round_trip_via_sentinel():
    session, envelope = _session(), _envelope()
    reply = await _handler().handle_MAIL(None, session, envelope, "<>", [])
    assert reply.startswith("250")
    assert envelope.mail_from == NULL_SENDER_SENTINEL


# ---------------------------------------------------------------------------
# PROXY-protocol source survives the STARTTLS session rebuild.
#
# aiosmtpd rebuilds ``session`` from scratch when the client issues STARTTLS,
# dropping ``session.proxy_data`` and resetting ``session.peer`` to the raw TCP
# peer (the load balancer). The real client IP must still reach the MDA on the
# post-TLS DATA command. Regression guard for the "client_ip == LB internal IP"
# bug seen in production behind HAProxy.
# ---------------------------------------------------------------------------


class _FakeServer:
    """Per-connection SMTP protocol stand-in (survives the STARTTLS swap)."""

    async def acquire_gate_post_proxy(self, ip: str) -> bool:
        return True


@pytest.mark.asyncio
async def test_proxy_source_survives_starttls_and_reaches_mda():
    real_client = ip_address("203.0.113.9")
    lb_peer = ("10.89.0.2", 43154)  # HAProxy/podman gateway — NOT the client

    server = _FakeServer()
    mda = _FakeMDA()
    handler = _handler(mda)

    # 1. PROXY header parsed on the plaintext connection, before STARTTLS.
    proxy_data = types.SimpleNamespace(
        src_addr=real_client, src_port=52000, version=2, protocol=1
    )
    session_pre_tls = types.SimpleNamespace(
        host_name=None, peer=lb_peer, proxy_data=proxy_data
    )
    gate = await handler.handle_PROXY(server, session_pre_tls, _envelope(), proxy_data)
    assert gate is True

    # 2. STARTTLS rebuilds the session: proxy_data gone, peer is the LB again.
    #    Same server instance carries over.
    session_post_tls = types.SimpleNamespace(
        host_name=None, peer=lb_peer, proxy_data=None
    )

    # 3. DATA delivers using the post-TLS session.
    envelope = _envelope()
    envelope.mail_from = "sender@example.com"
    envelope.rcpt_tos = ["rcpt@example.com"]
    envelope.content = b"Subject: hi\r\n\r\nbody\r\n"
    reply = await handler.handle_DATA(server, session_post_tls, envelope)

    assert reply.startswith("250"), reply
    assert mda.deliver_kwargs is not None
    assert mda.deliver_kwargs["client_address"] == "203.0.113.9"
    assert mda.deliver_kwargs["client_port"] == "52000"
