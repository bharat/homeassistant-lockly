"""Lockly lock slot manager integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.components import mqtt, websocket_api
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import CoreState, Event
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.loader import async_get_loaded_integration

from .const import (
    CONF_LOCK_GROUP_ENTITY,
    CONF_LOCK_GROUP_NAME,
    DOMAIN,
    INTEGRATION_VERSION,
    LOGGER,
    SERVICE_ADD_SLOT,
    SERVICE_APPLY_ALL,
    SERVICE_APPLY_SLOT,
    SERVICE_PUSH_SLOT,
    SERVICE_REMOVE_SLOT,
    SERVICE_UPDATE_SLOT,
    SERVICE_WIPE_SLOTS,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .coordinator import LocklySlotCoordinator
from .data import LocklyData
from .frontend import JSModuleRegistration
from .manager import LocklyManager

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant, ServiceCall

    from .data import LocklyConfigEntry

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
]

SERVICE_SCHEMA_ENTRY = vol.Schema({vol.Required("entry_id"): cv.string})
SERVICE_SCHEMA_SLOT = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
        vol.Required("slot"): vol.Coerce(int),
    }
)
SERVICE_SCHEMA_WIPE = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
        vol.Optional("slots"): vol.Any(
            cv.string, vol.All(cv.ensure_list, [vol.Coerce(int)])
        ),
    }
)
SERVICE_SCHEMA_UPDATE = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
        vol.Required("slot"): vol.Coerce(int),
        vol.Optional("name"): cv.string,
        vol.Optional("pin"): cv.string,
        vol.Optional("enabled"): cv.boolean,
    }
)

ENTRY_NOT_FOUND = "entry_not_found"


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:  # noqa: PLR0915
    """Set up the Lockly integration."""
    hass.data.setdefault(DOMAIN, {})
    skip_frontend = hass.data.get(f"{DOMAIN}_skip_frontend", False)

    @websocket_api.websocket_command(
        {
            vol.Required("type"): f"{DOMAIN}/version",
        }
    )
    @websocket_api.async_response
    async def websocket_get_version(
        _hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict,
    ) -> None:
        """Return the integration version."""
        connection.send_result(msg["id"], {"version": INTEGRATION_VERSION})

    @websocket_api.websocket_command(
        {
            vol.Required("type"): f"{DOMAIN}/config",
            vol.Required("entry_id"): cv.string,
        }
    )
    @websocket_api.async_response
    async def websocket_get_config(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict,
    ) -> None:
        """Return config entry data used by the card."""
        entry_id = msg["entry_id"]
        runtime = hass.data.get(DOMAIN, {}).get(entry_id)
        if runtime is None:
            connection.send_error(msg["id"], ENTRY_NOT_FOUND, "Entry not found")
            return
        entry = runtime.coordinator.config_entry
        data = entry.options or entry.data
        connection.send_result(
            msg["id"],
            {
                "group_entity_id": data.get(CONF_LOCK_GROUP_ENTITY),
                "group_name": data.get(CONF_LOCK_GROUP_NAME),
            },
        )

    websocket_api.async_register_command(hass, websocket_get_version)
    websocket_api.async_register_command(hass, websocket_get_config)

    @websocket_api.websocket_command(
        {
            vol.Required("type"): f"{DOMAIN}/entries",
        }
    )
    @websocket_api.async_response
    async def websocket_list_entries(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict,
    ) -> None:
        """Return Lockly config entries for the card editor."""
        entries = []
        for entry in hass.config_entries.async_entries(DOMAIN):
            data = entry.options or entry.data
            entries.append(
                {
                    "entry_id": entry.entry_id,
                    "title": entry.title,
                    "group_entity_id": data.get(CONF_LOCK_GROUP_ENTITY),
                    "group_name": data.get(CONF_LOCK_GROUP_NAME),
                }
            )
        connection.send_result(msg["id"], entries)

    websocket_api.async_register_command(hass, websocket_list_entries)

    if not skip_frontend:

        async def _register_frontend(_: Event | None = None) -> None:
            registration = JSModuleRegistration(hass)
            await registration.async_register()

        if hass.state is CoreState.running:
            await _register_frontend()
        else:
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _register_frontend)

    async def _get_manager(call: ServiceCall) -> LocklyManager:
        entry_id = call.data["entry_id"]
        runtime = hass.data[DOMAIN].get(entry_id)
        if runtime is None:
            message = ENTRY_NOT_FOUND
            raise ServiceValidationError(message)
        return runtime.manager

    async def _handle_add_slot(call: ServiceCall) -> None:
        manager = await _get_manager(call)
        await manager.add_slot()

    async def _handle_remove_slot(call: ServiceCall) -> None:
        manager = await _get_manager(call)
        await manager.remove_slot(call.data["slot"])

    async def _handle_apply_slot(call: ServiceCall) -> None:
        manager = await _get_manager(call)
        await manager.apply_slot(call.data["slot"])

    async def _handle_push_slot(call: ServiceCall) -> None:
        manager = await _get_manager(call)
        await manager.apply_slot(call.data["slot"])

    async def _handle_apply_all(call: ServiceCall) -> None:
        manager = await _get_manager(call)
        await manager.apply_all()

    async def _handle_update_slot(call: ServiceCall) -> None:
        manager = await _get_manager(call)
        await manager.update_slot(
            call.data["slot"],
            name=call.data.get("name"),
            pin=call.data.get("pin"),
            enabled=call.data.get("enabled"),
        )

    async def _handle_wipe(call: ServiceCall) -> None:
        manager = await _get_manager(call)
        slots = call.data.get("slots")
        if isinstance(slots, str):
            slots = [int(item.strip()) for item in slots.split(",") if item.strip()]
        await manager.wipe_slots(slots)

    hass.services.async_register(
        DOMAIN, SERVICE_ADD_SLOT, _handle_add_slot, schema=SERVICE_SCHEMA_ENTRY
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_SLOT, _handle_remove_slot, schema=SERVICE_SCHEMA_SLOT
    )
    hass.services.async_register(
        DOMAIN, SERVICE_APPLY_SLOT, _handle_apply_slot, schema=SERVICE_SCHEMA_SLOT
    )
    hass.services.async_register(
        DOMAIN, SERVICE_PUSH_SLOT, _handle_push_slot, schema=SERVICE_SCHEMA_SLOT
    )
    hass.services.async_register(
        DOMAIN, SERVICE_APPLY_ALL, _handle_apply_all, schema=SERVICE_SCHEMA_ENTRY
    )
    hass.services.async_register(
        DOMAIN, SERVICE_UPDATE_SLOT, _handle_update_slot, schema=SERVICE_SCHEMA_UPDATE
    )
    hass.services.async_register(
        DOMAIN, SERVICE_WIPE_SLOTS, _handle_wipe, schema=SERVICE_SCHEMA_WIPE
    )

    return True


# https://developers.home-assistant.io/docs/config_entries_index/#setting-up-an-entry
async def async_setup_entry(
    hass: HomeAssistant,
    entry: LocklyConfigEntry,
) -> bool:
    """Set up this integration using UI."""
    store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry.entry_id}")
    coordinator = LocklySlotCoordinator(
        hass=hass, store=store, entry=entry, logger=LOGGER
    )
    manager = LocklyManager(hass=hass, entry=entry, coordinator=coordinator)
    entry.runtime_data = LocklyData(
        coordinator=coordinator,
        manager=manager,
        integration=async_get_loaded_integration(hass, entry.domain),
        subscriptions=[],
    )
    await coordinator.async_load()

    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.domain in {"text", "switch"}:
            registry.async_remove(entity.entity_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    hass.data[DOMAIN][entry.entry_id] = entry.runtime_data

    async def _handle_action_message(msg: mqtt.ReceiveMessage) -> None:
        topic = msg.topic
        payload = msg.payload
        if isinstance(payload, bytes):
            try:
                payload = payload.decode()
            except UnicodeDecodeError:
                payload = payload.decode(errors="replace")
        if not topic.endswith("/action"):
            return
        lock_name = topic[len(manager.mqtt_topic) + 1 : -len("/action")]
        if not lock_name:
            return
        LOGGER.debug("MQTT %s: %s", topic, payload)
        await manager.handle_mqtt_action(lock_name, str(payload))

    unsub: Callable[[], None] = await mqtt.async_subscribe(
        hass,
        f"{manager.mqtt_topic}/+/action",
        _handle_action_message,
    )
    entry.runtime_data.subscriptions.append(unsub)
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: LocklyConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        runtime = hass.data[DOMAIN].get(entry.entry_id)
        if runtime and runtime.subscriptions:
            for unsub in runtime.subscriptions:
                unsub()
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(
    hass: HomeAssistant,
    entry: LocklyConfigEntry,
) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
