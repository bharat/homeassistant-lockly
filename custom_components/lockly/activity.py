"""Activity ring buffer with persistence for Lockly."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from homeassistant.helpers.event import async_call_later

if TYPE_CHECKING:
    from homeassistant.core import CALLBACK_TYPE, HomeAssistant
    from homeassistant.helpers.storage import Store

MAX_EVENTS = 100
DEDUP_WINDOW_SECONDS = 5

_MANUAL_TO_BASE: dict[str, str] = {
    "manual_lock": "lock",
    "manual_unlock": "unlock",
}
_BASE_TO_MANUAL: dict[str, str] = {v: k for k, v in _MANUAL_TO_BASE.items()}


class ActivityBuffer:
    """Persisted ring buffer of lock activity events."""

    def __init__(self, hass: HomeAssistant, store: Store | None = None) -> None:
        """Initialize the buffer."""
        self._hass = hass
        self._store = store
        self._buffer: deque[dict[str, object]] = deque(maxlen=MAX_EVENTS)
        self._save_unsub: CALLBACK_TYPE | None = None

    def append(self, event_data: dict[str, object], action: str) -> None:
        """Append an event, deduplicating rapid manual+base lock pairs."""
        if self._try_merge(event_data, action):
            return
        self._buffer.append(
            {
                **event_data,
                "action": action,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        self._schedule_save()

    def _dedup_candidate(self, lock_name: object) -> dict[str, object] | None:
        """Return the previous event if it can be merged with a new one.

        Returns ``None`` when the buffer is empty, the previous event is
        for a different lock, or the timestamp is outside the dedup window.
        """
        if not self._buffer:
            return None
        last = self._buffer[-1]
        if last.get("lock") != lock_name:
            return None
        last_ts = last.get("timestamp")
        if not last_ts or not isinstance(last_ts, str):
            return None
        try:
            last_time = datetime.fromisoformat(last_ts)
        except (ValueError, TypeError):
            return None
        if (datetime.now(UTC) - last_time).total_seconds() > DEDUP_WINDOW_SECONDS:
            return None
        return last

    def _try_merge(self, event_data: dict[str, object], action: str) -> bool:
        """Merge manual_lock+lock (or unlock) pairs within a time window.

        When a Zigbee command locks/unlocks the door, the lock firmware
        reports both a manual_* action (physical mechanism) and the base
        action (rf command confirmation) within seconds.  Collapsing them
        avoids duplicate rows in the activity card and lets us label the
        result as *automation* when the source is ``rf``.
        """
        last = self._dedup_candidate(event_data.get("lock"))
        if last is None:
            return False

        last_action = last.get("action")

        # Case 1: new event is manual_lock/unlock, previous is base lock/unlock
        base_of_new = _MANUAL_TO_BASE.get(action)
        if base_of_new and last_action == base_of_new:
            if last.get("source") == "rf":
                last["source"] = "automation"
            if not last.get("user_name") and event_data.get("user_name"):
                last["user_name"] = event_data["user_name"]
            if last.get("slot_id") is None and event_data.get("slot_id") is not None:
                last["slot_id"] = event_data["slot_id"]
            self._schedule_save()
            return True

        # Case 2: new event is base lock/unlock, previous is manual_lock/unlock
        manual_of_new = _BASE_TO_MANUAL.get(action)
        if manual_of_new and last_action == manual_of_new:
            source = event_data.get("source")
            if source == "rf":
                source = "automation"
            merged = {
                **last,
                **event_data,
                "action": action,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            if source:
                merged["source"] = source
            self._buffer[-1] = merged
            self._schedule_save()
            return True

        return False

    def recent(self, max_events: int = 20) -> list[dict[str, object]]:
        """Return recent events, newest first."""
        events = list(self._buffer)
        events.reverse()
        return events[:max_events]

    async def async_load(self) -> None:
        """Load persisted events into the in-memory buffer."""
        if self._store is None:
            return
        data = await self._store.async_load()
        if data and isinstance(data, list):
            self._buffer.extend(data)

    async def _async_save(self, *_: object) -> None:
        """Persist the current buffer to disk."""
        self._save_unsub = None
        if self._store is None:
            return
        await self._store.async_save(list(self._buffer))

    def _schedule_save(self) -> None:
        """Debounce saves to at most once per second."""
        if self._save_unsub is not None:
            return
        self._save_unsub = async_call_later(self._hass, 1, self._async_save)
