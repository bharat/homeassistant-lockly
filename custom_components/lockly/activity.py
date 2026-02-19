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


class ActivityBuffer:
    """Persisted ring buffer of lock activity events."""

    def __init__(self, hass: HomeAssistant, store: Store | None = None) -> None:
        """Initialize the buffer."""
        self._hass = hass
        self._store = store
        self._buffer: deque[dict[str, object]] = deque(maxlen=MAX_EVENTS)
        self._save_unsub: CALLBACK_TYPE | None = None

    def append(self, event_data: dict[str, object], action: str) -> None:
        """Append an event and schedule a debounced save."""
        self._buffer.append(
            {
                **event_data,
                "action": action,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        self._schedule_save()

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
