"""Slot manager for Lockly."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_ENDPOINT,
    CONF_LOCK_ENTITIES,
    CONF_LOCK_GROUP_ENTITY,
    CONF_LOCK_NAMES,
    CONF_MAX_SLOTS,
    CONF_MQTT_TOPIC,
    DEFAULT_ENDPOINT,
    DEFAULT_LOCK_NAMES,
    DEFAULT_MAX_SLOTS,
    DEFAULT_MQTT_TOPIC,
    LOGGER,
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
        self._pending_by_lock: dict[str, list[int]] = {}
        self._pending_slots: dict[int, set[str]] = {}
        self._pending_timeouts: dict[int, object] = {}

    @property
    def group_entity_id(self) -> str | None:
        """Return the configured lock group entity id."""
        data = self._entry.options or self._entry.data
        group_entity_id = data.get(CONF_LOCK_GROUP_ENTITY)
        return str(group_entity_id) if group_entity_id else None

    @property
    def lock_names(self) -> list[str]:
        """Configured Zigbee2MQTT lock friendly names."""
        data = self._entry.options or self._entry.data
        names = data.get(CONF_LOCK_NAMES, DEFAULT_LOCK_NAMES)
        if isinstance(names, str):
            names = [item.strip() for item in names.split(",") if item.strip()]
        if self.group_entity_id:
            group_names = self._resolve_group_lock_names(self.group_entity_id)
            if group_names:
                return group_names
        if lock_entities := self._get_lock_entities(data):
            expanded_entities = self._expand_lock_entity_ids(lock_entities)
            entity_names = self._resolve_lock_names_from_entities(expanded_entities)
            if entity_names:
                return entity_names
        LOGGER.debug(
            "No lock names resolved (group_entity_id=%s, lock_entities=%s, names=%s)",
            self.group_entity_id,
            self._get_lock_entities(data),
            names,
        )
        return [name for name in names if name]

    def _get_lock_entities(self, data: dict) -> list[str]:
        """Return lock entities from entry data/options."""
        entities = data.get(CONF_LOCK_ENTITIES, [])
        if isinstance(entities, str):
            return [entities]
        return list(entities) if isinstance(entities, list) else []

    def _resolve_group_lock_names(self, group_entity_id: str) -> list[str]:
        """Resolve lock friendly names from a group entity."""
        group_state = self._hass.states.get(group_entity_id)
        if not group_state:
            LOGGER.debug("Group entity %s not found in state", group_entity_id)
            return []
        entity_ids = group_state.attributes.get("entity_id", [])
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]
        if not isinstance(entity_ids, list):
            return []
        return self._resolve_lock_names_from_entities(entity_ids)

    def _expand_group_members(self, entity_id: str) -> list[str]:
        """Return lock entity members when a group entity is provided."""
        state = self._hass.states.get(entity_id)
        if not state:
            return []
        members = state.attributes.get("entity_id", [])
        if isinstance(members, str):
            members = [members]
        if not isinstance(members, list):
            return []
        return [
            member
            for member in members
            if isinstance(member, str) and member.startswith("lock.")
        ]

    def _resolve_lock_names_from_entities(self, entity_ids: list[str]) -> list[str]:
        """Resolve Zigbee2MQTT lock names from entity ids."""
        registry = er.async_get(self._hass)
        device_registry = dr.async_get(self._hass)
        names: list[str] = []
        for entity_id in entity_ids:
            if entity_id.startswith("group."):
                names.extend(self._resolve_group_lock_names(entity_id))
                continue
            group_members = self._expand_group_members(entity_id)
            if group_members:
                names.extend(self._resolve_lock_names_from_entities(group_members))
                continue
            state = self._hass.states.get(entity_id)
            if state and state.attributes.get("friendly_name"):
                names.append(state.attributes["friendly_name"])
                continue
            if state and state.attributes.get("device"):
                names.append(state.attributes["device"])
                continue
            entry = registry.async_get(entity_id)
            if entry and entry.device_id:
                device = device_registry.async_get(entry.device_id)
                if device and device.name:
                    names.append(device.name)
                    continue
            names.append(entity_id)
        return names

    def _expand_lock_entity_ids(self, entity_ids: Iterable[str]) -> list[str]:
        """Expand lock entity ids, resolving groups to lock entities."""
        expanded: list[str] = []
        for entity_id in entity_ids:
            if not entity_id:
                continue
            if entity_id.startswith("group."):
                members = self._expand_group_members(entity_id)
                expanded.extend(members)
                continue
            group_members = self._expand_group_members(entity_id)
            if group_members:
                expanded.extend(group_members)
                continue
            expanded.append(entity_id)
        return expanded

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
        LOGGER.debug(
            "Persisted slots: %s",
            [
                {
                    "slot": slot.slot,
                    "name": slot.name,
                    "pin": "***" if slot.pin else "",
                    "enabled": slot.enabled,
                    "busy": slot.busy,
                }
                for slot in self._coordinator.data.values()
            ],
        )

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

    async def remove_slot(
        self,
        slot_id: int,
        *,
        lock_entities: Iterable[str] | None = None,
        dry_run: bool = False,
    ) -> None:
        """Remove a slot and clear it from locks."""
        if slot_id not in self._coordinator.data:
            message = SLOT_NOT_FOUND
            raise ServiceValidationError(message)
        await self.apply_slot(
            slot_id,
            force_clear=True,
            lock_entities=lock_entities,
            dry_run=dry_run,
        )
        self._coordinator.data.pop(slot_id, None)
        await self._save()
        await self._remove_entities_for_slot(slot_id)

    async def update_slot(  # noqa: PLR0913
        self,
        slot_id: int,
        *,
        name: str | None = None,
        pin: str | None = None,
        enabled: bool | None = None,
        busy: bool | None = None,
        last_response: dict | None = None,
        last_response_ts: float | None = None,
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
            if enabled and not self._pin_re.match(slot.pin or ""):
                slot.enabled = False
                await self._save()
                await self._notify_invalid_pin(slot_id)
                message = INVALID_PIN
                raise ServiceValidationError(message)
            slot.enabled = enabled
        if busy is not None:
            slot.busy = busy
        if last_response is not None:
            slot.last_response = last_response
        if last_response_ts is not None:
            slot.last_response_ts = last_response_ts
        LOGGER.debug(
            "Updated slot %s (name=%s, pin=%s, enabled=%s, busy=%s)",
            slot_id,
            slot.name,
            "***" if slot.pin else "",
            slot.enabled,
            slot.busy,
        )
        await self._save()

    async def _notify_invalid_pin(self, slot_id: int) -> None:
        """Notify user about an invalid PIN."""
        if not self._hass.services.has_service("persistent_notification", "create"):
            return
        await self._hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Lockly",
                "message": f"Slot {slot_id}: PIN must be 4-8 digits (numbers only).",
            },
            blocking=True,
        )

    async def apply_slot(
        self,
        slot_id: int,
        *,
        force_clear: bool = False,
        lock_entities: Iterable[str] | None = None,
        dry_run: bool = False,
    ) -> None:
        """Apply a slot to all locks."""
        if slot_id not in self._coordinator.data:
            message = SLOT_NOT_FOUND
            raise ServiceValidationError(message)
        slot = self._coordinator.data[slot_id]
        if lock_entities is None:
            lock_names = self.lock_names
        else:
            entity_ids = self._expand_lock_entity_ids(lock_entities)
            lock_names = self._resolve_lock_names_from_entities(entity_ids)
        if not lock_names:
            message = NO_LOCKS_CONFIGURED
            raise ServiceValidationError(message)
        LOGGER.debug(
            "Applying slot %s to locks %s (enabled=%s)",
            slot_id,
            lock_names,
            slot.enabled,
        )
        if not force_clear and slot.enabled and not self._pin_re.match(slot.pin or ""):
            await self._notify_invalid_pin(slot_id)
            message = INVALID_PIN
            raise ServiceValidationError(message)
        await self.update_slot(slot_id, busy=True)
        if dry_run:
            await self.update_slot(
                slot_id,
                busy=False,
                last_response={"status": "simulated"},
                last_response_ts=time.time(),
            )
            return
        pending_locks = set(lock_names)
        self._pending_slots[slot_id] = pending_locks
        for lock_name in lock_names:
            self._pending_by_lock.setdefault(lock_name, []).append(slot_id)
            if force_clear or not slot.enabled:
                await self._publish_clear(slot_id, lock_name)
            else:
                await self._publish_set(slot_id, slot.pin, lock_name)
        if self._hass.data.get("lockly_skip_timeout"):
            await self.update_slot(slot_id, busy=False)
            self._pending_slots.pop(slot_id, None)
            return
        self._schedule_timeout(slot_id)

    async def apply_all(
        self, *, lock_entities: Iterable[str] | None = None, dry_run: bool = False
    ) -> None:
        """Apply all slots."""
        for slot_id in sorted(self._coordinator.data):
            slot = self._coordinator.data.get(slot_id)
            if not slot or not slot.enabled:
                continue
            await self.apply_slot(slot_id, lock_entities=lock_entities, dry_run=dry_run)

    async def wipe_slots(
        self,
        slot_ids: Iterable[int] | None = None,
        *,
        lock_entities: Iterable[str] | None = None,
        dry_run: bool = False,
    ) -> None:
        """Wipe all slots or a subset."""
        targets = (
            list(slot_ids) if slot_ids is not None else list(self._coordinator.data)
        )
        for slot_id in targets:
            if slot_id in self._coordinator.data:
                await self.remove_slot(
                    slot_id, lock_entities=lock_entities, dry_run=dry_run
                )

    async def _publish_set(self, slot_id: int, pin: str, lock_name: str) -> None:
        """Publish pin_code set to a lock."""
        payload = {
            "pin_code": {
                "user": slot_id,
                "user_type": "unrestricted",
                "user_enabled": True,
                "pin_code": pin,
            }
        }
        await self._publish_lock(lock_name, payload)

    async def _publish_clear(self, slot_id: int, lock_name: str) -> None:
        """Publish pin_code clear/disable to a lock."""
        payload = {
            "pin_code": {
                "user": slot_id,
                "user_type": "unrestricted",
                "user_enabled": False,
                "pin_code": None,
            }
        }
        await self._publish_lock(lock_name, payload)

    async def _publish_lock(self, lock_name: str, payload: dict) -> None:
        """Publish a Zigbee2MQTT per-lock set command."""
        topic = f"{self.mqtt_topic}/{lock_name}/set"
        if not self._hass.services.has_service("mqtt", "publish"):
            LOGGER.error("MQTT publish service not available for topic %s", topic)
            return
        safe_payload = payload
        if isinstance(payload, dict) and "pin_code" in payload:
            safe_payload = {
                **payload,
                "pin_code": {
                    **payload["pin_code"],
                    "pin_code": "***",
                },
            }
        LOGGER.debug("MQTT publish to %s: %s", topic, safe_payload)
        try:
            await self._hass.services.async_call(
                "mqtt",
                "publish",
                {
                    "topic": topic,
                    "qos": 1,
                    "payload": json.dumps(payload),
                },
                blocking=True,
            )
            LOGGER.debug("MQTT publish complete to %s", topic)
        except Exception as err:  # noqa: BLE001
            LOGGER.exception("MQTT publish failed for %s: %s", lock_name, err)

    def _schedule_timeout(self, slot_id: int, timeout: int = 15) -> None:
        """Schedule a timeout for an outstanding slot apply."""

        async def _on_timeout() -> None:
            pending_locks = self._pending_slots.pop(slot_id, None)
            if pending_locks is None:
                return
            if slot_id not in self._coordinator.data:
                LOGGER.debug(
                    "MQTT response timeout for slot %s ignored (slot removed)",
                    slot_id,
                )
                self._pending_timeouts.pop(slot_id, None)
                return
            await self.update_slot(
                slot_id,
                busy=False,
                last_response={
                    "status": "timeout",
                    "locks": sorted(pending_locks),
                },
                last_response_ts=time.time(),
            )
            self._pending_timeouts.pop(slot_id, None)
            LOGGER.warning("MQTT response timeout for slot %s", slot_id)

        handle = self._hass.loop.call_later(
            timeout, lambda: self._hass.async_create_task(_on_timeout())
        )
        self._pending_timeouts[slot_id] = handle

    async def handle_mqtt_action(self, lock_name: str, action: str) -> None:
        """Handle MQTT action responses for a lock."""
        slot_queue = self._pending_by_lock.get(lock_name)
        if not slot_queue:
            return
        slot_id = slot_queue.pop(0)
        if not slot_queue:
            self._pending_by_lock.pop(lock_name, None)
        pending_locks = self._pending_slots.get(slot_id)
        if pending_locks:
            pending_locks.discard(lock_name)
        if action == "pin_code_deleted":
            status = "available"
        elif action == "pin_code_added":
            status = "enabled"
        else:
            status = "unknown"
        LOGGER.debug(
            "Lock action for slot %s on %s: %s",
            slot_id,
            lock_name,
            action,
        )
        if slot_id not in self._coordinator.data:
            LOGGER.debug("Ignoring action for slot %s (slot removed)", slot_id)
            return
        await self.update_slot(
            slot_id,
            last_response={"lock": lock_name, "action": action, "status": status},
            last_response_ts=time.time(),
        )
        if pending_locks is not None and not pending_locks:
            self._pending_slots.pop(slot_id, None)
            handle = self._pending_timeouts.pop(slot_id, None)
            if handle is not None:
                handle.cancel()
            await self.update_slot(slot_id, busy=False)
