#!/usr/bin/env python3
# ruff: noqa: T201
"""Seed config/.storage/core.config_entries with an MQTT entry for dev use.

Hooked into scripts/develop ahead of `hass` so a fresh devcontainer comes
up already pointing at the local mosquitto broker, skipping the manual
"Settings > Devices & Services > Add Integration > MQTT" click-through
after onboarding completes.

Idempotent: if an MQTT entry already exists in core.config_entries, do
nothing. Safe to leave wired into scripts/develop permanently.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
STORAGE_DIR = CONFIG_DIR / ".storage"
ENTRIES_PATH = STORAGE_DIR / "core.config_entries"

# Crockford base32, matching homeassistant.util.ulid.ulid_now() so the entry
# id we generate is indistinguishable from one HA would have written itself.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _ulid() -> str:
    ts_ms = int(time.time() * 1000)
    rand = int.from_bytes(os.urandom(10), "big")
    val = (ts_ms << 80) | rand
    out: list[str] = []
    for _ in range(26):
        out.append(_CROCKFORD[val & 0x1F])
        val >>= 5
    return "".join(reversed(out))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_mqtt_entry() -> dict:
    now = _now()
    return {
        "created_at": now,
        "data": {"broker": "localhost", "port": 1883},
        "disabled_by": None,
        "discovery_keys": {},
        "domain": "mqtt",
        "entry_id": _ulid(),
        "minor_version": 1,
        "modified_at": now,
        "options": {},
        "pref_disable_new_entities": False,
        "pref_disable_polling": False,
        "source": "user",
        "subentries": [],
        "title": "Mosquitto (dev)",
        "unique_id": None,
        "version": 2,
    }


def main() -> int:
    """Seed core.config_entries with an MQTT entry; exit 0 on success."""
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    if ENTRIES_PATH.exists():
        payload = json.loads(ENTRIES_PATH.read_text())
        entries = payload.get("data", {}).get("entries", [])
        if any(e.get("domain") == "mqtt" for e in entries):
            print("[seed_dev_mqtt] MQTT entry already present, skipping.")
            return 0
        entries.append(_new_mqtt_entry())
        payload["data"]["entries"] = entries
    else:
        payload = {
            "version": 1,
            "minor_version": 5,
            "key": "core.config_entries",
            "data": {"entries": [_new_mqtt_entry()]},
        }
    ENTRIES_PATH.write_text(json.dumps(payload, indent=2))
    rel = ENTRIES_PATH.relative_to(CONFIG_DIR.parent)
    print(f"[seed_dev_mqtt] Seeded MQTT entry into {rel}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
