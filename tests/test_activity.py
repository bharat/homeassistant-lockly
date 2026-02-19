"""Tests for the ActivityBuffer."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.lockly.activity import ActivityBuffer

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@pytest.fixture
def store() -> AsyncMock:
    mock = AsyncMock()
    mock.async_load.return_value = None
    return mock


@pytest.fixture
def buf(hass: HomeAssistant, store: AsyncMock) -> ActivityBuffer:
    return ActivityBuffer(hass, store)


@pytest.mark.asyncio
async def test_append_and_recent(buf: ActivityBuffer) -> None:
    buf.append({"lock": "Front Door"}, "unlock")
    buf.append({"lock": "Back Door"}, "lock")

    recent = buf.recent(max_events=10)
    assert len(recent) == 2
    assert recent[0]["lock"] == "Back Door"
    assert recent[0]["action"] == "lock"
    assert recent[1]["lock"] == "Front Door"
    assert "timestamp" in recent[0]


@pytest.mark.asyncio
async def test_recent_limit(buf: ActivityBuffer) -> None:
    for i in range(10):
        buf.append({"lock": f"Lock {i}"}, "unlock")

    recent = buf.recent(max_events=3)
    assert len(recent) == 3
    assert recent[0]["lock"] == "Lock 9"


@pytest.mark.asyncio
async def test_load_persisted_data(hass: HomeAssistant, store: AsyncMock) -> None:
    store.async_load.return_value = [
        {
            "lock": "Saved",
            "action": "unlock",
            "timestamp": "2025-01-01T00:00:00+00:00",
        }
    ]
    buf = ActivityBuffer(hass, store)
    await buf.async_load()

    recent = buf.recent()
    assert len(recent) == 1
    assert recent[0]["lock"] == "Saved"


@pytest.mark.asyncio
async def test_load_empty_store(buf: ActivityBuffer, store: AsyncMock) -> None:
    store.async_load.return_value = None
    await buf.async_load()
    assert buf.recent() == []


@pytest.mark.asyncio
async def test_no_store(hass: HomeAssistant) -> None:
    buf = ActivityBuffer(hass, store=None)
    buf.append({"lock": "Test"}, "lock")
    assert len(buf.recent()) == 1
    await buf.async_load()
    assert len(buf.recent()) == 1


@pytest.mark.asyncio
async def test_save_debounced(buf: ActivityBuffer) -> None:
    with patch("custom_components.lockly.activity.async_call_later") as mock_later:
        buf.append({"lock": "A"}, "lock")
        assert mock_later.call_count == 1
        buf.append({"lock": "B"}, "unlock")
        assert mock_later.call_count == 1
