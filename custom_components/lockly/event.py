"""Event platform for Lockly lock actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.event import EventEntity
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, LOGGER

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .data import LocklyConfigEntry

# Matches Z2M exposes.action.values + pin_code management actions
LOCK_ACTION_EVENTS = [
    "unknown",
    "lock",
    "unlock",
    "lock_failure_invalid_pin_or_id",
    "lock_failure_invalid_schedule",
    "unlock_failure_invalid_pin_or_id",
    "unlock_failure_invalid_schedule",
    "one_touch_lock",
    "key_lock",
    "key_unlock",
    "auto_lock",
    "schedule_lock",
    "schedule_unlock",
    "manual_lock",
    "manual_unlock",
    "non_access_user_operational_event",
    "pin_code_added",
    "pin_code_deleted",
]


class LocklyLockEvent(EventEntity):
    """Event entity tracking actions for a lock managed by Lockly."""

    _attr_has_entity_name = True
    _attr_event_types = LOCK_ACTION_EVENTS

    def __init__(self, entry_id: str, entry_title: str, lock_name: str) -> None:
        """Initialize the lock event entity."""
        slug = lock_name.lower().replace(" ", "_").replace("-", "_")
        self._attr_unique_id = f"{entry_id}-lock-event-{slug}"
        self._attr_name = lock_name
        self._attr_icon = "mdi:lock-clock"
        self._entry_id = entry_id
        self._entry_title = entry_title
        self._lock_name = lock_name

    @property
    def device_info(self) -> DeviceInfo:
        """Associate with the Lockly config entry device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=self._entry_title,
        )

    def fire_action(self, event_type: str, event_data: dict) -> None:
        """Trigger a lock action event."""
        if event_type not in LOCK_ACTION_EVENTS:
            LOGGER.debug("Unknown lock event type: %s", event_type)
            return
        self._trigger_event(event_type, event_data)
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LocklyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Lockly event entities."""
    runtime = hass.data[DOMAIN].get(entry.entry_id)
    if runtime is None:
        return

    manager = runtime.manager
    entities: dict[str, LocklyLockEvent] = {}

    def handle_lock_event(lock_name: str, event_type: str, event_data: dict) -> None:
        if lock_name not in entities:
            entity = LocklyLockEvent(entry.entry_id, entry.title, lock_name)
            entities[lock_name] = entity
            async_add_entities([entity])
            LOGGER.debug("Created event entity for lock: %s", lock_name)

        entity = entities[lock_name]
        if entity.hass is not None:
            entity.fire_action(event_type, event_data)

    manager.register_lock_event_callback(handle_lock_event)
