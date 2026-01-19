"""Text platform for Lockly slots."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.text import TextEntity, TextMode
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
    """Set up Lockly text entities."""
    manager = entry.runtime_data.manager

    def _factory(slot: LocklySlot) -> list[LocklySlotText]:
        return [
            LocklySlotNameText(entry.runtime_data.coordinator, slot.slot),
            LocklySlotPinText(entry.runtime_data.coordinator, slot.slot),
        ]

    manager.register_platform(Platform.TEXT.value, async_add_entities, _factory)


class LocklySlotText(CoordinatorEntity[LocklySlotCoordinator], TextEntity):
    """Base class for Lockly text entities."""

    _attr_mode = TextMode.TEXT

    def __init__(self, coordinator: LocklySlotCoordinator, slot_id: int) -> None:
        """Initialize the text entity."""
        super().__init__(coordinator)
        self._slot_id = slot_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name=coordinator.config_entry.title,
        )

    @property
    def slot(self) -> LocklySlot | None:
        """Return the current slot."""
        return self.coordinator.data.get(self._slot_id)

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra state attributes."""
        slot = self.slot
        manager = self.coordinator.config_entry.runtime_data.manager
        return {
            "lockly_entry_id": self.coordinator.config_entry.entry_id,
            "lockly_slot": self._slot_id,
            "lockly_group_entity": manager.group_entity_id,
            "lockly_type": self.lockly_type,
            "busy": getattr(slot, "busy", False) if slot else False,
        }


class LocklySlotNameText(LocklySlotText):
    """Text entity for the slot name."""

    lockly_type = "name"
    _attr_icon = "mdi:account"
    _attr_native_max = 32

    def __init__(self, coordinator: LocklySlotCoordinator, slot_id: int) -> None:
        """Initialize name entity."""
        super().__init__(coordinator, slot_id)
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}-slot-{slot_id}-name"
        )
        self._attr_name = f"Slot {slot_id} Name"

    @property
    def native_value(self) -> str | None:
        """Return the current slot name."""
        slot = self.slot
        return slot.name if slot else None

    async def async_set_value(self, value: str) -> None:
        """Set the slot name."""
        await self.coordinator.config_entry.runtime_data.manager.update_slot(
            self._slot_id, name=value
        )


class LocklySlotPinText(LocklySlotText):
    """Text entity for the slot PIN."""

    lockly_type = "pin"
    _attr_icon = "mdi:form-textbox-password"
    _attr_native_max = 8

    def __init__(self, coordinator: LocklySlotCoordinator, slot_id: int) -> None:
        """Initialize PIN entity."""
        super().__init__(coordinator, slot_id)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}-slot-{slot_id}-pin"
        self._attr_name = f"Slot {slot_id} PIN"

    @property
    def native_value(self) -> str | None:
        """Return the current slot PIN."""
        slot = self.slot
        return slot.pin if slot else None

    async def async_set_value(self, value: str) -> None:
        """Set the slot PIN."""
        await self.coordinator.config_entry.runtime_data.manager.update_slot(
            self._slot_id, pin=value
        )
