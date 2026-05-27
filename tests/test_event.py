"""Tests for the Lockly event platform."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from homeassistant.const import CONF_NAME
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lockly import (
    _handle_action_message,
    _handle_state_payload,
)
from custom_components.lockly.const import (
    CONF_ENDPOINT,
    CONF_FIRST_SLOT,
    CONF_LAST_SLOT,
    CONF_LOCK_NAMES,
    CONF_MQTT_TOPIC,
    DEFAULT_ENDPOINT,
    DEFAULT_FIRST_SLOT,
    DEFAULT_LAST_SLOT,
    DEFAULT_MQTT_TOPIC,
    DOMAIN,
)
from custom_components.lockly.event import LocklyLockEvent
from custom_components.lockly.logbook import EVENT_LOCKLY_LOCK_ACTIVITY

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@pytest.fixture
def entity(hass: HomeAssistant) -> LocklyLockEvent:
    ent = LocklyLockEvent("test-entry-id", "My Lockly", "Front Door")
    ent.hass = hass
    ent.entity_id = "event.lockly_front_door"
    return ent


def test_unique_id(entity: LocklyLockEvent) -> None:
    assert entity.unique_id == "test-entry-id-lock-event-front_door"


def test_device_info(entity: LocklyLockEvent) -> None:
    info = entity.device_info
    assert ("lockly", "test-entry-id") in info["identifiers"]
    assert info["name"] == "My Lockly"


@pytest.mark.asyncio
async def test_fire_action_triggers_event(
    entity: LocklyLockEvent,
) -> None:
    event_data = {
        "user_name": "Bob",
        "slot_id": 2,
        "source": "keypad",
    }
    fired: list[dict] = []
    entity.hass.bus.async_listen(
        EVENT_LOCKLY_LOCK_ACTIVITY,
        lambda event: fired.append(event.data),
    )
    with (
        patch.object(entity, "_trigger_event") as mock_trigger,
        patch.object(entity, "async_write_ha_state"),
    ):
        entity.fire_action("unlock", event_data)

    await entity.hass.async_block_till_done()
    mock_trigger.assert_called_once_with("unlock", event_data)
    assert len(fired) == 1
    assert fired[0]["lock"] == "Front Door"
    assert fired[0]["action"] == "unlock"
    assert fired[0]["user_name"] == "Bob"


def test_fire_action_ignores_unknown_type(
    entity: LocklyLockEvent,
) -> None:
    with (
        patch.object(entity, "_trigger_event") as mock_trigger,
        patch.object(entity, "async_write_ha_state"),
    ):
        entity.fire_action("totally_bogus", {})

    mock_trigger.assert_not_called()


def _register_lock_state(hass: HomeAssistant, lock_name: str) -> None:
    """Register a `lock.*` entity in the state machine with the given friendly_name."""
    slug = lock_name.lower().replace(" ", "_").replace("-", "_")
    hass.states.async_set(
        f"lock.{slug}",
        "locked",
        {"friendly_name": lock_name},
    )


async def _setup_entry_with_lock_names(
    hass: HomeAssistant,
    enable_custom_integrations: Any,
    lock_names: list[str],
    *,
    entry_id: str | None = None,
    register_states: bool = True,
) -> MockConfigEntry:
    """Set up a Lockly config entry whose lock_names resolves to the given list.

    By default this also registers matching `lock.*` entities in the state
    machine; the dispatch filter now derives its set of valid lock names
    from the state machine rather than from config.
    """
    _ = enable_custom_integrations
    hass.data["lockly_skip_frontend"] = True
    hass.data["lockly_skip_mqtt"] = True
    hass.data["lockly_skip_worker"] = True
    hass.data["lockly_skip_timeout"] = True
    if register_states:
        for name in lock_names:
            _register_lock_state(hass, name)
    kwargs: dict[str, Any] = {
        "domain": DOMAIN,
        "title": "Lockly",
        "data": {
            CONF_NAME: "Lockly",
            CONF_FIRST_SLOT: DEFAULT_FIRST_SLOT,
            CONF_LAST_SLOT: DEFAULT_LAST_SLOT,
            CONF_MQTT_TOPIC: DEFAULT_MQTT_TOPIC,
            CONF_ENDPOINT: DEFAULT_ENDPOINT,
            CONF_LOCK_NAMES: lock_names,
        },
    }
    if entry_id is not None:
        kwargs["entry_id"] = entry_id
    entry = MockConfigEntry(**kwargs)
    entry.add_to_hass(hass)
    await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    return entry


@pytest.mark.enable_socket
async def test_state_dispatch_ignores_unconfigured_lock(
    hass: HomeAssistant, enable_custom_integrations: Any
) -> None:
    """State-payload messages for non-configured locks must not reach the manager."""
    entry = await _setup_entry_with_lock_names(
        hass, enable_custom_integrations, ["Garden Upper Lock"]
    )
    manager = hass.data[DOMAIN][entry.entry_id].manager
    assert "Garden Upper Lock" in manager.lock_names

    action_calls: list[tuple[tuple, dict]] = []
    state_calls: list[tuple[tuple, dict]] = []

    async def fake_action(*args: Any, **kwargs: Any) -> None:
        action_calls.append((args, kwargs))

    async def fake_state(*args: Any, **kwargs: Any) -> None:
        state_calls.append((args, kwargs))

    manager.handle_mqtt_action = fake_action
    manager.handle_mqtt_state = fake_state

    stale = SimpleNamespace(
        topic=f"{DEFAULT_MQTT_TOPIC}/Control4 Keypad",
        payload='{"action": "unlock", "action_user": 5}',
    )
    await _handle_state_payload(manager, stale)
    assert action_calls == []
    assert state_calls == []

    valid = SimpleNamespace(
        topic=f"{DEFAULT_MQTT_TOPIC}/Garden Upper Lock",
        payload='{"action": "unlock"}',
    )
    await _handle_state_payload(manager, valid)
    assert len(action_calls) == 1
    args, kwargs = action_calls[0]
    assert args[0] == "Garden Upper Lock"
    assert args[1] == "unlock"
    assert kwargs.get("fire_lock_event") is True


@pytest.mark.enable_socket
async def test_action_dispatch_ignores_unconfigured_lock(
    hass: HomeAssistant, enable_custom_integrations: Any
) -> None:
    """Action-topic messages for non-configured locks must not reach the manager."""
    entry = await _setup_entry_with_lock_names(
        hass, enable_custom_integrations, ["Garden Upper Lock"]
    )
    manager = hass.data[DOMAIN][entry.entry_id].manager

    calls: list[tuple[tuple, dict]] = []

    async def tracker(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))

    manager.handle_mqtt_action = tracker

    stale = SimpleNamespace(
        topic=f"{DEFAULT_MQTT_TOPIC}/Control4 Keypad/action",
        payload="unlock",
    )
    await _handle_action_message(manager, stale)
    assert calls == []

    valid = SimpleNamespace(
        topic=f"{DEFAULT_MQTT_TOPIC}/Garden Upper Lock/action",
        payload="unlock",
    )
    await _handle_action_message(manager, valid)
    assert len(calls) == 1
    args, _ = calls[0]
    assert args[0] == "Garden Upper Lock"


@pytest.mark.enable_socket
async def test_setup_removes_stale_event_entities(
    hass: HomeAssistant, enable_custom_integrations: Any
) -> None:
    """Pre-existing event entities for unconfigured locks are removed at setup."""
    _ = enable_custom_integrations
    hass.data["lockly_skip_frontend"] = True
    hass.data["lockly_skip_mqtt"] = True
    hass.data["lockly_skip_worker"] = True
    hass.data["lockly_skip_timeout"] = True

    entry_id = "lockly_test_entry"
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Lockly",
        entry_id=entry_id,
        data={
            CONF_NAME: "Lockly",
            CONF_FIRST_SLOT: DEFAULT_FIRST_SLOT,
            CONF_LAST_SLOT: DEFAULT_LAST_SLOT,
            CONF_MQTT_TOPIC: DEFAULT_MQTT_TOPIC,
            CONF_ENDPOINT: DEFAULT_ENDPOINT,
            CONF_LOCK_NAMES: ["Garden Upper Lock"],
        },
    )
    entry.add_to_hass(hass)
    _register_lock_state(hass, "Garden Upper Lock")

    registry = er.async_get(hass)
    stale = registry.async_get_or_create(
        "event",
        DOMAIN,
        f"{entry_id}-lock-event-control4_keypad",
        config_entry=entry,
        suggested_object_id="lockly_control4_keypad",
    )
    keep = registry.async_get_or_create(
        "event",
        DOMAIN,
        f"{entry_id}-lock-event-garden_upper_lock",
        config_entry=entry,
        suggested_object_id="lockly_garden_upper_lock",
    )
    assert registry.async_get(stale.entity_id) is not None
    assert registry.async_get(keep.entity_id) is not None

    await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert registry.async_get(stale.entity_id) is None
    assert registry.async_get(keep.entity_id) is not None


@pytest.mark.enable_socket
async def test_cleanup_skipped_when_no_lock_names_resolved(
    hass: HomeAssistant, enable_custom_integrations: Any
) -> None:
    """If lock_names is empty, cleanup must not nuke existing event entities."""
    _ = enable_custom_integrations
    hass.data["lockly_skip_frontend"] = True
    hass.data["lockly_skip_mqtt"] = True
    hass.data["lockly_skip_worker"] = True
    hass.data["lockly_skip_timeout"] = True

    entry_id = "lockly_empty_entry"
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Lockly",
        entry_id=entry_id,
        data={
            CONF_NAME: "Lockly",
            CONF_FIRST_SLOT: DEFAULT_FIRST_SLOT,
            CONF_LAST_SLOT: DEFAULT_LAST_SLOT,
            CONF_MQTT_TOPIC: DEFAULT_MQTT_TOPIC,
            CONF_ENDPOINT: DEFAULT_ENDPOINT,
        },
    )
    entry.add_to_hass(hass)

    registry = er.async_get(hass)
    existing = registry.async_get_or_create(
        "event",
        DOMAIN,
        f"{entry_id}-lock-event-garden_upper_lock",
        config_entry=entry,
        suggested_object_id="lockly_garden_upper_lock",
    )

    await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert registry.async_get(existing.entity_id) is not None


@pytest.mark.enable_socket
async def test_state_dispatch_allows_lock_present_only_in_state_machine(
    hass: HomeAssistant, enable_custom_integrations: Any
) -> None:
    """Dispatch when the only signal is a `lock.*` entity in the state machine."""
    _ = enable_custom_integrations
    hass.data["lockly_skip_frontend"] = True
    hass.data["lockly_skip_mqtt"] = True
    hass.data["lockly_skip_worker"] = True
    hass.data["lockly_skip_timeout"] = True

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Lockly",
        data={
            CONF_NAME: "Lockly",
            CONF_FIRST_SLOT: DEFAULT_FIRST_SLOT,
            CONF_LAST_SLOT: DEFAULT_LAST_SLOT,
            CONF_MQTT_TOPIC: DEFAULT_MQTT_TOPIC,
            CONF_ENDPOINT: DEFAULT_ENDPOINT,
        },
    )
    entry.add_to_hass(hass)
    _register_lock_state(hass, "Front Door Lock")
    await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    manager = hass.data[DOMAIN][entry.entry_id].manager
    assert manager.lock_names == []

    action_calls: list[tuple[tuple, dict]] = []

    async def fake_action(*args: Any, **kwargs: Any) -> None:
        action_calls.append((args, kwargs))

    manager.handle_mqtt_action = fake_action

    valid = SimpleNamespace(
        topic=f"{DEFAULT_MQTT_TOPIC}/Front Door Lock",
        payload='{"action": "unlock"}',
    )
    await _handle_state_payload(manager, valid)
    assert len(action_calls) == 1
    args, kwargs = action_calls[0]
    assert args[0] == "Front Door Lock"
    assert args[1] == "unlock"
    assert kwargs.get("fire_lock_event") is True

    stranger = SimpleNamespace(
        topic=f"{DEFAULT_MQTT_TOPIC}/Entry Keypad",
        payload='{"action": "unlock"}',
    )
    await _handle_state_payload(manager, stranger)
    assert len(action_calls) == 1


@pytest.mark.enable_socket
async def test_cleanup_uses_ha_lock_registry_for_known_set(
    hass: HomeAssistant, enable_custom_integrations: Any
) -> None:
    """Cleanup keeps entities matching a current `lock.*` and drops others."""
    _ = enable_custom_integrations
    hass.data["lockly_skip_frontend"] = True
    hass.data["lockly_skip_mqtt"] = True
    hass.data["lockly_skip_worker"] = True
    hass.data["lockly_skip_timeout"] = True

    entry_id = "lockly_registry_cleanup"
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Lockly",
        entry_id=entry_id,
        data={
            CONF_NAME: "Lockly",
            CONF_FIRST_SLOT: DEFAULT_FIRST_SLOT,
            CONF_LAST_SLOT: DEFAULT_LAST_SLOT,
            CONF_MQTT_TOPIC: DEFAULT_MQTT_TOPIC,
            CONF_ENDPOINT: DEFAULT_ENDPOINT,
        },
    )
    entry.add_to_hass(hass)
    _register_lock_state(hass, "Front Door Lock")

    registry = er.async_get(hass)
    keep = registry.async_get_or_create(
        "event",
        DOMAIN,
        f"{entry_id}-lock-event-front_door_lock",
        config_entry=entry,
        suggested_object_id="lockly_front_door_lock",
    )
    stale = registry.async_get_or_create(
        "event",
        DOMAIN,
        f"{entry_id}-lock-event-control4_keypad",
        config_entry=entry,
        suggested_object_id="lockly_control4_keypad",
    )

    await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert registry.async_get(keep.entity_id) is not None
    assert registry.async_get(stale.entity_id) is None
