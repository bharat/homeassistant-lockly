"""Custom types for Lockly."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.loader import Integration

    from .coordinator import LocklySlotCoordinator
    from .manager import LocklyManager


type LocklyConfigEntry = ConfigEntry[LocklyData]


@dataclass
class LocklyData:
    """Data for the Lockly integration."""

    coordinator: LocklySlotCoordinator
    manager: LocklyManager
    integration: Integration
    subscriptions: list[Callable[[], None]] | None = None
