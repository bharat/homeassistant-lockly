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

_PHYSICAL_TO_BASE: dict[str, str] = {
    "manual_lock": "lock",
    "manual_unlock": "unlock",
}

_AUTOMATION_SOURCES: set[str] = {"rf", "remote"}


def _within_stored_window(prev: dict[str, object], curr: dict[str, object]) -> bool:
    """Check whether two stored events are for the same lock within the dedup window."""
    if prev.get("lock") != curr.get("lock"):
        return False
    prev_ts = prev.get("timestamp")
    curr_ts = curr.get("timestamp")
    if not isinstance(prev_ts, str) or not isinstance(curr_ts, str):
        return False
    try:
        prev_time = datetime.fromisoformat(prev_ts)
        curr_time = datetime.fromisoformat(curr_ts)
    except (ValueError, TypeError):
        return False
    return abs((curr_time - prev_time).total_seconds()) <= DEDUP_WINDOW_SECONDS


def _try_merge_stored(
    prev: dict[str, object], curr: dict[str, object]
) -> dict[str, object] | None:
    """Merge two adjacent stored events if they form a physical+base pair.

    Returns the merged event, or ``None`` if they cannot be merged.
    """
    if not _within_stored_window(prev, curr):
        return None

    prev_action = prev.get("action")
    curr_action = curr.get("action")

    # Case 1: curr is physical variant, prev is the base action
    base_of_curr = _PHYSICAL_TO_BASE.get(curr_action)
    if base_of_curr and prev_action == base_of_curr:
        merged = {**prev}
        if merged.get("source") in _AUTOMATION_SOURCES:
            merged["source"] = "automation"
        if not merged.get("user_name") and curr.get("user_name"):
            merged["user_name"] = curr["user_name"]
        if merged.get("slot_id") is None and curr.get("slot_id") is not None:
            merged["slot_id"] = curr["slot_id"]
        return merged

    # Case 2: curr is base action, prev is a physical variant
    if _PHYSICAL_TO_BASE.get(prev_action) == curr_action:
        source = curr.get("source")
        if source in _AUTOMATION_SOURCES:
            source = "automation"
        merged = {**prev, **curr}
        if source:
            merged["source"] = source
        return merged

    return None


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
        """Merge physical+base lock pairs within a time window.

        When a Zigbee command locks/unlocks the door, the lock firmware
        reports both a physical action (manual_lock, one_touch_lock, …)
        and the base action (rf/remote command confirmation) within
        seconds.  Collapsing them avoids duplicate rows in the activity
        card and lets us label the result as *automation*.
        """
        last = self._dedup_candidate(event_data.get("lock"))
        if last is None:
            return False

        last_action = last.get("action")

        # Case 1: new event is a physical variant, previous is base
        base_of_new = _PHYSICAL_TO_BASE.get(action)
        if base_of_new and last_action == base_of_new:
            if last.get("source") in _AUTOMATION_SOURCES:
                last["source"] = "automation"
            if not last.get("user_name") and event_data.get("user_name"):
                last["user_name"] = event_data["user_name"]
            if last.get("slot_id") is None and event_data.get("slot_id") is not None:
                last["slot_id"] = event_data["slot_id"]
            self._schedule_save()
            return True

        # Case 2: new event is base action, previous is physical variant
        if _PHYSICAL_TO_BASE.get(last_action) == action:
            source = event_data.get("source")
            if source in _AUTOMATION_SOURCES:
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

    @staticmethod
    def _dedup_events(
        events: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        """Deduplicate physical+base lock pairs using stored timestamps."""
        if not events:
            return events
        result: list[dict[str, object]] = [events[0]]
        for evt in events[1:]:
            merged = _try_merge_stored(result[-1], evt)
            if merged is not None:
                result[-1] = merged
            else:
                result.append(evt)
        return result

    async def async_load(self) -> None:
        """Load persisted events, deduplicating stale pairs on the fly."""
        if self._store is None:
            return
        data = await self._store.async_load()
        if data and isinstance(data, list):
            clean = self._dedup_events(data)
            self._buffer.extend(clean)
            if len(clean) < len(data):
                self._schedule_save()

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
