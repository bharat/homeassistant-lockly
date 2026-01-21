"""Tests for Lockly services."""

# ruff: noqa: S101

import asyncio
import json
import time
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.lockly.const import (
    CONF_ENDPOINT,
    CONF_MAX_SLOTS,
    CONF_MQTT_TOPIC,
    DEFAULT_ENDPOINT,
    DEFAULT_MAX_SLOTS,
    DEFAULT_MQTT_TOPIC,
    DOMAIN,
)


async def _setup_entry(
    hass: HomeAssistant, enable_custom_integrations: Any
) -> MockConfigEntry:
    _ = enable_custom_integrations
    hass.data["lockly_skip_frontend"] = True
    hass.data["lockly_skip_timeout"] = True
    hass.data["lockly_skip_mqtt"] = True
    hass.data["lockly_skip_worker"] = True
    async_mock_service(hass, "mqtt", "publish")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Lockly",
        data={
            CONF_NAME: "Lockly",
            CONF_MAX_SLOTS: DEFAULT_MAX_SLOTS,
            CONF_MQTT_TOPIC: DEFAULT_MQTT_TOPIC,
            CONF_ENDPOINT: DEFAULT_ENDPOINT,
        },
    )
    entry.add_to_hass(hass)
    hass.states.async_set(
        "lock.garden_upper_lock",
        "locked",
        {"friendly_name": "Garden Upper Lock"},
    )
    await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def _wait_for_mqtt_calls(mqtt_calls: list, expected: int) -> None:
    """Wait for MQTT publish calls from async workers."""
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if len(mqtt_calls) >= expected:
            return
        await asyncio.sleep(0)
    pytest.fail("Timed out waiting for MQTT publish calls")


