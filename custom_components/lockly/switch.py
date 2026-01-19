"""Switch platform for Lockly slots."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import Platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import LocklySlot, LocklySlotCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .data import LocklyConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001 Unused function argument: `hass`
    entry: LocklyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switch platform."""
    manager = entry.runtime_data.manager

    def _factory(slot: LocklySlot) -> list[LocklySlotEnabledSwitch]:
        return [LocklySlotEnabledSwitch(entry.runtime_data.coordinator, slot.slot)]

    manager.register_platform(Platform.SWITCH.value, async_add_entities, _factory)


class LocklySlotEnabledSwitch(CoordinatorEntity[LocklySlotCoordinator], SwitchEntity):
    """Switch entity for slot enabled state."""

    _attr_icon = "mdi:lock"

    def __init__(self, coordinator: LocklySlotCoordinator, slot_id: int) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._slot_id = slot_id
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}-slot-{slot_id}-enabled"
        )
        self._attr_name = f"Slot {slot_id} Enabled"
        self._attr_device_info = DeviceInfo(
            identifiers={
                (coordinator.config_entry.domain, coordinator.config_entry.entry_id)
            },
            name=coordinator.config_entry.title,
        )

    @property
    def slot(self) -> LocklySlot | None:
        """Return the current slot."""
        return self.coordinator.data.get(self._slot_id)

    @property
    def is_on(self) -> bool:
        """Return true if the slot is enabled."""
        slot = self.slot
        return bool(slot.enabled) if slot else False

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra state attributes."""
        slot = self.slot
        manager = self.coordinator.config_entry.runtime_data.manager
        return {
            "lockly_entry_id": self.coordinator.config_entry.entry_id,
            "lockly_slot": self._slot_id,
            "lockly_group_entity": manager.group_entity_id,
            "lockly_type": "enabled",
            "busy": getattr(slot, "busy", False) if slot else False,
        }

    async def async_turn_on(self, **_: Any) -> None:
        """Enable the slot."""
        await self.coordinator.config_entry.runtime_data.manager.update_slot(
            self._slot_id, enabled=True
        )

    async def async_turn_off(self, **_: Any) -> None:
        """Disable the slot."""
        await self.coordinator.config_entry.runtime_data.manager.update_slot(
            self._slot_id, enabled=False
        )
