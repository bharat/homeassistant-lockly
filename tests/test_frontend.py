"""Tests for Lockly frontend registration."""

from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.lockly.const import JSMODULES, URL_BASE
from custom_components.lockly.frontend import JSModuleRegistration


class _ResourcesStub:
    """Minimal lovelace resources stub."""

    def __init__(self, items: Iterable[dict[str, Any]], *, loaded: bool = True) -> None:
        self._items = items
        self.loaded = loaded
        self.async_delete_item = AsyncMock()
        self.async_update_item = AsyncMock()
        self.async_create_item = AsyncMock()

    def async_items(self) -> Iterable[dict[str, Any]]:
        return self._items


class _LovelaceStub:
    """Minimal lovelace stub."""

    def __init__(self, resources: _ResourcesStub) -> None:
        self.mode = "storage"
        self.resources = resources


@pytest.mark.asyncio
async def test_async_register_skips_lovelace_when_disabled(hass: HomeAssistant) -> None:
    """Ensure the static path registers even without lovelace storage."""
    hass.http = SimpleNamespace(async_register_static_paths=AsyncMock())
    registration = JSModuleRegistration(hass)

    await registration.async_register()

    hass.http.async_register_static_paths.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_register_path_ignores_duplicate(hass: HomeAssistant) -> None:
    """Ensure duplicate static path registration is ignored."""
    hass.http = SimpleNamespace(
        async_register_static_paths=AsyncMock(side_effect=RuntimeError)
    )
    registration = JSModuleRegistration(hass)

    await registration.async_register()


@pytest.mark.asyncio
async def test_register_modules_updates_existing_and_cleans_legacy(
    hass: HomeAssistant,
) -> None:
    """Ensure legacy resources are removed and existing are updated."""
    module = JSMODULES[0]
    legacy = {"id": "legacy", "url": "/local/lockly-card/lockly-card.js"}
    existing = {
        "id": "existing",
        "url": f"{URL_BASE}/{module['filename']}?v=SOMETHING_BOGUS",
    }
    resources = _ResourcesStub([legacy, existing])
    hass.data["lovelace"] = _LovelaceStub(resources)
    hass.http = SimpleNamespace(async_register_static_paths=AsyncMock())
    registration = JSModuleRegistration(hass)

    await registration.async_register()

    resources.async_delete_item.assert_awaited_once_with("legacy")
    resources.async_update_item.assert_awaited_once()


@pytest.mark.asyncio
async def test_register_modules_creates_when_missing(hass: HomeAssistant) -> None:
    """Ensure modules are created when none exist."""
    resources = _ResourcesStub([])
    hass.data["lovelace"] = _LovelaceStub(resources)
    hass.http = SimpleNamespace(async_register_static_paths=AsyncMock())
    registration = JSModuleRegistration(hass)

    await registration.async_register()

    resources.async_create_item.assert_awaited_once()