@pytest.mark.enable_socket
async def test_apply_slot_publishes_mqtt(
    hass: HomeAssistant, enable_custom_integrations: Any
) -> None:
    """Test applying a slot publishes MQTT commands."""
    entry = await _setup_entry(hass, enable_custom_integrations)
    mqtt_calls = async_mock_service(hass, "mqtt", "publish")

    await hass.services.async_call(
        DOMAIN, "add_slot", {"entry_id": entry.entry_id}, blocking=True
    )
    manager = hass.data[DOMAIN][entry.entry_id].manager
    await manager.update_slot(1, name="Guest", pin="1234", enabled=True)

    await hass.services.async_call(
        DOMAIN,
        "apply_slot",
        {
            "entry_id": entry.entry_id,
            "slot": 1,
            "lock_entities": ["lock.garden_upper_lock"],
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    await _wait_for_mqtt_calls(mqtt_calls, 1)
    assert len(mqtt_calls) == 1
    payload = json.loads(mqtt_calls[0].data["payload"])
    assert mqtt_calls[0].data["topic"] == "zigbee2mqtt/Garden Upper Lock/set"
    assert payload["pin_code"]["user"] == 1
    assert payload["pin_code"]["user_type"] == "unrestricted"
    assert payload["pin_code"]["user_enabled"] is True
    assert payload["pin_code"]["pin_code"] == "1234"


@pytest.mark.enable_socket
async def test_apply_slot_rejects_invalid_pin(
    hass: HomeAssistant, enable_custom_integrations: Any
) -> None:
    """Test applying invalid PIN raises."""
    entry = await _setup_entry(hass, enable_custom_integrations)
    await hass.services.async_call(
        DOMAIN, "add_slot", {"entry_id": entry.entry_id}, blocking=True
    )
    manager = hass.data[DOMAIN][entry.entry_id].manager
    with pytest.raises(ServiceValidationError):
        await manager.update_slot(1, name="Guest", pin="12", enabled=True)

    await hass.services.async_call(
        DOMAIN,
        "apply_slot",
        {
            "entry_id": entry.entry_id,
            "slot": 1,
            "lock_entities": ["lock.garden_upper_lock"],
        },
        blocking=True,
    )
    await hass.async_block_till_done()


@pytest.mark.enable_socket
async def test_apply_slot_dry_run_skips_mqtt(
    hass: HomeAssistant, enable_custom_integrations: Any
) -> None:
    """Test dry_run apply does not publish MQTT."""
    entry = await _setup_entry(hass, enable_custom_integrations)
    mqtt_calls = async_mock_service(hass, "mqtt", "publish")

    await hass.services.async_call(
        DOMAIN, "add_slot", {"entry_id": entry.entry_id}, blocking=True
    )
    manager = hass.data[DOMAIN][entry.entry_id].manager
    await manager.update_slot(1, name="Guest", pin="1234", enabled=True)

    await hass.services.async_call(
        DOMAIN,
        "apply_slot",
        {
            "entry_id": entry.entry_id,
            "slot": 1,
            "lock_entities": ["lock.garden_upper_lock"],
            "dry_run": True,
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    assert len(mqtt_calls) == 0


@pytest.mark.enable_socket
async def test_apply_all_skips_disabled(
    hass: HomeAssistant, enable_custom_integrations: Any
) -> None:
    """Test apply_all only sends enabled slots."""
    entry = await _setup_entry(hass, enable_custom_integrations)
    mqtt_calls = async_mock_service(hass, "mqtt", "publish")

    await hass.services.async_call(
        DOMAIN, "add_slot", {"entry_id": entry.entry_id}, blocking=True
    )
    await hass.services.async_call(
        DOMAIN, "add_slot", {"entry_id": entry.entry_id}, blocking=True
    )
    manager = hass.data[DOMAIN][entry.entry_id].manager
    await manager.update_slot(1, name="Guest", pin="1234", enabled=True)
    await manager.update_slot(2, name="Disabled", pin="9999", enabled=False)

    await hass.services.async_call(
        DOMAIN,
        "apply_all",
        {"entry_id": entry.entry_id, "lock_entities": ["lock.garden_upper_lock"]},
        blocking=True,
    )
    await hass.async_block_till_done()
    await _wait_for_mqtt_calls(mqtt_calls, 1)
    assert len(mqtt_calls) == 1
    payload = json.loads(mqtt_calls[0].data["payload"])
    assert payload["pin_code"]["user"] == 1


@pytest.mark.enable_socket
async def test_remove_slot_clears_pin(
    hass: HomeAssistant, enable_custom_integrations: Any
) -> None:
    """Test removing a slot clears the PIN on the lock."""
    entry = await _setup_entry(hass, enable_custom_integrations)
    mqtt_calls = async_mock_service(hass, "mqtt", "publish")

    await hass.services.async_call(
        DOMAIN, "add_slot", {"entry_id": entry.entry_id}, blocking=True
    )
    manager = hass.data[DOMAIN][entry.entry_id].manager
    await manager.update_slot(1, name="Guest", pin="1234", enabled=True)

    await hass.services.async_call(
        DOMAIN,
        "remove_slot",
        {
            "entry_id": entry.entry_id,
            "slot": 1,
            "lock_entities": ["lock.garden_upper_lock"],
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    await _wait_for_mqtt_calls(mqtt_calls, 1)
    assert len(mqtt_calls) == 1
    payload = json.loads(mqtt_calls[0].data["payload"])
    assert payload["pin_code"]["user"] == 1
    assert payload["pin_code"]["user_enabled"] is False
    assert payload["pin_code"]["pin_code"] is None


@pytest.mark.enable_socket
async def test_wipe_slots_subset(
    hass: HomeAssistant, enable_custom_integrations: Any
) -> None:
    """Test wiping a subset clears only targeted slots."""
    entry = await _setup_entry(hass, enable_custom_integrations)
    mqtt_calls = async_mock_service(hass, "mqtt", "publish")

    await hass.services.async_call(
        DOMAIN, "add_slot", {"entry_id": entry.entry_id}, blocking=True
    )
    await hass.services.async_call(
        DOMAIN, "add_slot", {"entry_id": entry.entry_id}, blocking=True
    )
    manager = hass.data[DOMAIN][entry.entry_id].manager
    await manager.update_slot(1, name="Guest1", pin="1111", enabled=True)
    await manager.update_slot(2, name="Guest2", pin="2222", enabled=True)

    await hass.services.async_call(
        DOMAIN,
        "wipe_slots",
        {
            "entry_id": entry.entry_id,
            "slots": [1],
            "lock_entities": ["lock.garden_upper_lock"],
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    await _wait_for_mqtt_calls(mqtt_calls, 1)
    assert len(mqtt_calls) == 1
    payload = json.loads(mqtt_calls[0].data["payload"])
    assert payload["pin_code"]["user"] == 1
    assert payload["pin_code"]["user_enabled"] is False


@pytest.mark.enable_socket
async def test_group_lock_entities_expand(
    hass: HomeAssistant, enable_custom_integrations: Any
) -> None:
    """Test lock group entity expands to lock members."""
    entry = await _setup_entry(hass, enable_custom_integrations)
    mqtt_calls = async_mock_service(hass, "mqtt", "publish")
    hass.states.async_set(
        "group.test_locks",
        "on",
        {"entity_id": ["lock.garden_upper_lock"]},
    )

    await hass.services.async_call(
        DOMAIN, "add_slot", {"entry_id": entry.entry_id}, blocking=True
    )
    manager = hass.data[DOMAIN][entry.entry_id].manager
    await manager.update_slot(1, name="Guest", pin="1234", enabled=True)

    await hass.services.async_call(
        DOMAIN,
        "apply_slot",
        {
            "entry_id": entry.entry_id,
            "slot": 1,
            "lock_entities": ["group.test_locks"],
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    await _wait_for_mqtt_calls(mqtt_calls, 1)
    assert len(mqtt_calls) == 1
    assert mqtt_calls[0].data["topic"] == "zigbee2mqtt/Garden Upper Lock/set"


@pytest.mark.enable_socket
async def test_slot_status_attribute(
    hass: HomeAssistant, enable_custom_integrations: Any
) -> None:
    """Test slot status attribute is exposed."""
    entry = await _setup_entry(hass, enable_custom_integrations)
    await hass.services.async_call(
        DOMAIN, "add_slot", {"entry_id": entry.entry_id}, blocking=True
    )
    manager = hass.data[DOMAIN][entry.entry_id].manager
    await manager.update_slot(1, status="queued")
    await hass.async_block_till_done()
    slot_states = [
        state
        for state in hass.states.async_all()
        if state.attributes.get("lockly_slot") == 1
    ]
    assert slot_states
    assert slot_states[0].attributes.get("status") == "queued"


@pytest.mark.enable_socket
async def test_export_slots_returns_payload(
    hass: HomeAssistant, enable_custom_integrations: Any
) -> None:
    """Test export slots returns serialized data."""
    entry = await _setup_entry(hass, enable_custom_integrations)
    manager = hass.data[DOMAIN][entry.entry_id].manager
    await manager.add_slot()
    await manager.update_slot(1, name="Guest", pin="1234", enabled=True)

    response = await hass.services.async_call(
        DOMAIN,
        "export_slots",
        {"entry_id": entry.entry_id},
        blocking=True,
        return_response=True,
    )
    slots = response.get("slots", [])
    assert slots == [
        {
            "slot": 1,
            "name": "Guest",
            "pin": "",
            "enabled": True,
        }
    ]


@pytest.mark.enable_socket
async def test_import_slots_replace(
    hass: HomeAssistant, enable_custom_integrations: Any
) -> None:
    """Test importing slots replaces existing data."""
    entry = await _setup_entry(hass, enable_custom_integrations)
    manager = hass.data[DOMAIN][entry.entry_id].manager
    await manager.add_slot()
    await manager.update_slot(1, name="Old", pin="9999", enabled=True)

    payload = json.dumps(
        {
            "slots": [
                {"slot": 2, "name": "New", "pin": "1234", "enabled": True},
            ]
        }
    )
    await hass.services.async_call(
        DOMAIN,
        "import_slots",
        {"entry_id": entry.entry_id, "payload": payload},
        blocking=True,
    )
    exported = manager.export_slots(include_pins=True)
    assert exported == [
        {
            "slot": 2,
            "name": "New",
            "pin": "1234",
            "enabled": True,
        }
    ]
