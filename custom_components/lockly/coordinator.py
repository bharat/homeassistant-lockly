"""Slot coordinator for Lockly."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

if TYPE_CHECKING:
    from logging import Logger

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.storage import Store

    from .data import LocklyConfigEntry


@dataclass
class LocklySlot:
    """Lockly slot data."""

    slot: int
    name: str = ""
    pin: str = ""
    enabled: bool = False
    busy: bool = False
    status: str = ""
    last_response: dict | None = None
    last_response_ts: float | None = None


class LocklySlotCoordinator(DataUpdateCoordinator[dict[int, LocklySlot]]):
    """Coordinator for Lockly slot state."""

    config_entry: LocklyConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        store: Store,
        entry: LocklyConfigEntry,
        logger: Logger,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass=hass,
            logger=logger,
            name=entry.title,
            update_interval=None,
        )
        self._store = store
        self.config_entry = entry
        self.data = {}

    async def async_load(self) -> None:
        """Load slot state from storage."""
        stored = await self._store.async_load() or []
        self.data = {}
        for item in stored:
            if "slot" not in item:
                continue
            slot_id = int(item["slot"])
            slot = LocklySlot(**{**item, "slot": slot_id})
            self.data[slot_id] = slot
        self.async_set_updated_data(self.data)

    async def async_save(self) -> None:
        """Persist slot state to storage."""
        payload = [asdict(slot) for slot in self.data.values()]
        await self._store.async_save(payload)
