"""Tests for Lockly config flow."""

# ruff: noqa: S101

from typing import Any

import pytest
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lockly.const import (
    CONF_ENDPOINT,
    CONF_MAX_SLOTS,
    CONF_MQTT_TOPIC,
    DEFAULT_ENDPOINT,
    DEFAULT_MAX_SLOTS,
    DEFAULT_MQTT_TOPIC,
    DOMAIN,
)


@pytest.mark.enable_socket
async def test_config_flow_user(
    hass: HomeAssistant, enable_custom_integrations: Any
) -> None:
    """Test the config flow user step."""
    _ = enable_custom_integrations
    hass.data["lockly_skip_frontend"] = True

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "form"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Lockly",
            CONF_MAX_SLOTS: DEFAULT_MAX_SLOTS,
            CONF_MQTT_TOPIC: DEFAULT_MQTT_TOPIC,
            CONF_ENDPOINT: DEFAULT_ENDPOINT,
        },
    )
    assert result["type"] == "create_entry"
    data = result["data"]
    assert data[CONF_MAX_SLOTS] == DEFAULT_MAX_SLOTS
    assert data[CONF_MQTT_TOPIC] == DEFAULT_MQTT_TOPIC
    assert data[CONF_ENDPOINT] == DEFAULT_ENDPOINT


@pytest.mark.enable_socket
async def test_options_flow_updates_settings(
    hass: HomeAssistant, enable_custom_integrations: Any
) -> None:
    """Test options flow updates integration settings."""
    _ = enable_custom_integrations
    hass.data["lockly_skip_frontend"] = True
    updated_slots = 10
    updated_topic = "zigbee2mqtt_test"
    updated_endpoint = 2
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

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_MAX_SLOTS: updated_slots,
            CONF_MQTT_TOPIC: updated_topic,
            CONF_ENDPOINT: updated_endpoint,
        },
    )
    assert result["type"] == "create_entry"
    assert entry.options[CONF_MAX_SLOTS] == updated_slots
    assert entry.options[CONF_MQTT_TOPIC] == updated_topic
    assert entry.options[CONF_ENDPOINT] == updated_endpoint
