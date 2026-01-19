"""Tests for Lockly services."""

# ruff: noqa: S101

import json
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
    CONF_LOCK_GROUP_ENTITY,
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
    async_mock_service(hass, "mqtt", "publish")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Lockly",
        data={
            CONF_NAME: "Lockly",
            CONF_LOCK_GROUP_ENTITY: "group.lockly_locks",
            CONF_MAX_SLOTS: DEFAULT_MAX_SLOTS,
            CONF_MQTT_TOPIC: DEFAULT_MQTT_TOPIC,
            CONF_ENDPOINT: DEFAULT_ENDPOINT,
        },
    )
    entry.add_to_hass(hass)
    hass.states.async_set(
        "group.lockly_locks",
        "on",
        {"entity_id": ["lock.garden_upper_lock"]},
    )
    hass.states.async_set(
        "lock.garden_upper_lock",
        "locked",
        {"friendly_name": "Garden Upper Lock"},
    )
    await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


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
        DOMAIN, "apply_slot", {"entry_id": entry.entry_id, "slot": 1}, blocking=True
    )
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
        DOMAIN, "apply_slot", {"entry_id": entry.entry_id, "slot": 1}, blocking=True
    )
