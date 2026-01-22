"""Tests for Lockly entity base class."""

# ruff: noqa: S101

from collections.abc import Callable
from typing import Any

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lockly.const import DOMAIN
from custom_components.lockly.entity import LocklyEntity


class _CoordinatorStub:
    """Minimal coordinator stub for CoordinatorEntity."""

    def __init__(self, config_entry: MockConfigEntry) -> None:
        self.config_entry = config_entry
        self.data = {}
        self.last_update_success = True

    def async_add_listener(self, _listener: Callable[..., Any]) -> Callable[[], None]:
        return lambda: None

    async def async_request_refresh(self) -> None:
        return None


def test_lockly_entity_sets_device_info() -> None:
    """Verify the base entity wires device info and unique ID."""
    entry = MockConfigEntry(domain=DOMAIN, title="Lockly")
    coordinator = _CoordinatorStub(entry)
    entity = LocklyEntity(coordinator)

    assert entity.unique_id == entry.entry_id
    assert entity.device_info is not None
    assert entity.device_info["identifiers"] == {(entry.domain, entry.entry_id)}
