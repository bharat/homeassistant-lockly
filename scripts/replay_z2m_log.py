#!/usr/bin/env python3
r"""Reconstruct Lockly activity data from Zigbee2MQTT log files.

Parses z2m log lines, extracts lock action events, and writes a Home
Assistant storage file compatible with ActivityBuffer.async_load().

Usage examples::

    # Preview events from a z2m log (dry run)
    python scripts/replay_z2m_log.py z2m.log

    # Write directly to a HA store file
    python scripts/replay_z2m_log.py z2m.log \
        --store-path /config/.storage/lockly_activity.abc123

    # Provide slot-name mapping and timezone offset
    python scripts/replay_z2m_log.py z2m.log \
        --slots '{"7": "Lorena", "2": "Alice"}' \
        --tz-offset -1

Log format (z2m default)::

    [2026-02-20 10:11:46] info: \tz2m:mqtt: MQTT publish: topic \
        'zigbee2mqtt/Front Door Lock', payload '{...json...}'

    [2026-02-20 10:12:22] info: \tz2m:mqtt: MQTT publish: topic \
        'zigbee2mqtt/Front Door Lock/action', payload 'manual_lock'
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

LOCK_ACTIONS = {
    "lock",
    "unlock",
    "lock_failure_invalid_pin_or_id",
    "lock_failure_invalid_schedule",
    "unlock_failure_invalid_pin_or_id",
    "unlock_failure_invalid_schedule",
    "one_touch_lock",
    "key_lock",
    "key_unlock",
    "auto_lock",
    "schedule_lock",
    "schedule_unlock",
    "manual_lock",
    "manual_unlock",
    "non_access_user_operational_event",
}

LINE_RE = re.compile(
    r"\[(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\]\s+"
    r"info:\s+z2m:mqtt:\s+MQTT publish:\s+"
    r"topic\s+'(?P<topic>[^']+)',\s+payload\s+'(?P<payload>.*)'$"
)


def _parse_timestamp(ts_str: str, tz_offset_hours: float) -> str:
    """Convert a log timestamp string to an ISO 8601 UTC string."""
    tz = timezone(timedelta(hours=tz_offset_hours))
    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
    return ts.astimezone(UTC).isoformat()


def _parse_action_topic(
    lock_name: str, payload: str, ts_iso: str
) -> dict[str, object] | None:
    """Parse an action-topic line (plain action string payload)."""
    action = payload.strip()
    if action not in LOCK_ACTIONS:
        return None
    return {
        "lock": lock_name,
        "action": action,
        "timestamp": ts_iso,
        "_source": "action_topic",
    }


def _parse_state_topic(
    lock_name: str, payload_raw: str, ts_iso: str
) -> dict[str, object] | None:
    """Parse a state-topic line (JSON payload with action field)."""
    try:
        data = json.loads(payload_raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    action = data.get("action")
    if not action or action not in LOCK_ACTIONS:
        return None

    action_user = data.get("action_user")
    if isinstance(action_user, str) and action_user.isdigit():
        action_user = int(action_user)
    if not isinstance(action_user, int):
        action_user = None

    action_source_name = data.get("action_source_name")
    if not isinstance(action_source_name, str):
        action_source_name = None

    event: dict[str, object] = {
        "lock": lock_name,
        "action": action,
        "timestamp": ts_iso,
        "_source": "state_topic",
    }
    if action_user is not None:
        event["slot_id"] = action_user
    if action_source_name:
        event["source"] = action_source_name
    return event


def _parse_line(
    line: str,
    base_topic: str,
    tz_offset_hours: float,
) -> dict[str, object] | None:
    """Parse a single z2m log line into an activity event dict."""
    m = LINE_RE.match(line.strip())
    if not m:
        return None

    ts_iso = _parse_timestamp(m.group("ts"), tz_offset_hours)
    topic = m.group("topic")
    payload_raw = m.group("payload")

    prefix = base_topic + "/"
    if not topic.startswith(prefix):
        return None

    remainder = topic[len(prefix) :]

    if remainder.endswith("/action"):
        lock_name = remainder[: -len("/action")]
        return _parse_action_topic(lock_name, payload_raw, ts_iso)

    if "/" in remainder:
        return None

    return _parse_state_topic(remainder, payload_raw, ts_iso)


def _correlate_events(
    events: list[dict[str, object]],
    window_seconds: float = 3.0,
) -> list[dict[str, object]]:
    """Merge action-topic events into state-topic events when paired.

    When z2m fires a lock action, it publishes to both the action topic
    (plain string) and the state topic (JSON with user/source details).
    If we have both, prefer the state-topic version.  Action-topic-only
    events are kept as fallback.
    """
    state_events: list[dict[str, object]] = []
    action_events: list[dict[str, object]] = []
    for evt in events:
        if evt.get("_source") == "state_topic":
            state_events.append(evt)
        else:
            action_events.append(evt)

    matched_action_indices: set[int] = set()

    for se in state_events:
        se_ts = datetime.fromisoformat(str(se["timestamp"]))
        for i, ae in enumerate(action_events):
            if i in matched_action_indices:
                continue
            if ae["lock"] != se["lock"] or ae["action"] != se["action"]:
                continue
            ae_ts = datetime.fromisoformat(str(ae["timestamp"]))
            if abs((se_ts - ae_ts).total_seconds()) <= window_seconds:
                matched_action_indices.add(i)
                break

    result = list(state_events)
    for i, ae in enumerate(action_events):
        if i not in matched_action_indices:
            result.append(ae)

    result.sort(key=lambda e: str(e.get("timestamp", "")))
    return result


def _apply_slot_names(
    events: list[dict[str, object]],
    slots: dict[int, str],
) -> None:
    """Resolve slot_id to user_name in-place."""
    for evt in events:
        slot_id = evt.get("slot_id")
        if isinstance(slot_id, int) and slot_id in slots:
            evt["user_name"] = slots[slot_id]


def _strip_internal_keys(events: list[dict[str, object]]) -> None:
    """Remove internal metadata keys before output."""
    for evt in events:
        evt.pop("_source", None)


def parse_log(
    lines: list[str],
    *,
    base_topic: str = "zigbee2mqtt",
    tz_offset_hours: float = 0.0,
) -> list[dict[str, object]]:
    """Parse z2m log lines into a sorted list of activity events."""
    raw: list[dict[str, object]] = []
    for line in lines:
        evt = _parse_line(line, base_topic, tz_offset_hours)
        if evt is not None:
            raw.append(evt)

    return _correlate_events(raw)


def write_store(path: str, events: list[dict[str, object]]) -> None:
    """Write events to a HA .storage file, preserving envelope."""
    store_path = Path(path)
    existing: dict | None = None
    try:
        with store_path.open(encoding="utf-8") as fh:
            existing = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    if isinstance(existing, dict) and "data" in existing:
        existing["data"] = events
        output = existing
    else:
        output = {
            "version": 1,
            "minor_version": 1,
            "key": "lockly_activity",
            "data": events,
        }

    with store_path.open("w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2)
        fh.write("\n")


def main() -> None:
    """Parse z2m logs and output or store Lockly activity events."""
    parser = argparse.ArgumentParser(
        description="Reconstruct Lockly activity data from z2m logs.",
    )
    parser.add_argument("logfile", help="Path to z2m log file")
    parser.add_argument(
        "--store-path",
        help="HA .storage file to write (overwrites data field)",
    )
    parser.add_argument(
        "--base-topic",
        default="zigbee2mqtt",
        help="z2m base MQTT topic (default: zigbee2mqtt)",
    )
    parser.add_argument(
        "--slots",
        help=('JSON mapping of slot IDs to names, e.g. \'{"7": "Lorena"}\''),
    )
    parser.add_argument(
        "--tz-offset",
        type=float,
        default=0.0,
        help="Hours offset from UTC for log timestamps",
    )

    args = parser.parse_args()

    slots: dict[int, str] = {}
    if args.slots:
        raw_slots = json.loads(args.slots)
        slots = {int(k): v for k, v in raw_slots.items()}

    with Path(args.logfile).open(encoding="utf-8") as fh:
        lines = fh.readlines()

    events = parse_log(
        lines,
        base_topic=args.base_topic,
        tz_offset_hours=args.tz_offset,
    )

    _apply_slot_names(events, slots)
    _strip_internal_keys(events)

    msg = f"Parsed {len(events)} lock action events"
    sys.stderr.write(msg + "\n")

    if args.store_path:
        write_store(args.store_path, events)
        msg = f"Wrote {len(events)} events to {args.store_path}"
        sys.stderr.write(msg + "\n")
    else:
        json.dump(events, sys.stdout, indent=2)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
