"""Slot manager for Lockly."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_ENDPOINT,
    CONF_LOCK_NAMES,
    CONF_MAX_SLOTS,
    CONF_MQTT_TOPIC,
    DEFAULT_ENDPOINT,
    DEFAULT_LOCK_NAMES,
    DEFAULT_MAX_SLOTS,
    DEFAULT_MQTT_TOPIC,
    PIN_REGEX,
)
from .coordinator import LocklySlot, LocklySlotCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import LocklyConfigEntry

EntityFactory = Callable[[LocklySlot], list]

NO_AVAILABLE_SLOTS = "no_available_slots"
SLOT_NOT_FOUND = "slot_not_found"
NO_LOCKS_CONFIGURED = "no_locks_configured"
INVALID_PIN = "invalid_pin"


class LocklyManager:
    """Manage Lockly slots and MQTT actions."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: LocklyConfigEntry,
        coordinator: LocklySlotCoordinator,
    ) -> None:
        """Initialize the manager."""
        self._hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._platforms: dict[str, tuple[Callable, EntityFactory]] = {}
        self._entities: dict[int, dict[str, list]] = {}
        self._pin_re = re.compile(PIN_REGEX)

    @property
    def lock_names(self) -> list[str]:
        """Configured Zigbee2MQTT lock friendly names."""
        data = self._entry.options or self._entry.data
        names = data.get(CONF_LOCK_NAMES, DEFAULT_LOCK_NAMES)
        if isinstance(names, str):
            names = [item.strip() for item in names.split(",") if item.strip()]
        return [name for name in names if name]

    @property
    def max_slots(self) -> int:
        """Maximum slots configured."""
        data = self._entry.options or self._entry.data
        return int(data.get(CONF_MAX_SLOTS, DEFAULT_MAX_SLOTS))

    @property
    def mqtt_topic(self) -> str:
        """Base MQTT topic for Zigbee2MQTT."""
        data = self._entry.options or self._entry.data
        return str(data.get(CONF_MQTT_TOPIC, DEFAULT_MQTT_TOPIC))

    @property
    def endpoint(self) -> int:
        """Endpoint for the lock device."""
        data = self._entry.options or self._entry.data
        return int(data.get(CONF_ENDPOINT, DEFAULT_ENDPOINT))

    def register_platform(
        self,
        platform_key: str,
        async_add_entities: Callable,
        entity_factory: EntityFactory,
    ) -> None:
        """Register a platform for dynamic slot entities."""
        self._platforms[platform_key] = (async_add_entities, entity_factory)
        for slot in self._coordinator.data.values():
            self._add_entities_for_slot(platform_key, slot)

    def _add_entities_for_slot(self, platform_key: str, slot: LocklySlot) -> None:
        """Add entities for a slot on a platform."""
        if platform_key not in self._platforms:
            return
        async_add_entities, factory = self._platforms[platform_key]
        entities = factory(slot)
        self._entities.setdefault(slot.slot, {}).setdefault(platform_key, [])
        self._entities[slot.slot][platform_key].extend(entities)
        async_add_entities(entities)

    async def _remove_entities_for_slot(self, slot_id: int) -> None:
        """Remove entities for a slot across platforms."""
        registry = er.async_get(self._hass)
        for entities in self._entities.get(slot_id, {}).values():
            for entity in entities:
                await entity.async_remove()
                if entity.entity_id:
                    registry.async_remove(entity.entity_id)
        self._entities.pop(slot_id, None)

    async def _save(self) -> None:
        """Persist coordinator state."""
        await self._coordinator.async_save()
        self._coordinator.async_set_updated_data(self._coordinator.data)

    def _next_available_slot(self) -> int | None:
        """Find next available slot ID."""
        for slot_id in range(1, self.max_slots + 1):
            if slot_id not in self._coordinator.data:
                return slot_id
        return None

    async def add_slot(self) -> LocklySlot:
        """Add a new slot."""
        slot_id = self._next_available_slot()
        if slot_id is None:
            message = NO_AVAILABLE_SLOTS
            raise ServiceValidationError(message)
        slot = LocklySlot(slot=slot_id)
        self._coordinator.data[slot_id] = slot
        await self._save()
        for platform_key in self._platforms:
            self._add_entities_for_slot(platform_key, slot)
        return slot

    async def remove_slot(self, slot_id: int) -> None:
        """Remove a slot and clear it from locks."""
        if slot_id not in self._coordinator.data:
            message = SLOT_NOT_FOUND
            raise ServiceValidationError(message)
        await self.apply_slot(slot_id, force_clear=True)
        self._coordinator.data.pop(slot_id, None)
        await self._save()
        await self._remove_entities_for_slot(slot_id)

    async def update_slot(
        self,
        slot_id: int,
        *,
        name: str | None = None,
        pin: str | None = None,
        enabled: bool | None = None,
        busy: bool | None = None,
    ) -> None:
        """Update a slot's stored values."""
        if slot_id not in self._coordinator.data:
            message = SLOT_NOT_FOUND
            raise ServiceValidationError(message)
        slot = self._coordinator.data[slot_id]
        if name is not None:
            slot.name = name
        if pin is not None:
            slot.pin = pin
        if enabled is not None:
            slot.enabled = enabled
        if busy is not None:
            slot.busy = busy
        await self._save()

    async def apply_slot(self, slot_id: int, *, force_clear: bool = False) -> None:
        """Apply a slot to all locks."""
        if slot_id not in self._coordinator.data:
            message = SLOT_NOT_FOUND
            raise ServiceValidationError(message)
        slot = self._coordinator.data[slot_id]
        if not self.lock_names:
            message = NO_LOCKS_CONFIGURED
            raise ServiceValidationError(message)
        if not force_clear and slot.enabled and not self._pin_re.match(slot.pin or ""):
            message = INVALID_PIN
            raise ServiceValidationError(message)
        await self.update_slot(slot_id, busy=True)
        try:
            if force_clear or not slot.enabled:
                await self._publish_clear(slot_id, self.lock_names)
            else:
                await self._publish_set(slot_id, slot.pin, self.lock_names)
        finally:
            await self.update_slot(slot_id, busy=False)

    async def apply_all(self) -> None:
        """Apply all slots."""
        for slot_id in sorted(self._coordinator.data):
            await self.apply_slot(slot_id)

    async def wipe_slots(self, slot_ids: Iterable[int] | None = None) -> None:
        """Wipe all slots or a subset."""
        targets = (
            list(slot_ids) if slot_ids is not None else list(self._coordinator.data)
        )
        for slot_id in targets:
            if slot_id in self._coordinator.data:
                await self.remove_slot(slot_id)

    async def _publish_set(
        self, slot_id: int, pin: str, lock_names: Iterable[str]
    ) -> None:
        """Publish setPinCode to locks."""
        payload = {
            "endpoint": self.endpoint,
            "cluster": "closuresDoorLock",
            "command": "setPinCode",
            "commandType": "functional",
            "transaction": f"lockly-{slot_id}",
            "payload": {
                "userid": slot_id,
                "usertype": 0,
                "userstatus": 1,
                "pincodevalue": pin,
            },
        }
        await self._publish(lock_names, payload)

    async def _publish_clear(self, slot_id: int, lock_names: Iterable[str]) -> None:
        """Publish clearPinCode to locks."""
        payload = {
            "endpoint": self.endpoint,
            "cluster": "closuresDoorLock",
            "command": "clearPinCode",
            "commandType": "functional",
            "transaction": f"lockly-{slot_id}",
            "payload": {"userid": slot_id},
        }
        await self._publish(lock_names, payload)

    async def _publish(self, lock_names: Iterable[str], payload: dict) -> None:
        """Publish a Zigbee2MQTT device command for each lock."""
        topic = f"{self.mqtt_topic}/bridge/request/device/command"
        for lock_name in lock_names:
            command = {"id": lock_name, **payload}
            await self._hass.services.async_call(
                "mqtt",
                "publish",
                {
                    "topic": topic,
                    "qos": 1,
                    "payload": json.dumps(command),
                },
                blocking=True,
            )
