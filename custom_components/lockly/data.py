"""Custom types for Lockly."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
