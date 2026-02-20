"""Describe Lockly logbook events."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.core import Event, HomeAssistant, callback

if TYPE_CHECKING:
    from collections.abc import Callable

from .const import DOMAIN

EVENT_LOCKLY_LOCK_ACTIVITY = "lockly_lock_activity"

SOURCE_LABELS: dict[str, str] = {
    "keypad": "keypad",
    "rfid": "RFID",
    "manual": "manual",
    "rf": "automation",
    "remote": "automation",
    "automation": "automation",
}

ACTION_LABELS: dict[str, str] = {
    "lock": "locked",
    "unlock": "unlocked",
    "auto_lock": "auto-locked",
    "key_lock": "locked with key",
    "key_unlock": "unlocked with key",
    "manual_lock": "locked",
    "manual_unlock": "unlocked",
    "one_touch_lock": "one-touch locked",
    "schedule_lock": "schedule locked",
    "schedule_unlock": "schedule unlocked",
}


@callback
def async_describe_events(
    _hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, str]]], None],
) -> None:
    """Describe lockly logbook events."""

    @callback
    def _describe_lockly_event(event: Event) -> dict[str, str]:
        data = event.data
        lock = data.get("lock", "Lock")
        action = data.get("action", "unknown")
        label = ACTION_LABELS.get(action, action.replace("_", " "))

        user = data.get("user_name")
        if not user:
            slot_id = data.get("slot_id")
            user = f"Slot {slot_id}" if slot_id is not None else None

        source = data.get("source")
        source_label = SOURCE_LABELS.get(source, source) if source else None

        parts = [label]
        if user:
            parts.append(f"by {user}")
        if source_label:
            parts.append(f"via {source_label}")

        return {
            LOGBOOK_ENTRY_NAME: lock,
            LOGBOOK_ENTRY_MESSAGE: " ".join(parts),
        }

    async_describe_event(DOMAIN, EVENT_LOCKLY_LOCK_ACTIVITY, _describe_lockly_event)
