"""Custom types for integration_blueprint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.loader import Integration

    from .api import LocklyApiClient
    from .coordinator import LocklyDataUpdateCoordinator


type LocklyConfigEntry = ConfigEntry[LocklyData]


@dataclass
class LocklyData:
    """Data for the Lockly integration."""

    client: LocklyApiClient
    coordinator: LocklyDataUpdateCoordinator
    integration: Integration
