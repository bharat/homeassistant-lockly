"""Tests for the Lockly event platform."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from custom_components.lockly.event import LocklyLockEvent
from custom_components.lockly.logbook import EVENT_LOCKLY_LOCK_ACTIVITY

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@pytest.fixture
def entity(hass: HomeAssistant) -> LocklyLockEvent:
    ent = LocklyLockEvent("test-entry-id", "My Lockly", "Front Door")
    ent.hass = hass
    ent.entity_id = "event.lockly_front_door"
    return ent


def test_unique_id(entity: LocklyLockEvent) -> None:
    assert entity.unique_id == "test-entry-id-lock-event-front_door"


def test_device_info(entity: LocklyLockEvent) -> None:
    info = entity.device_info
    assert ("lockly", "test-entry-id") in info["identifiers"]
    assert info["name"] == "My Lockly"


@pytest.mark.asyncio
async def test_fire_action_triggers_event(
    entity: LocklyLockEvent,
) -> None:
    event_data = {
        "user_name": "Bob",
        "slot_id": 2,
        "source": "keypad",
    }
    fired: list[dict] = []
    entity.hass.bus.async_listen(
        EVENT_LOCKLY_LOCK_ACTIVITY,
        lambda event: fired.append(event.data),
    )
    with (
        patch.object(entity, "_trigger_event") as mock_trigger,
        patch.object(entity, "async_write_ha_state"),
    ):
        entity.fire_action("unlock", event_data)

    await entity.hass.async_block_till_done()
    mock_trigger.assert_called_once_with("unlock", event_data)
    assert len(fired) == 1
    assert fired[0]["lock"] == "Front Door"
    assert fired[0]["action"] == "unlock"
    assert fired[0]["user_name"] == "Bob"


def test_fire_action_ignores_unknown_type(
    entity: LocklyLockEvent,
) -> None:
    with (
        patch.object(entity, "_trigger_event") as mock_trigger,
        patch.object(entity, "async_write_ha_state"),
    ):
        entity.fire_action("totally_bogus", {})

    mock_trigger.assert_not_called()
