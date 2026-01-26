"""Lockly lock slot manager integration."""

from __future__ import annotations

import json
from functools import partial
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.components import mqtt, websocket_api
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import CoreState, Event, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.loader import async_get_loaded_integration

from .const import (
    DOMAIN,
    INTEGRATION_VERSION,
    LOGGER,
    SERVICE_ADD_SLOT,
    SERVICE_APPLY_ALL,
    SERVICE_APPLY_SLOT,
    SERVICE_EXPORT_SLOTS,
    SERVICE_IMPORT_SLOTS,
    SERVICE_PUSH_SLOT,
    SERVICE_REMOVE_SLOT,
    SERVICE_UPDATE_SLOT,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .coordinator import LocklySlotCoordinator
from .data import LocklyData
from .frontend import JSModuleRegistration
from .manager import ApplySlotOptions, LocklyManager

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant, ServiceCall

    from .data import LocklyConfigEntry

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
]

SERVICE_SCHEMA_ENTRY = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
        vol.Optional("lock_entities"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("dry_run"): cv.boolean,
    }
)
SERVICE_SCHEMA_SLOT = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
        vol.Required("slot"): vol.Coerce(int),
        vol.Optional("lock_entities"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("dry_run"): cv.boolean,
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
SERVICE_SCHEMA_EXPORT = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
        vol.Optional("include_pins"): cv.boolean,
    }
)
SERVICE_SCHEMA_IMPORT = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
        vol.Required("payload"): cv.string,
        vol.Optional("replace"): cv.boolean,
    }
)

ENTRY_NOT_FOUND = "entry_not_found"


