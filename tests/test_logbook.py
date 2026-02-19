"""Tests for Lockly logbook event descriptions."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.core import Event, HomeAssistant

from custom_components.lockly.logbook import (
    EVENT_LOCKLY_LOCK_ACTIVITY,
    async_describe_events,
)


@pytest.fixture
def describe() -> dict[str, object]:
    """Register logbook descriptions and return callbacks."""
    registered: dict[str, object] = {}

    def fake_describe(_domain: str, event_name: str, cb: object) -> None:
        registered[event_name] = cb

    hass = MagicMock(spec=HomeAssistant)
    async_describe_events(hass, fake_describe)
    return registered


def _make_event(data: dict) -> Event:
    return Event(EVENT_LOCKLY_LOCK_ACTIVITY, data)


def test_basic_unlock(describe: dict) -> None:
    cb = describe[EVENT_LOCKLY_LOCK_ACTIVITY]
    result = cb(
        _make_event(
            {
                "lock": "Front Door",
                "action": "unlock",
                "user_name": "Alice",
                "source": "keypad",
            }
        )
    )
    assert result["name"] == "Front Door"
    assert "unlocked" in result["message"]
    assert "Alice" in result["message"]
    assert "keypad" in result["message"]


def test_lock_no_user(describe: dict) -> None:
    cb = describe[EVENT_LOCKLY_LOCK_ACTIVITY]
    result = cb(_make_event({"lock": "Back Door", "action": "lock"}))
    assert result["name"] == "Back Door"
    assert "locked" in result["message"]
    assert "by" not in result["message"]


def test_slot_fallback(describe: dict) -> None:
    cb = describe[EVENT_LOCKLY_LOCK_ACTIVITY]
    result = cb(
        _make_event(
            {
                "lock": "Garage",
                "action": "unlock",
                "slot_id": 3,
            }
        )
    )
    assert "Slot 3" in result["message"]


def test_unknown_action(describe: dict) -> None:
    cb = describe[EVENT_LOCKLY_LOCK_ACTIVITY]
    result = cb(
        _make_event(
            {
                "lock": "Side Door",
                "action": "non_access_user_operational_event",
            }
        )
    )
    assert "non access user operational event" in result["message"]


def test_rfid_source(describe: dict) -> None:
    cb = describe[EVENT_LOCKLY_LOCK_ACTIVITY]
    result = cb(
        _make_event(
            {
                "lock": "Front Door",
                "action": "unlock",
                "source": "rfid",
            }
        )
    )
    assert "RFID" in result["message"]
