"""Tests for Lockly config flow."""

# ruff: noqa: S101

from typing import Any

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant

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


async def test_config_flow_user(
    hass: HomeAssistant, enable_custom_integrations: Any
) -> None:
    """Test the config flow user step."""
    _ = enable_custom_integrations
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "form"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Lockly",
            CONF_LOCK_NAMES: "Front Door, Garage",
            CONF_MAX_SLOTS: DEFAULT_MAX_SLOTS,
            CONF_MQTT_TOPIC: DEFAULT_MQTT_TOPIC,
            CONF_ENDPOINT: DEFAULT_ENDPOINT,
        },
    )
    assert result["type"] == "create_entry"
    data = result["data"]
    assert data[CONF_LOCK_NAMES] == ["Front Door", "Garage"]
    assert data[CONF_MAX_SLOTS] == DEFAULT_MAX_SLOTS
    assert data[CONF_MQTT_TOPIC] == DEFAULT_MQTT_TOPIC
    assert data[CONF_ENDPOINT] == DEFAULT_ENDPOINT