async def _register_websocket_handlers(hass: HomeAssistant) -> None:
    """Register websocket commands."""

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
        connection.send_result(
            msg["id"],
            {
                "title": entry.title,
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
        entries = [
            {
                "entry_id": entry.entry_id,
                "title": entry.title,
            }
            for entry in hass.config_entries.async_entries(DOMAIN)
        ]
        connection.send_result(msg["id"], entries)

    websocket_api.async_register_command(hass, websocket_list_entries)


async def _register_frontend(hass: HomeAssistant) -> None:
    """Register frontend resources when enabled."""
    if hass.data.get(f"{DOMAIN}_skip_frontend", False):
        return

    async def _register(_: Event | None = None) -> None:
        registration = JSModuleRegistration(hass)
        await registration.async_register()

    if hass.state is CoreState.running:
        await _register()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _register)


async def _get_manager(hass: HomeAssistant, call: ServiceCall) -> LocklyManager:
    entry_id = call.data["entry_id"]
    runtime = hass.data[DOMAIN].get(entry_id)
    if runtime is None:
        message = ENTRY_NOT_FOUND
        raise ServiceValidationError(message)
    return runtime.manager


async def _handle_add_slot(hass: HomeAssistant, call: ServiceCall) -> None:
    manager = await _get_manager(hass, call)
    await manager.add_slot()


async def _handle_remove_slot(hass: HomeAssistant, call: ServiceCall) -> None:
    manager = await _get_manager(hass, call)
    await manager.remove_slot(
        call.data["slot"],
        lock_entities=call.data.get("lock_entities"),
        dry_run=call.data.get("dry_run", False),
    )


async def _handle_apply_slot(hass: HomeAssistant, call: ServiceCall) -> None:
    manager = await _get_manager(hass, call)
    await manager.apply_slot(
        call.data["slot"],
        ApplySlotOptions(
            lock_entities=call.data.get("lock_entities"),
            dry_run=call.data.get("dry_run", False),
            wait_for_completion=False,
        ),
    )


async def _handle_push_slot(hass: HomeAssistant, call: ServiceCall) -> None:
    manager = await _get_manager(hass, call)
    await manager.apply_slot(
        call.data["slot"],
        ApplySlotOptions(
            lock_entities=call.data.get("lock_entities"),
            dry_run=call.data.get("dry_run", False),
            wait_for_completion=False,
        ),
    )


async def _handle_apply_all(hass: HomeAssistant, call: ServiceCall) -> None:
    manager = await _get_manager(hass, call)
    await manager.apply_all(
        lock_entities=call.data.get("lock_entities"),
        dry_run=call.data.get("dry_run", False),
    )


async def _handle_update_slot(hass: HomeAssistant, call: ServiceCall) -> None:
    manager = await _get_manager(hass, call)
    await manager.update_slot(
        call.data["slot"],
        name=call.data.get("name"),
        pin=call.data.get("pin"),
        enabled=call.data.get("enabled"),
    )


async def _handle_export_slots(hass: HomeAssistant, call: ServiceCall) -> dict:
    manager = await _get_manager(hass, call)
    include_pins = call.data.get("include_pins", False)
    slots = manager.export_slots(include_pins=include_pins)
    return {"slots": slots}


async def _handle_import_slots(hass: HomeAssistant, call: ServiceCall) -> None:
    manager = await _get_manager(hass, call)
    payload = call.data.get("payload", "")
    if not payload:
        message = "invalid_payload"
        raise ServiceValidationError(message)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as err:
        message = "invalid_payload"
        raise ServiceValidationError(message) from err
    slots = data.get("slots", []) if isinstance(data, dict) else data
    if not isinstance(slots, list):
        message = "invalid_payload"
        raise ServiceValidationError(message)
    await manager.import_slots(slots, replace=call.data.get("replace", True))


def _register_services(hass: HomeAssistant) -> None:
    """Register services for Lockly."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_SLOT,
        partial(_handle_add_slot, hass),
        schema=SERVICE_SCHEMA_ENTRY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_SLOT,
        partial(_handle_remove_slot, hass),
        schema=SERVICE_SCHEMA_SLOT,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_APPLY_SLOT,
        partial(_handle_apply_slot, hass),
        schema=SERVICE_SCHEMA_SLOT,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PUSH_SLOT,
        partial(_handle_push_slot, hass),
        schema=SERVICE_SCHEMA_SLOT,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_APPLY_ALL,
        partial(_handle_apply_all, hass),
        schema=SERVICE_SCHEMA_ENTRY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_SLOT,
        partial(_handle_update_slot, hass),
        schema=SERVICE_SCHEMA_UPDATE,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT_SLOTS,
        partial(_handle_export_slots, hass),
        schema=SERVICE_SCHEMA_EXPORT,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_SLOTS,
        partial(_handle_import_slots, hass),
        schema=SERVICE_SCHEMA_IMPORT,
    )


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    """Set up the Lockly integration."""
    hass.data.setdefault(DOMAIN, {})
    await _register_websocket_handlers(hass)
    await _register_frontend(hass)
    _register_services(hass)
    return True


async def _setup_entry_runtime(
    hass: HomeAssistant,
    entry: LocklyConfigEntry,
) -> LocklyManager:
    """Create runtime data for a config entry."""
    store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry.entry_id}")
    coordinator = LocklySlotCoordinator(
        hass=hass, store=store, entry=entry, logger=LOGGER
    )
    manager = LocklyManager(hass=hass, entry=entry, coordinator=coordinator)
    manager.register_stop_listener()
    entry.runtime_data = LocklyData(
        coordinator=coordinator,
        manager=manager,
        integration=async_get_loaded_integration(hass, entry.domain),
        subscriptions=[],
    )
    await coordinator.async_load()
    return manager


def _cleanup_legacy_entities(hass: HomeAssistant, entry: LocklyConfigEntry) -> None:
    """Remove legacy text/switch entities from the registry."""
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.domain in {"text", "switch"}:
            registry.async_remove(entity.entity_id)


async def _subscribe_mqtt(
    hass: HomeAssistant,
    entry: LocklyConfigEntry,
    manager: LocklyManager,
) -> None:
    """Subscribe to MQTT updates for a lockly entry."""
    if hass.data.get(f"{DOMAIN}_skip_mqtt", False):
        return

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

    async def _handle_state_action(msg: mqtt.ReceiveMessage) -> None:
        topic = msg.topic
        if topic.endswith("/action"):
            return
        payload = msg.payload
        if isinstance(payload, bytes):
            try:
                payload = payload.decode()
            except UnicodeDecodeError:
                payload = payload.decode(errors="replace")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return
        if not isinstance(payload, dict):
            return
        lock_name = topic[len(manager.mqtt_topic) + 1 :]
        if not lock_name:
            return
        action = payload.get("action")
        if action:
            action_user = payload.get("action_user")
            if isinstance(action_user, str) and action_user.isdigit():
                action_user = int(action_user)
            if not isinstance(action_user, int):
                action_user = None
            LOGGER.debug("MQTT %s action: %s", topic, action)
            await manager.handle_mqtt_action(
                lock_name, str(action), action_user=action_user
            )
            return
        await manager.handle_mqtt_state(lock_name, payload)

    unsub_action: Callable[[], None] = await mqtt.async_subscribe(
        hass,
        f"{manager.mqtt_topic}/+/action",
        _handle_action_message,
    )
    unsub_state: Callable[[], None] = await mqtt.async_subscribe(
        hass,
        f"{manager.mqtt_topic}/+",
        _handle_state_action,
    )
    entry.runtime_data.subscriptions.extend([unsub_action, unsub_state])


# https://developers.home-assistant.io/docs/config_entries_index/#setting-up-an-entry
async def async_setup_entry(
    hass: HomeAssistant,
    entry: LocklyConfigEntry,
) -> bool:
    """Set up this integration using UI."""
    manager = await _setup_entry_runtime(hass, entry)
    _cleanup_legacy_entities(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    hass.data[DOMAIN][entry.entry_id] = entry.runtime_data
    await _subscribe_mqtt(hass, entry, manager)
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
        if runtime:
            await runtime.manager.async_stop(remove_listeners=True)
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(
    hass: HomeAssistant,
    entry: LocklyConfigEntry,
) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
