"""Sensor platform for Lockly slots."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import Platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import LocklySlot, LocklySlotCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .data import LocklyConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: LocklyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Lockly slot sensor entities."""
    manager = entry.runtime_data.manager

    def _factory(slot: LocklySlot) -> list[LocklySlotSensor]:
        return [LocklySlotSensor(entry.runtime_data.coordinator, slot.slot)]

    manager.register_platform(Platform.SENSOR.value, async_add_entities, _factory)


class LocklySlotSensor(CoordinatorEntity[LocklySlotCoordinator], SensorEntity):
    """Sensor entity representing a lock slot."""

    _attr_icon = "mdi:lock"

    def __init__(self, coordinator: LocklySlotCoordinator, slot_id: int) -> None:
        """Initialize the slot sensor."""
        super().__init__(coordinator)
        self._slot_id = slot_id
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}-slot-{slot_id}"
        self._attr_name = f"Lockly Slot {slot_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name=coordinator.config_entry.title,
        )

    @property
    def slot(self) -> LocklySlot | None:
        """Return the current slot."""
        return self.coordinator.data.get(self._slot_id)

    @property
    def native_value(self) -> str | None:
        """Return the slot status."""
        slot = self.slot
        if not slot:
            return None
        if slot.enabled:
            return "enabled"
        if slot.name or slot.pin:
            return "disabled"
        return "empty"

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra state attributes."""
        slot = self.slot
        manager = self.coordinator.config_entry.runtime_data.manager
        return {
            "lockly_entry_id": self.coordinator.config_entry.entry_id,
            "lockly_slot": self._slot_id,
            "lockly_group_entity": manager.group_entity_id,
            "name": slot.name if slot else "",
            "pin": slot.pin if slot else "",
            "enabled": bool(slot.enabled) if slot else False,
            "busy": getattr(slot, "busy", False) if slot else False,
            "last_response": getattr(slot, "last_response", {}) if slot else {},
            "last_response_ts": getattr(slot, "last_response_ts", None)
            if slot
            else None,
        }
