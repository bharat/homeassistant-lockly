"""Slot manager for Lockly."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable, Coroutine, Iterable
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict, Unpack

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_ENDPOINT,
    CONF_FIRST_SLOT,
    CONF_LAST_SLOT,
    CONF_LOCK_ENTITIES,
    CONF_LOCK_GROUP_ENTITY,
    CONF_LOCK_NAMES,
    CONF_MAX_SLOTS,
    CONF_MQTT_TOPIC,
    DEFAULT_ENDPOINT,
    DEFAULT_FIRST_SLOT,
    DEFAULT_LAST_SLOT,
    DEFAULT_LOCK_NAMES,
    DEFAULT_MQTT_TOPIC,
    LOGGER,
    PIN_REGEX,
)
from .coordinator import LocklySlot, LocklySlotCoordinator

if TYPE_CHECKING:
    from homeassistant.core import CALLBACK_TYPE, HomeAssistant

    from .data import LocklyConfigEntry

EntityFactory = Callable[[LocklySlot], list]


@dataclass(slots=True)
class SlotJob:
    """Queued slot application job."""

    slot_id: int
    lock_names: list[str]
    force_clear: bool
    dry_run: bool
    remove_on_complete: bool
    future: asyncio.Future[None]


@dataclass(slots=True)
class ApplySlotOptions:
    """Options for applying a slot."""

    force_clear: bool = False
    lock_entities: Iterable[str] | None = None
    dry_run: bool = False
    remove_on_complete: bool = False
    wait_for_completion: bool = True


class SlotUpdate(TypedDict, total=False):
    """Update payload for a lock slot."""

    name: NotRequired[str | None]
    pin: NotRequired[str | None]
    enabled: NotRequired[bool | None]
    busy: NotRequired[bool | None]
    status: NotRequired[str | None]
    last_response: NotRequired[dict | None]
    last_response_ts: NotRequired[float | None]


NO_AVAILABLE_SLOTS = "no_available_slots"
SLOT_NOT_FOUND = "slot_not_found"
NO_LOCKS_CONFIGURED = "no_locks_configured"
INVALID_PIN = "invalid_pin"
INVALID_SLOT = "invalid_slot"
DEFAULT_ACTION_TIMEOUT = 10
MAX_ACTION_RETRIES = 3


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
        self._pending_lock_names: dict[int, list[str]] = {}
        self._pending_actions: dict[tuple[int, str], dict[str, object]] = {}
        self._lock_queues: dict[str, asyncio.Queue[tuple[int, dict]]] = {}
        self._lock_workers: dict[str, asyncio.Task] = {}
        self._slot_publish_started: set[int] = set()
        self._stop_callbacks: list[CALLBACK_TYPE] = []
        self._slot_queue: asyncio.Queue[SlotJob] = asyncio.Queue()
        self._slot_worker_task: asyncio.Task | None = None
        self._slot_completion: dict[int, asyncio.Future[None]] = {}
        self._remove_after_apply: set[int] = set()

    @property
    def group_entity_id(self) -> str | None:
        """Return the configured lock group entity id."""
        data = self._entry.options or self._entry.data
        group_entity_id = data.get(CONF_LOCK_GROUP_ENTITY)
        return str(group_entity_id) if group_entity_id else None

    @property
    def coordinator(self) -> LocklySlotCoordinator:
        """Return the slot coordinator."""
        return self._coordinator

    @property
    def lock_workers(self) -> dict[str, asyncio.Task]:
        """Return active lock worker tasks."""
        return self._lock_workers

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
    def first_slot(self) -> int:
        """First slot configured."""
        data = self._entry.options or self._entry.data
        return int(data.get(CONF_FIRST_SLOT, DEFAULT_FIRST_SLOT))

    @property
    def last_slot(self) -> int:
        """Last slot configured."""
        data = self._entry.options or self._entry.data
        return int(
            data.get(CONF_LAST_SLOT, data.get(CONF_MAX_SLOTS, DEFAULT_LAST_SLOT))
        )

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
                    "status": slot.status,
                }
                for slot in self._coordinator.data.values()
            ],
        )

    def _next_available_slot(self) -> int | None:
        """Find next available slot ID."""
        for slot_id in range(self.first_slot, self.last_slot + 1):
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
            ApplySlotOptions(
                force_clear=True,
                lock_entities=lock_entities,
                dry_run=dry_run,
                remove_on_complete=True,
                wait_for_completion=True,
            ),
        )

    async def update_slot(self, slot_id: int, **updates: Unpack[SlotUpdate]) -> None:
        """Update a slot's stored values."""
        if slot_id not in self._coordinator.data:
            message = SLOT_NOT_FOUND
            raise ServiceValidationError(message)
        slot = self._coordinator.data[slot_id]
        name = updates.get("name")
        pin = updates.get("pin")
        enabled = updates.get("enabled")
        busy = updates.get("busy")
        status = updates.get("status")
        last_response = updates.get("last_response")
        last_response_ts = updates.get("last_response_ts")
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
        if status is not None:
            slot.status = status
        if last_response is not None:
            slot.last_response = last_response
        if last_response_ts is not None:
            slot.last_response_ts = last_response_ts
        LOGGER.debug(
            "Updated slot %s (name=%s, pin=%s, enabled=%s, busy=%s, status=%s)",
            slot_id,
            slot.name,
            "***" if slot.pin else "",
            slot.enabled,
            slot.busy,
            slot.status,
        )
        await self._save()

    def _ensure_slot(self, slot_id: int) -> LocklySlot:
        """Ensure a slot exists in storage."""
        slot = self._coordinator.data.get(slot_id)
        if slot:
            return slot
        slot = LocklySlot(slot=slot_id)
        self._coordinator.data[slot_id] = slot
        for platform_key in self._platforms:
            self._add_entities_for_slot(platform_key, slot)
        return slot

    def export_slots(self, *, include_pins: bool = False) -> list[dict]:
        """Export slots as serializable payload."""
        slots = []
        for slot_id in sorted(self._coordinator.data):
            slot = self._coordinator.data[slot_id]
            slots.append(
                {
                    "slot": slot.slot,
                    "name": slot.name,
                    "pin": slot.pin if include_pins else "",
                    "enabled": slot.enabled,
                }
            )
        return slots

    async def import_slots(self, slots: list[dict], *, replace: bool = True) -> None:
        """Import slots from a payload."""
        if replace:
            for slot_id in list(self._coordinator.data):
                await self._remove_entities_for_slot(slot_id)
                self._coordinator.data.pop(slot_id, None)
        for item in slots:
            if "slot" not in item:
                message = INVALID_SLOT
                raise ServiceValidationError(message)
            slot_id = int(item["slot"])
            if slot_id < self.first_slot or slot_id > self.last_slot:
                message = INVALID_SLOT
                raise ServiceValidationError(message)
            slot = self._ensure_slot(slot_id)
            slot.name = str(item.get("name", "") or "")
            slot.pin = str(item.get("pin", "") or "")
            enabled = bool(item.get("enabled", False))
            if enabled and not self._pin_re.match(slot.pin or ""):
                message = INVALID_PIN
                raise ServiceValidationError(message)
            slot.enabled = enabled
            slot.busy = False
            slot.status = ""
            slot.last_response = None
            slot.last_response_ts = None
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
        options: ApplySlotOptions | None = None,
    ) -> None:
        """Apply a slot to all locks."""
        options = options or ApplySlotOptions()
        if slot_id not in self._coordinator.data:
            message = SLOT_NOT_FOUND
            raise ServiceValidationError(message)
        slot = self._coordinator.data[slot_id]
        if options.lock_entities is None:
            lock_names = self.lock_names
        else:
            entity_ids = self._expand_lock_entity_ids(options.lock_entities)
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
        if (
            not options.force_clear
            and slot.enabled
            and not self._pin_re.match(slot.pin or "")
        ):
            await self._notify_invalid_pin(slot_id)
            message = INVALID_PIN
            raise ServiceValidationError(message)
        await self.update_slot(slot_id, busy=True, status="queued")
        self._ensure_slot_worker()
        future: asyncio.Future[None] = self._hass.loop.create_future()
        await self._slot_queue.put(
            SlotJob(
                slot_id=slot_id,
                lock_names=list(lock_names),
                force_clear=options.force_clear,
                dry_run=options.dry_run,
                remove_on_complete=options.remove_on_complete,
                future=future,
            )
        )
        if options.wait_for_completion:
            await future

    async def apply_all(
        self, *, lock_entities: Iterable[str] | None = None, dry_run: bool = False
    ) -> None:
        """Apply all slots."""
        for slot_id in sorted(self._coordinator.data):
            slot = self._coordinator.data.get(slot_id)
            if not slot or not slot.enabled:
                continue
            await self.apply_slot(
                slot_id,
                ApplySlotOptions(
                    lock_entities=lock_entities,
                    dry_run=dry_run,
                    wait_for_completion=False,
                ),
            )

    def _create_background_task(
        self, coro: Coroutine[Any, Any, Any], name: str
    ) -> asyncio.Task:
        """Create a background task when supported by Home Assistant."""
        create = getattr(self._hass, "async_create_background_task", None)
        if create is not None:
            try:
                return create(coro, name)
            except TypeError:
                return create(coro)
        return self._hass.async_create_task(coro)

    def _ensure_lock_worker(self, lock_name: str) -> asyncio.Queue[tuple[int, dict]]:
        """Ensure a per-lock worker is running for publish serialization."""
        queue = self._lock_queues.get(lock_name)
        if queue is None:
            queue = asyncio.Queue()
            self._lock_queues[lock_name] = queue
        worker = self._lock_workers.get(lock_name)
        if worker is None or worker.done():
            self._lock_workers[lock_name] = self._hass.async_create_task(
                self._lock_worker(lock_name, queue)
            )
        return queue

    def _ensure_slot_worker(self) -> None:
        """Ensure a single slot worker is running for slot serialization."""
        if self._slot_worker_task is None or self._slot_worker_task.done():
            self._slot_worker_task = self._create_background_task(
                self._slot_worker(), "lockly_slot_worker"
            )

    async def _slot_worker(self) -> None:
        """Worker that serializes slot updates."""
        while True:
            job = await self._slot_queue.get()
            try:
                await self._process_slot_job(job)
                if not job.future.done():
                    with suppress(asyncio.CancelledError, HomeAssistantError):
                        await job.future
            except HomeAssistantError as err:  # pragma: no cover - defensive
                if not job.future.done():
                    job.future.set_exception(err)
            finally:
                self._slot_queue.task_done()

    async def _process_slot_job(self, job: SlotJob) -> None:
        """Process a queued slot job."""
        slot = self._coordinator.data.get(job.slot_id)
        if not slot:
            self._resolve_job_future(job)
            return
        self._slot_completion[job.slot_id] = job.future
        if job.remove_on_complete:
            self._remove_after_apply.add(job.slot_id)
        await self.update_slot(job.slot_id, busy=True, status="updating")
        if job.dry_run:
            await self._handle_dry_run(job.slot_id)
            await self._finalize_slot_completion(job.slot_id)
            return
        await self._queue_slot_actions(job, slot)
        if self._hass.data.get("lockly_skip_timeout"):
            await self._finalize_skip_timeout(job.slot_id, job.lock_names)

    def _resolve_job_future(self, job: SlotJob) -> None:
        """Resolve a job when its slot no longer exists."""
        if not job.future.done():
            job.future.set_result(None)

    async def _handle_dry_run(self, slot_id: int) -> None:
        """Mark a slot as completed for a dry run."""
        await self.update_slot(
            slot_id,
            busy=False,
            status="",
            last_response={"status": "simulated"},
            last_response_ts=time.time(),
        )

    async def _queue_slot_actions(self, job: SlotJob, slot: LocklySlot) -> None:
        """Queue MQTT actions for a slot update."""
        pending_locks = set(job.lock_names)
        self._pending_slots[job.slot_id] = pending_locks
        self._pending_lock_names[job.slot_id] = list(job.lock_names)
        for lock_name in job.lock_names:
            self._pending_by_lock.setdefault(lock_name, []).append(job.slot_id)
            payload = self._build_slot_payload(
                job.slot_id, slot, force_clear=job.force_clear
            )
            self._pending_actions[(job.slot_id, lock_name)] = {
                "attempts": 0,
                "payload": payload,
                "handle": None,
            }
            await self._enqueue_publish(lock_name, job.slot_id, payload)

    def _build_slot_payload(
        self, slot_id: int, slot: LocklySlot, *, force_clear: bool
    ) -> dict:
        """Build the MQTT payload for a slot update."""
        if force_clear or not slot.enabled:
            return {
                "pin_code": {
                    "user": slot_id,
                    "user_type": "unrestricted",
                    "user_enabled": False,
                    "pin_code": None,
                }
            }
        return {
            "pin_code": {
                "user": slot_id,
                "user_type": "unrestricted",
                "user_enabled": True,
                "pin_code": slot.pin,
            }
        }

    async def _finalize_skip_timeout(
        self, slot_id: int, lock_names: Iterable[str]
    ) -> None:
        """Finalize a slot immediately when timeouts are disabled."""
        await self.update_slot(slot_id, busy=False, status="")
        self._pending_slots.pop(slot_id, None)
        self._pending_lock_names.pop(slot_id, None)
        for lock_name in lock_names:
            self._pending_actions.pop((slot_id, lock_name), None)
        await self._finalize_slot_completion(slot_id)

    def register_stop_listener(self) -> None:
        """Register a listener to cancel background workers on shutdown."""
        if self._stop_callbacks:
            return

        def _on_stop(_: object) -> None:
            self._hass.add_job(self.async_stop(remove_listeners=False))

        self._stop_callbacks.append(
            self._hass.bus.async_listen_once("homeassistant_stop", _on_stop)
        )

    async def async_stop(self, *, remove_listeners: bool = False) -> None:
        """Stop background tasks for the manager."""
        if remove_listeners:
            for callback in self._stop_callbacks:
                try:
                    callback()
                except ValueError:
                    LOGGER.debug("Stop listener already removed", exc_info=True)
            self._stop_callbacks.clear()
        else:
            self._stop_callbacks.clear()
        for worker in self._lock_workers.values():
            worker.cancel()
        self._lock_workers.clear()
        self._lock_queues.clear()
        for action in self._pending_actions.values():
            handle = action.get("handle")
            if handle is not None:
                handle.cancel()
        self._pending_actions.clear()

    async def _enqueue_publish(
        self, lock_name: str, slot_id: int, payload: dict
    ) -> None:
        """Queue a publish for a lock, preserving per-lock order."""
        if self._hass.data.get("lockly_skip_worker"):
            self._start_action_timer(slot_id, lock_name)
            await self._mark_slot_updating(slot_id)
            LOGGER.debug(
                "MQTT publish (sync) queued for slot %s on %s",
                slot_id,
                lock_name,
            )
            await self._publish_lock(lock_name, payload)
            return
        queue = self._ensure_lock_worker(lock_name)
        LOGGER.debug("MQTT publish queued for slot %s on %s", slot_id, lock_name)
        await queue.put((slot_id, payload))

    async def _lock_worker(
        self, lock_name: str, queue: asyncio.Queue[tuple[int, dict]]
    ) -> None:
        """Worker that serializes publishes for a lock."""
        while True:
            slot_id, payload = await queue.get()
            try:
                self._start_action_timer(slot_id, lock_name)
                await self._mark_slot_updating(slot_id)
                await self._publish_lock(lock_name, payload)
            except HomeAssistantError as err:
                LOGGER.exception("MQTT publish failed for %s: %s", lock_name, err)
            finally:
                queue.task_done()

    async def _mark_slot_updating(self, slot_id: int) -> None:
        """Mark a slot as updating when its first publish starts."""
        if slot_id in self._slot_publish_started:
            return
        if slot_id not in self._coordinator.data:
            return
        self._slot_publish_started.add(slot_id)
        await self.update_slot(slot_id, status="updating")

    def _start_action_timer(self, slot_id: int, lock_name: str) -> None:
        """Start a timeout timer for a lock action if needed."""
        if self._hass.data.get("lockly_skip_timeout"):
            return
        action = self._pending_actions.get((slot_id, lock_name))
        if not action or action.get("handle"):
            return
        action["handle"] = self._hass.loop.call_later(
            DEFAULT_ACTION_TIMEOUT,
            lambda: self._hass.async_create_task(
                self._handle_action_timeout(slot_id, lock_name)
            ),
        )
        LOGGER.debug(
            "Action timer started for slot %s on %s (attempt=%s, timeout=%ss)",
            slot_id,
            lock_name,
            action.get("attempts", 0) + 1,
            DEFAULT_ACTION_TIMEOUT,
        )

    def _cancel_action_timer(self, slot_id: int, lock_name: str) -> None:
        """Cancel an outstanding timeout for a lock action."""
        action = self._pending_actions.get((slot_id, lock_name))
        if not action:
            return
        handle = action.get("handle")
        if handle is not None:
            handle.cancel()
        action["handle"] = None
        LOGGER.debug("Action timer cleared for slot %s on %s", slot_id, lock_name)

    async def _handle_action_timeout(self, slot_id: int, lock_name: str) -> None:
        """Handle a timeout for a lock action, retrying if configured."""
        action = self._pending_actions.get((slot_id, lock_name))
        if not action:
            return
        action["handle"] = None
        attempts = int(action.get("attempts", 0))
        if attempts < MAX_ACTION_RETRIES:
            action["attempts"] = attempts + 1
            LOGGER.debug(
                "Retrying slot %s on %s (attempt=%s/%s)",
                slot_id,
                lock_name,
                action["attempts"] + 1,
                MAX_ACTION_RETRIES + 1,
            )
            await self._enqueue_publish(lock_name, slot_id, action["payload"])
            return
        self._pending_actions.pop((slot_id, lock_name), None)
        pending_locks = self._pending_slots.get(slot_id)
        if pending_locks:
            pending_locks.discard(lock_name)
        if slot_id not in self._coordinator.data:
            return
        await self.update_slot(
            slot_id,
            status="timeout",
            last_response={
                "lock": lock_name,
                "status": "timeout",
                "attempts": attempts + 1,
            },
            last_response_ts=time.time(),
        )
        LOGGER.warning(
            "MQTT response timeout for slot %s on %s (attempts=%s)",
            slot_id,
            lock_name,
            attempts + 1,
        )
        if pending_locks is not None and not pending_locks:
            self._pending_slots.pop(slot_id, None)
            self._pending_lock_names.pop(slot_id, None)
            self._slot_publish_started.discard(slot_id)
            await self.update_slot(slot_id, busy=False, status="timeout")
            await self._finalize_slot_completion(slot_id)

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
        except (HomeAssistantError, TypeError) as err:
            LOGGER.exception("MQTT publish failed for %s: %s", lock_name, err)

    def _dequeue_pending_slot(
        self,
        lock_name: str,
        action: str,
        *,
        slot_id: int | None = None,
        source: str,
    ) -> int | None:
        """Remove a pending slot for a lock, honoring explicit slot IDs."""
        slot_queue = self._pending_by_lock.get(lock_name)
        if not slot_queue:
            LOGGER.debug(
                "Lock %s ignored for %s (no pending slot): %s",
                source,
                lock_name,
                action,
            )
            return None
        if slot_id is None:
            slot_id = slot_queue.pop(0)
        else:
            try:
                slot_queue.remove(slot_id)
            except ValueError:
                LOGGER.debug(
                    "Lock %s ignored for %s (slot %s not pending): %s",
                    source,
                    lock_name,
                    slot_id,
                    action,
                )
                return None
        if not slot_queue:
            self._pending_by_lock.pop(lock_name, None)
        LOGGER.debug(
            "Lock %s dequeued slot %s for %s (action=%s)",
            source,
            slot_id,
            lock_name,
            action,
        )
        return slot_id

    async def handle_mqtt_action(
        self, lock_name: str, action: str, *, action_user: int | None = None
    ) -> None:
        """Handle MQTT action responses for a lock."""
        slot_id = self._dequeue_pending_slot(
            lock_name, action, slot_id=action_user, source="action"
        )
        if slot_id is None:
            return
        await self._complete_action(lock_name, slot_id, action)

    async def handle_mqtt_state(self, lock_name: str, payload: dict) -> None:
        """Handle MQTT state updates to confirm pending actions."""
        match = self._match_pending_state(lock_name, payload)
        if match is None:
            return
        slot_id, action_name, status = match
        LOGGER.debug(
            "Lock state matched slot %s on %s (status=%s)",
            slot_id,
            lock_name,
            status,
        )
        slot_id = self._dequeue_pending_slot(
            lock_name, action_name, slot_id=slot_id, source="state"
        )
        if slot_id is None:
            return
        await self._complete_action(lock_name, slot_id, action_name)

    def _match_pending_state(
        self, lock_name: str, payload: dict
    ) -> tuple[int, str, str] | None:
        """Return pending slot/action details if the payload matches."""
        slot_queue = self._pending_by_lock.get(lock_name)
        users = payload.get("users") if slot_queue else None
        if not slot_queue or not isinstance(users, dict):
            return None
        slot_id = slot_queue[0]
        action = self._pending_actions.get((slot_id, lock_name))
        user_entry = users.get(str(slot_id)) or users.get(slot_id)
        status = user_entry.get("status") if isinstance(user_entry, dict) else None
        payload_data = action.get("payload") if isinstance(action, dict) else None
        pin_code = (
            payload_data.get("pin_code") if isinstance(payload_data, dict) else None
        )
        if (
            not action
            or action.get("handle") is None
            or not isinstance(user_entry, dict)
            or not status
            or not isinstance(payload_data, dict)
            or not isinstance(pin_code, dict)
        ):
            return None
        enabled = bool(pin_code.get("user_enabled"))
        expected_statuses = {"enabled"} if enabled else {"available", "disabled"}
        if status not in expected_statuses:
            return None
        action_name = "pin_code_added" if enabled else "pin_code_deleted"
        return slot_id, action_name, status

    async def _complete_action(self, lock_name: str, slot_id: int, action: str) -> None:
        """Finalize a pending action once a response is received."""
        self._cancel_action_timer(slot_id, lock_name)
        self._pending_actions.pop((slot_id, lock_name), None)
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
            self._slot_publish_started.discard(slot_id)
            await self.update_slot(slot_id, busy=False, status="")
            self._pending_lock_names.pop(slot_id, None)
            await self._finalize_slot_completion(slot_id)

    async def _finalize_slot_completion(self, slot_id: int) -> None:
        """Resolve completion futures and remove slots if requested."""
        future = self._slot_completion.pop(slot_id, None)
        if future and not future.done():
            future.set_result(None)
        if slot_id in self._remove_after_apply:
            self._remove_after_apply.discard(slot_id)
            await self._remove_slot_after_apply(slot_id)

    async def _remove_slot_after_apply(self, slot_id: int) -> None:
        """Remove slot data/entities after a wipe completes."""
        self._coordinator.data.pop(slot_id, None)
        await self._save()
        await self._remove_entities_for_slot(slot_id)
