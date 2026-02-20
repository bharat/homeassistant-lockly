"""Tests for the z2m log replay script."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from scripts.replay_z2m_log import (
    _correlate_events,
    parse_log,
    write_store,
)

if TYPE_CHECKING:
    from pathlib import Path

_STATE_JSON = (
    '{"action":"unlock","action_source":0,'
    '"action_source_name":"keypad","action_user":7,'
    '"auto_relock_time":180,"battery":98,"battery_low":false,'
    '"linkquality":84,"lock_state":"locked",'
    '"state":"LOCK"}'
)

SAMPLE_STATE_LINE = (
    "[2026-02-20 10:11:46] info: \tz2m:mqtt: MQTT publish: "
    "topic 'zigbee2mqtt/Front Door Lock', "
    f"payload '{_STATE_JSON}'"
)

SAMPLE_ACTION_LINE = (
    "[2026-02-20 10:12:22] info: \tz2m:mqtt: MQTT publish: "
    "topic 'zigbee2mqtt/Front Door Lock/action', "
    "payload 'manual_lock'"
)

_NOACTION_JSON = (
    '{"action_source_name":null,"action_user":null,'
    '"battery":98,"lock_state":"locked","state":"LOCK"}'
)

_MANUAL_LOCK_JSON = (
    '{"action":"manual_lock","action_source":2,'
    '"action_source_name":"manual","action_user":null,'
    '"lock_state":"locked","state":"LOCK"}'
)


def _z2m_action_line(ts: str, lock: str, action: str) -> str:
    return (
        f"[{ts}] info: \tz2m:mqtt: MQTT publish: "
        f"topic 'zigbee2mqtt/{lock}/action', "
        f"payload '{action}'"
    )


def _z2m_state_line(ts: str, lock: str, payload_json: str) -> str:
    return (
        f"[{ts}] info: \tz2m:mqtt: MQTT publish: "
        f"topic 'zigbee2mqtt/{lock}', "
        f"payload '{payload_json}'"
    )


# -- parse_log -------------------------------------------------------


def test_state_topic_with_action() -> None:
    events = parse_log([SAMPLE_STATE_LINE], tz_offset_hours=0.0)
    assert len(events) == 1
    evt = events[0]
    assert evt["lock"] == "Front Door Lock"
    assert evt["action"] == "unlock"
    assert evt["slot_id"] == 7
    assert evt["source"] == "keypad"


def test_action_topic() -> None:
    events = parse_log([SAMPLE_ACTION_LINE], tz_offset_hours=0.0)
    assert len(events) == 1
    evt = events[0]
    assert evt["lock"] == "Front Door Lock"
    assert evt["action"] == "manual_lock"
    assert "slot_id" not in evt
    assert "source" not in evt


def test_tz_offset() -> None:
    events_utc = parse_log([SAMPLE_STATE_LINE], tz_offset_hours=0.0)
    events_est = parse_log([SAMPLE_STATE_LINE], tz_offset_hours=-5.0)
    ts_utc = str(events_utc[0]["timestamp"])
    ts_est = str(events_est[0]["timestamp"])
    assert ts_utc != ts_est
    assert "10:11:46" in ts_utc
    assert "15:11:46" in ts_est


def test_ignores_non_action_state() -> None:
    line = _z2m_state_line(
        "2026-02-20 13:24:19",
        "Front Door Lock",
        _NOACTION_JSON,
    )
    assert parse_log([line]) == []


def test_ignores_unrecognized_action() -> None:
    line = _z2m_action_line(
        "2026-02-20 10:00:00",
        "Front Door Lock",
        "bogus_event",
    )
    assert parse_log([line]) == []


def test_ignores_non_matching_lines() -> None:
    events = parse_log(
        [
            "some random line",
            "",
            "[2026-02-20 10:00:00] debug: something",
        ]
    )
    assert events == []


def test_mixed_state_and_action_lines() -> None:
    state_line = _z2m_state_line(
        "2026-02-20 10:12:22",
        "Front Door Lock",
        _MANUAL_LOCK_JSON,
    )
    action_line = _z2m_action_line(
        "2026-02-20 10:12:22",
        "Front Door Lock",
        "manual_lock",
    )
    events = parse_log([state_line, action_line])
    assert len(events) == 1
    assert events[0]["source"] == "manual"


def test_custom_base_topic() -> None:
    line = (
        "[2026-02-20 10:00:00] info: \tz2m:mqtt: "
        "MQTT publish: topic 'z2m/My Lock/action', "
        "payload 'lock'"
    )
    events = parse_log([line], base_topic="z2m")
    assert len(events) == 1
    assert events[0]["lock"] == "My Lock"


# -- _correlate_events -----------------------------------------------


def test_state_preferred_over_action() -> None:
    state = {
        "lock": "Front Door Lock",
        "action": "lock",
        "timestamp": "2026-02-20T10:12:22+00:00",
        "source": "rf",
        "_source": "state_topic",
    }
    action = {
        "lock": "Front Door Lock",
        "action": "lock",
        "timestamp": "2026-02-20T10:12:22+00:00",
        "_source": "action_topic",
    }
    result = _correlate_events([state, action])
    assert len(result) == 1
    assert result[0]["source"] == "rf"


def test_unmatched_action_kept() -> None:
    action = {
        "lock": "Back Door Lock",
        "action": "unlock",
        "timestamp": "2026-02-20T10:00:00+00:00",
        "_source": "action_topic",
    }
    result = _correlate_events([action])
    assert len(result) == 1


def test_different_locks_not_correlated() -> None:
    state = {
        "lock": "Front Door Lock",
        "action": "lock",
        "timestamp": "2026-02-20T10:12:22+00:00",
        "_source": "state_topic",
    }
    action = {
        "lock": "Back Door Lock",
        "action": "lock",
        "timestamp": "2026-02-20T10:12:22+00:00",
        "_source": "action_topic",
    }
    result = _correlate_events([state, action])
    assert len(result) == 2


# -- write_store ------------------------------------------------------


def test_write_store_creates_new_file(tmp_path: Path) -> None:
    events = [
        {
            "lock": "Test",
            "action": "lock",
            "timestamp": "2026-01-01T00:00:00+00:00",
        }
    ]
    path = tmp_path / "store.json"
    write_store(str(path), events)
    data = json.loads(path.read_text())
    assert data["version"] == 1
    assert data["data"] == events


def test_write_store_preserves_envelope(tmp_path: Path) -> None:
    envelope = {
        "version": 1,
        "minor_version": 1,
        "key": "lockly_activity.abc123",
        "data": [{"old": "data"}],
    }
    events = [
        {
            "lock": "Test",
            "action": "lock",
            "timestamp": "2026-01-01T00:00:00+00:00",
        }
    ]
    path = tmp_path / "store.json"
    path.write_text(json.dumps(envelope))
    write_store(str(path), events)
    data = json.loads(path.read_text())
    assert data["key"] == "lockly_activity.abc123"
    assert data["data"] == events


# -- full pipeline ----------------------------------------------------


def test_user_sample_logs() -> None:
    """Parse the log lines from the conversation."""
    lock = "Front Door Lock"
    lines = [
        _z2m_action_line("2026-02-20 13:24:13", lock, "lock"),
        _z2m_state_line("2026-02-20 13:24:19", lock, _NOACTION_JSON),
        _z2m_state_line("2026-02-20 13:32:55", lock, _NOACTION_JSON),
        _z2m_action_line("2026-02-20 10:12:22", lock, "manual_lock"),
        _z2m_action_line("2026-02-20 10:11:46", lock, "unlock"),
        _z2m_action_line("2026-02-20 10:12:22", lock, "manual_lock"),
        _z2m_action_line("2026-02-20 10:12:23", lock, "lock"),
        _z2m_action_line("2026-02-20 12:33:21", lock, "manual_unlock"),
        _z2m_action_line("2026-02-20 12:35:14", lock, "manual_lock"),
    ]

    events = parse_log(lines, tz_offset_hours=0.0)

    actions = [(e["action"], e["lock"]) for e in events]
    assert ("unlock", lock) in actions
    assert ("manual_lock", lock) in actions
    assert ("lock", lock) in actions
    assert ("manual_unlock", lock) in actions

    timestamps = [str(e["timestamp"]) for e in events]
    assert all("13:32:55" not in ts for ts in timestamps)

    assert timestamps == sorted(timestamps)
