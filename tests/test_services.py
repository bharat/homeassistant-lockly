"""Tests for Lockly services."""

# ruff: noqa: S101

import json

import pytest
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
    CONF_LOCK_NAMES,
    CONF_MAX_SLOTS,
    CONF_MQTT_TOPIC,
    DEFAULT_ENDPOINT,
    DEFAULT_MAX_SLOTS,
    DEFAULT_MQTT_TOPIC,
    DOMAIN,
)


async def _setup_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Lockly",
        data={
            CONF_NAME: "Lockly",
            CONF_LOCK_NAMES: ["Front Door"],
            CONF_MAX_SLOTS: DEFAULT_MAX_SLOTS,
            CONF_MQTT_TOPIC: DEFAULT_MQTT_TOPIC,
            CONF_ENDPOINT: DEFAULT_ENDPOINT,
        },
    )
    entry.add_to_hass(hass)
    await async_setup_component(hass, DOMAIN, {})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_apply_slot_publishes_mqtt(hass: HomeAssistant) -> None:
    """Test applying a slot publishes MQTT commands."""
    entry = await _setup_entry(hass)
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
    assert payload["command"] == "setPinCode"
    assert payload["payload"]["userid"] == 1
    assert payload["payload"]["pincodevalue"] == "1234"


async def test_apply_slot_rejects_invalid_pin(hass: HomeAssistant) -> None:
    """Test applying invalid PIN raises."""
    entry = await _setup_entry(hass)
    await hass.services.async_call(
        DOMAIN, "add_slot", {"entry_id": entry.entry_id}, blocking=True
    )
    manager = hass.data[DOMAIN][entry.entry_id].manager
    await manager.update_slot(1, name="Guest", pin="12", enabled=True)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "apply_slot", {"entry_id": entry.entry_id, "slot": 1}, blocking=True
        )
