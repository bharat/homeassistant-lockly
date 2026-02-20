"""Tests for the ActivityBuffer."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.lockly.activity import ActivityBuffer, dedup_events

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


# --- Raw data preservation ---


@pytest.mark.asyncio
async def test_append_stores_raw_events(buf: ActivityBuffer) -> None:
    """All raw events are stored, even dedup-eligible ones."""
    buf.append({"lock": "Front Door", "source": "manual"}, "manual_lock")
    buf.append({"lock": "Front Door", "source": "rf"}, "lock")

    assert buf.raw_count() == 2
    assert buf.recent(max_events=10) != []


@pytest.mark.asyncio
async def test_raw_preserved_while_recent_deduplicates(buf: ActivityBuffer) -> None:
    """Buffer retains raw events; recent() returns deduped view."""
    buf.append({"lock": "Front Door", "source": "manual"}, "manual_lock")
    buf.append({"lock": "Front Door", "source": "rf"}, "lock")

    assert buf.raw_count() == 2

    recent = buf.recent(max_events=10)
    assert len(recent) == 1
    assert recent[0]["action"] == "lock"
    assert recent[0]["source"] == "automation"


@pytest.mark.asyncio
async def test_load_preserves_raw_data(hass: HomeAssistant, store: AsyncMock) -> None:
    """Loading does not modify or deduplicate stored data."""
    store.async_load.return_value = [
        {
            "lock": "Front Door",
            "action": "manual_lock",
            "source": "manual",
            "timestamp": "2026-02-20T10:12:22+00:00",
        },
        {
            "lock": "Front Door",
            "action": "lock",
            "source": "rf",
            "timestamp": "2026-02-20T10:12:23+00:00",
        },
    ]
    buf = ActivityBuffer(hass, store)
    with patch("custom_components.lockly.activity.async_call_later") as mock_later:
        await buf.async_load()
        assert mock_later.call_count == 0

    assert buf.raw_count() == 2


# --- Dedup via recent() ---


@pytest.mark.asyncio
async def test_dedup_manual_lock_then_lock_rf(buf: ActivityBuffer) -> None:
    """manual_lock followed by lock(rf) collapses into one automation event."""
    buf.append({"lock": "Front Door", "source": "manual"}, "manual_lock")
    buf.append({"lock": "Front Door", "source": "rf"}, "lock")

    recent = buf.recent(max_events=10)
    assert len(recent) == 1
    assert recent[0]["action"] == "lock"
    assert recent[0]["source"] == "automation"


@pytest.mark.asyncio
async def test_dedup_lock_rf_then_manual_lock(buf: ActivityBuffer) -> None:
    """lock(rf) followed by manual_lock collapses into one automation event."""
    buf.append({"lock": "Front Door", "source": "rf"}, "lock")
    buf.append({"lock": "Front Door", "source": "manual"}, "manual_lock")

    recent = buf.recent(max_events=10)
    assert len(recent) == 1
    assert recent[0]["action"] == "lock"
    assert recent[0]["source"] == "automation"


@pytest.mark.asyncio
async def test_dedup_preserves_user_info(buf: ActivityBuffer) -> None:
    """User info from the manual event is preserved after merge."""
    buf.append(
        {"lock": "Front Door", "source": "manual", "user_name": "Alice", "slot_id": 3},
        "manual_lock",
    )
    buf.append({"lock": "Front Door", "source": "rf"}, "lock")

    recent = buf.recent(max_events=10)
    assert len(recent) == 1
    assert recent[0]["user_name"] == "Alice"
    assert recent[0]["slot_id"] == 3
    assert recent[0]["source"] == "automation"


@pytest.mark.asyncio
async def test_dedup_unlock_pair(buf: ActivityBuffer) -> None:
    """manual_unlock + unlock(rf) merges the same way."""
    buf.append({"lock": "Front Door", "source": "manual"}, "manual_unlock")
    buf.append({"lock": "Front Door", "source": "rf"}, "unlock")

    recent = buf.recent(max_events=10)
    assert len(recent) == 1
    assert recent[0]["action"] == "unlock"
    assert recent[0]["source"] == "automation"


@pytest.mark.asyncio
async def test_no_dedup_different_locks(buf: ActivityBuffer) -> None:
    """Events for different locks are never merged."""
    buf.append({"lock": "Front Door", "source": "manual"}, "manual_lock")
    buf.append({"lock": "Back Door", "source": "rf"}, "lock")

    recent = buf.recent(max_events=10)
    assert len(recent) == 2


@pytest.mark.asyncio
async def test_no_dedup_unrelated_actions(buf: ActivityBuffer) -> None:
    """Non-complementary actions on the same lock are not merged."""
    buf.append({"lock": "Front Door"}, "unlock")
    buf.append({"lock": "Front Door"}, "lock")

    recent = buf.recent(max_events=10)
    assert len(recent) == 2


@pytest.mark.asyncio
async def test_standalone_manual_lock_kept(buf: ActivityBuffer) -> None:
    """A single manual_lock without a following base lock stays."""
    buf.append({"lock": "Front Door", "source": "manual"}, "manual_lock")

    recent = buf.recent(max_events=10)
    assert len(recent) == 1
    assert recent[0]["action"] == "manual_lock"
    assert recent[0]["source"] == "manual"


@pytest.mark.asyncio
async def test_no_dedup_one_touch_lock(buf: ActivityBuffer) -> None:
    """one_touch_lock is a deliberate physical action, not deduped with lock."""
    buf.append({"lock": "Front Door", "source": "manual"}, "one_touch_lock")
    buf.append({"lock": "Front Door", "source": "remote"}, "lock")

    recent = buf.recent(max_events=10)
    assert len(recent) == 2
    assert recent[0]["action"] == "lock"
    assert recent[1]["action"] == "one_touch_lock"


@pytest.mark.asyncio
async def test_dedup_same_action_lock_lock(buf: ActivityBuffer) -> None:
    """Two lock commands within the window collapse, keeping the first."""
    buf.append({"lock": "Front Door", "source": "automation"}, "lock")
    buf.append({"lock": "Front Door", "source": "remote"}, "lock")

    recent = buf.recent(max_events=10)
    assert len(recent) == 1
    assert recent[0]["action"] == "lock"
    assert recent[0]["source"] == "automation"


@pytest.mark.asyncio
async def test_dedup_same_action_preserves_user(buf: ActivityBuffer) -> None:
    """Same-action dedup preserves user info from the earlier event."""
    buf.append(
        {"lock": "Front Door", "source": "keypad", "user_name": "Alice"},
        "unlock",
    )
    buf.append({"lock": "Front Door", "source": "manual"}, "unlock")

    recent = buf.recent(max_events=10)
    assert len(recent) == 1
    assert recent[0]["user_name"] == "Alice"


@pytest.mark.asyncio
async def test_dedup_manual_lock_remote_source(buf: ActivityBuffer) -> None:
    """manual_lock + lock(remote) treated the same as rf."""
    buf.append({"lock": "Front Door", "source": "manual"}, "manual_lock")
    buf.append({"lock": "Front Door", "source": "remote"}, "lock")

    recent = buf.recent(max_events=10)
    assert len(recent) == 1
    assert recent[0]["action"] == "lock"
    assert recent[0]["source"] == "automation"


# --- Dedup on loaded data (via recent) ---


@pytest.mark.asyncio
async def test_loaded_data_deduped_in_recent(
    hass: HomeAssistant, store: AsyncMock
) -> None:
    """Persisted manual_lock + lock(rf) pair is collapsed by recent()."""
    store.async_load.return_value = [
        {
            "lock": "Front Door",
            "action": "manual_lock",
            "source": "manual",
            "timestamp": "2026-02-20T10:12:22+00:00",
        },
        {
            "lock": "Front Door",
            "action": "lock",
            "source": "rf",
            "timestamp": "2026-02-20T10:12:23+00:00",
        },
    ]
    buf = ActivityBuffer(hass, store)
    await buf.async_load()

    recent = buf.recent(max_events=10)
    assert len(recent) == 1
    assert recent[0]["action"] == "lock"
    assert recent[0]["source"] == "automation"


@pytest.mark.asyncio
async def test_loaded_same_action_deduped(
    hass: HomeAssistant, store: AsyncMock
) -> None:
    """Persisted duplicate lock commands collapse, keeping the first."""
    store.async_load.return_value = [
        {
            "lock": "Front Door",
            "action": "lock",
            "source": "automation",
            "timestamp": "2026-02-20T10:12:22+00:00",
        },
        {
            "lock": "Front Door",
            "action": "lock",
            "source": "remote",
            "timestamp": "2026-02-20T10:12:23+00:00",
        },
    ]
    buf = ActivityBuffer(hass, store)
    await buf.async_load()

    recent = buf.recent(max_events=10)
    assert len(recent) == 1
    assert recent[0]["action"] == "lock"
    assert recent[0]["source"] == "automation"


@pytest.mark.asyncio
async def test_loaded_one_touch_lock_not_deduped(
    hass: HomeAssistant, store: AsyncMock
) -> None:
    """Persisted one_touch_lock + lock(remote) are kept separate."""
    store.async_load.return_value = [
        {
            "lock": "Front Door",
            "action": "one_touch_lock",
            "source": "manual",
            "timestamp": "2026-02-20T10:12:22+00:00",
        },
        {
            "lock": "Front Door",
            "action": "lock",
            "source": "remote",
            "timestamp": "2026-02-20T10:12:23+00:00",
        },
    ]
    buf = ActivityBuffer(hass, store)
    await buf.async_load()

    recent = buf.recent(max_events=10)
    assert len(recent) == 2
    assert recent[0]["action"] == "lock"
    assert recent[1]["action"] == "one_touch_lock"


@pytest.mark.asyncio
async def test_loaded_clean_data_unchanged(
    hass: HomeAssistant, store: AsyncMock
) -> None:
    """Already-clean data passes through unchanged."""
    events = [
        {
            "lock": "Front Door",
            "action": "unlock",
            "source": "keypad",
            "user_name": "Alice",
            "timestamp": "2026-02-20T10:11:46+00:00",
        },
        {
            "lock": "Front Door",
            "action": "lock",
            "source": "automation",
            "timestamp": "2026-02-20T10:12:23+00:00",
        },
    ]
    store.async_load.return_value = list(events)
    buf = ActivityBuffer(hass, store)
    await buf.async_load()

    recent = buf.recent(max_events=10)
    assert len(recent) == 2
    assert recent[0]["action"] == "lock"
    assert recent[1]["action"] == "unlock"


# --- dedup_events() unit tests ---


def test_dedup_events_empty() -> None:
    assert dedup_events([]) == []


def test_dedup_events_single() -> None:
    events = [{"action": "lock", "lock": "A", "timestamp": "2026-01-01T00:00:00+00:00"}]
    assert dedup_events(events) == events


def test_dedup_events_physical_base_pair() -> None:
    events = [
        {
            "lock": "A",
            "action": "manual_lock",
            "source": "manual",
            "timestamp": "2026-01-01T00:00:00+00:00",
        },
        {
            "lock": "A",
            "action": "lock",
            "source": "rf",
            "timestamp": "2026-01-01T00:00:01+00:00",
        },
    ]
    result = dedup_events(events)
    assert len(result) == 1
    assert result[0]["action"] == "lock"
    assert result[0]["source"] == "automation"
