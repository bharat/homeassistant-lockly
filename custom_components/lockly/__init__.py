"""Lockly lock slot manager integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.const import Platform
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.loader import async_get_loaded_integration

from .const import (
    DOMAIN,
    LOGGER,
    SERVICE_ADD_SLOT,
    SERVICE_APPLY_ALL,
    SERVICE_APPLY_SLOT,
    SERVICE_REMOVE_SLOT,
    SERVICE_WIPE_SLOTS,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .coordinator import LocklySlotCoordinator
from .data import LocklyData
from .manager import LocklyManager

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall

    from .data import LocklyConfigEntry

PLATFORMS: list[Platform] = [
    Platform.TEXT,
    Platform.SWITCH,
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

ENTRY_NOT_FOUND = "entry_not_found"


async def async_setup(hass: HomeAssistant) -> bool:
    """Set up the Lockly integration."""
    hass.data.setdefault(DOMAIN, {})

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

    async def _handle_apply_all(call: ServiceCall) -> None:
        manager = await _get_manager(call)
        await manager.apply_all()

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
        DOMAIN, SERVICE_APPLY_ALL, _handle_apply_all, schema=SERVICE_SCHEMA_ENTRY
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
    )
    await coordinator.async_load()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    hass.data[DOMAIN][entry.entry_id] = entry.runtime_data
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: LocklyConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(
    hass: HomeAssistant,
    entry: LocklyConfigEntry,
) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
