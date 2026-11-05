"""Error monitoring: what reaches Sentry, and what never does (captured in memory, not sent)."""

from collections.abc import Iterator
from typing import Any

import pytest
import sentry_sdk
import structlog
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport

from sia.core.logging import configure_logging
from sia.core.observability import init_sentry, scrub_event
from tests.conftest import SettingsFactory


class CapturingTransport(Transport):
    def __init__(self, options: Any = None) -> None:
        super().__init__(options)
        self.events: list[Any] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        for item in envelope.items:
            event = item.get_event()
            if event is not None:
                self.events.append(event)


@pytest.fixture
def sentry(make_settings: SettingsFactory) -> Iterator[CapturingTransport]:
    transport = CapturingTransport()
    settings = make_settings(SENTRY_DSN="https://public@o0.ingest.sentry.io/1", SIA_RELEASE="abc")
    assert init_sentry(settings, "worker", transport=transport)
    configure_logging("INFO", "json")
    yield transport
    sentry_sdk.get_client().close()
    sentry_sdk.get_global_scope().set_client(None)


def flushed(transport: CapturingTransport) -> list[Any]:
    sentry_sdk.get_client().flush()
    return transport.events


def test_nothing_starts_without_a_dsn(make_settings: SettingsFactory) -> None:
    assert init_sentry(make_settings(), "api") is False
    assert not sentry_sdk.is_initialized()


def test_errors_with_tracebacks_are_reported_with_scrubbed_context(
    sentry: CapturingTransport,
) -> None:
    log = structlog.get_logger("sia.modules.enrichment.service")
    log.info("all_good")  # below ERROR: never reported
    log.warning("fetch_failed")
    try:
        1 / 0  # noqa: B018
    except ZeroDivisionError:
        log.exception("enrichment_crashed", run_id="r-1", ip_address="203.0.113.7")

    (event,) = flushed(sentry)
    assert event["exception"]["values"][-1]["type"] == "ZeroDivisionError"
    assert event["extra"]["run_id"] == "r-1"
    assert event["extra"]["ip_address"] == "[filtered]"
    assert event["tags"]["component"] == "worker"
    assert event["tags"]["logger"] == "sia.modules.enrichment.service"
    assert event["release"] == "abc"
    frames = event["exception"]["values"][-1]["stacktrace"]["frames"]
    assert frames
    assert all("vars" not in frame for frame in frames)  # no local variables leave the server


def test_errors_without_exceptions_are_reported_as_messages(sentry: CapturingTransport) -> None:
    structlog.get_logger("x").error("brief_store_failed", company_id="c-1", user_email="a@b.c")

    (event,) = flushed(sentry)
    assert event["message"] == "brief_store_failed" or event["logentry"]["message"] == (
        "brief_store_failed"
    )
    assert event["extra"]["company_id"] == "c-1"
    assert event["extra"]["user_email"] == "[filtered]"


def test_request_data_is_stripped() -> None:
    event = {
        "request": {
            "url": "https://sia.example/api/companies",
            "cookies": {"__Host-sia_session": "secret"},
            "data": {"password": "hunter2hunter2"},
            "query_string": "q=acme",
            "headers": {"Cookie": "x", "Authorization": "y", "User-Agent": "Firefox"},
        },
        "user": {"id": "u-1", "ip_address": "203.0.113.7", "email": "a@b.c"},
        "extra": {"session_token": "t", "company_id": "c"},
    }

    scrubbed = scrub_event(event)

    assert scrubbed["request"] == {
        "url": "https://sia.example/api/companies",
        "headers": {"User-Agent": "Firefox"},
    }
    assert scrubbed["user"] == {"id": "u-1"}
    assert scrubbed["extra"] == {"session_token": "[filtered]", "company_id": "c"}
