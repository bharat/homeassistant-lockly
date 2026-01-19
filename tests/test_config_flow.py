"""Tests for Lockly config flow."""

# ruff: noqa: S101

from typing import Any

import pytest
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant

from custom_components.lockly.const import (
    CONF_ENDPOINT,
    CONF_LOCK_ENTITIES,
    CONF_LOCK_GROUP_ENTITY,
    CONF_LOCK_GROUP_NAME,
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

    async def _noop_service(call) -> None:
        _ = call

    hass.services.async_register("group", "create", _noop_service)
    hass.services.async_register("group", "set", _noop_service)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "form"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Lockly",
            CONF_LOCK_GROUP_NAME: "Lockly Locks",
            CONF_LOCK_ENTITIES: ["lock.front_door", "lock.garage"],
            CONF_MAX_SLOTS: DEFAULT_MAX_SLOTS,
            CONF_MQTT_TOPIC: DEFAULT_MQTT_TOPIC,
            CONF_ENDPOINT: DEFAULT_ENDPOINT,
        },
    )
    assert result["type"] == "create_entry"
    data = result["data"]
    assert data[CONF_LOCK_GROUP_NAME] == "Lockly Locks"
    assert data[CONF_LOCK_GROUP_ENTITY] == "group.lockly_locks"
    assert data[CONF_MAX_SLOTS] == DEFAULT_MAX_SLOTS
    assert data[CONF_MQTT_TOPIC] == DEFAULT_MQTT_TOPIC
    assert data[CONF_ENDPOINT] == DEFAULT_ENDPOINT
