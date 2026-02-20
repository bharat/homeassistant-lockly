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
DEDUP_WINDOW_PHYSICAL = 60

_PHYSICAL_TO_BASE: dict[str, str] = {
    "manual_lock": "lock",
    "manual_unlock": "unlock",
}

_DELIBERATE_TO_BASE: dict[str, str] = {
    "one_touch_lock": "lock",
}

_AUTOMATION_SOURCES: set[str] = {"rf", "remote"}


def _within_window(
    prev: dict[str, object],
    curr: dict[str, object],
    window: float = DEDUP_WINDOW_SECONDS,
) -> bool:
    """Check whether two events are for the same lock within *window* seconds."""
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
    return abs((curr_time - prev_time).total_seconds()) <= window


def _merge_keep_first(
    prev: dict[str, object], curr: dict[str, object]
) -> dict[str, object]:
    """Merge two events, keeping prev as canonical and pulling user info."""
    merged = {**prev}
    if not merged.get("user_name") and curr.get("user_name"):
        merged["user_name"] = curr["user_name"]
    if merged.get("slot_id") is None and curr.get("slot_id") is not None:
        merged["slot_id"] = curr["slot_id"]
    return merged


def _try_merge(
    prev: dict[str, object], curr: dict[str, object]
) -> dict[str, object] | None:
    """Merge two adjacent events if they are redundant.

    Cases 1-3 handle firmware echoes and exact repeats within a narrow
    window.  Case 4 handles deliberate physical actions (one_touch_lock)
    followed by a redundant automation lock within a wider window.
    """
    prev_action = prev.get("action")
    curr_action = curr.get("action")

    if _within_window(prev, curr):
        # Case 1: curr is firmware echo, prev is the base action
        base_of_curr = _PHYSICAL_TO_BASE.get(curr_action)
        if base_of_curr and prev_action == base_of_curr:
            merged = _merge_keep_first(prev, curr)
            if merged.get("source") in _AUTOMATION_SOURCES:
                merged["source"] = "automation"
            return merged

        # Case 2: curr is base action, prev is firmware echo
        if _PHYSICAL_TO_BASE.get(prev_action) == curr_action:
            source = curr.get("source")
            if source in _AUTOMATION_SOURCES:
                source = "automation"
            merged = {**prev, **curr}
            if source:
                merged["source"] = source
            return merged

        # Case 3: exact same action repeated — keep the first
        if prev_action == curr_action:
            return _merge_keep_first(prev, curr)

    # Case 4: deliberate physical action + redundant base (wider window)
    if _DELIBERATE_TO_BASE.get(prev_action) == curr_action and _within_window(
        prev, curr, DEDUP_WINDOW_PHYSICAL
    ):
        return _merge_keep_first(prev, curr)

    return None


def dedup_events(
    events: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Collapse redundant adjacent events using stored timestamps.

    This is a pure presentation-layer transform: the source list is not
    modified and a new list is returned.
    """
    if not events:
        return events
    result: list[dict[str, object]] = [events[0]]
    for evt in events[1:]:
        merged = _try_merge(result[-1], evt)
        if merged is not None:
            result[-1] = merged
        else:
            result.append(evt)
    return result


class ActivityBuffer:
    """Persisted ring buffer of lock activity events.

    Raw events are always stored as-is.  Deduplication is applied at
    read time in ``recent()`` so the original data is never lost.
    """

    def __init__(self, hass: HomeAssistant, store: Store | None = None) -> None:
        """Initialize the buffer."""
        self._hass = hass
        self._store = store
        self._buffer: deque[dict[str, object]] = deque(maxlen=MAX_EVENTS)
        self._save_unsub: CALLBACK_TYPE | None = None

    def append(self, event_data: dict[str, object], action: str) -> None:
        """Append a raw event and schedule a save."""
        self._buffer.append(
            {
                **event_data,
                "action": action,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        self._schedule_save()

    def recent(self, max_events: int = 20) -> list[dict[str, object]]:
        """Return recent events newest-first, with dedup applied."""
        events = list(self._buffer)
        deduped = dedup_events(events)
        deduped.reverse()
        return deduped[:max_events]

    def raw_count(self) -> int:
        """Return the number of raw (non-deduped) events in the buffer."""
        return len(self._buffer)

    async def async_load(self) -> None:
        """Load persisted raw events into the buffer."""
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
