# AGENTS.md — Lockly HA Integration

This is the canonical agent guide for `bharat/homeassistant-lockly`. New Claude/Codex/Cursor sessions should read this before making changes.

## What this is

A Home Assistant custom integration + Lovelace card suite for managing **PIN-code access slots on Zigbee2MQTT smart locks**. Despite the name, it doesn't speak to Lockly hardware directly — it's a generic Z2M-via-MQTT slot manager that happens to be tuned to Lockly's quirks (firmware echoes, double events). Anything Z2M exposes through the standard PIN cluster works.

Architecturally: an MQTT-driven coordinator owns slot state (`LocklySlot` dataclass), a manager queues add/remove/apply jobs and dedups noisy lock events through `ActivityBuffer`, and two custom Lovelace cards (`lockly-card`, `lockly-activity-card`) render the UI. There's no polling, no cloud API, no Bluetooth — pure MQTT push (`iot_class: "local_push"`).

## Layout

```
.
├── README.md                   # Feature overview, install, configuration, services
├── CONTRIBUTING.md             # Fork/PR flow
│
├── custom_components/lockly/
│   ├── __init__.py             # async_setup_entry, services, MQTT subscribe, WebSocket, logbook
│   ├── manifest.json           # version "0.0.0" sentinel — see Releases section
│   ├── const.py                # DOMAIN, storage keys, _resolve_version() (mtime fallback)
│   ├── config_flow.py          # User flow: name + first/last slot + MQTT topic + endpoint; v2 migration
│   ├── data.py                 # TypedDict LocklyData wrapping coordinator/manager/subscriptions
│   ├── coordinator.py          # LocklySlotCoordinator (push-based; update_interval=None)
│   ├── manager.py              # Job queue, MQTT publish, response handling, dedup pipeline
│   ├── activity.py             # ActivityBuffer + 4 dedup rules (firmware echo, repeats, physical+auto, fallback)
│   ├── entity.py               # CoordinatorEntity base
│   ├── event.py                # LocklyLockEvent (16+ action types)
│   ├── sensor.py               # LocklySlotSensor (per-slot status)
│   ├── logbook.py              # Maps lock activity to HA logbook with labels
│   ├── services.yaml           # add_slot, remove_slot, apply_slot, push_slot, apply_all,
│   │                           #   update_slot, get_slot, export_slots, import_slots
│   ├── frontend/
│   │   ├── __init__.py         # JSModuleRegistration; cleans up legacy /local/lockly-card resources
│   │   ├── lockly-card.js      # Slot management UI (~957 LOC)
│   │   └── lockly-activity-card.js  # Recent events / per-lock summary (~704 LOC)
│   ├── strings.json
│   └── translations/en.json
│
├── assets/                     # Hand-authored brand assets (logo SVGs + README screenshots)
│                               #   — source files; not served by HA
├── brands/custom_integrations/lockly/
│                               # HA's brand registry artwork (icon.png, dark_icon.png + @2x)
├── www/lockly-card/lockly-card.js
│                               # Legacy fallback; frontend/__init__.py actively REMOVES the
│                               #   Lovelace resource pointing here (see lines 55–61)
│
├── tests/
│   ├── conftest.py             # `pytest_plugins = "pytest_homeassistant_custom_component"`
│   └── test_*.py               # 8 test modules (config flow, activity, services, frontend, ...)
│
├── config/                     # Runtime dev HA config (mosquitto.conf is checked in here)
│   ├── configuration.yaml      # Minimal — no default_config; pre-seeded MQTT entry
│   ├── mosquitto.conf          # Anon broker on 0.0.0.0:1883, no persistence
│   └── mosquitto-verbose.conf  # Same with verbose logging
│
├── scripts/
│   ├── setup                   # apt + pip + npm i -g concurrently + pre-commit + act
│   ├── develop                 # Mosquitto + (optional simulator) + HA via concurrently
│   ├── seed_dev_mqtt.py        # Idempotently writes MQTT config entry into .storage/
│   ├── lint                    # ruff check --fix && ruff format --check
│   └── simulate_devices.py     # Fake Z2M lock devices for ./scripts/develop
│
├── pytest.ini                  # asyncio_mode = auto
├── .ruff.toml                  # select = ALL minus ~5; max-complexity 25
├── .pre-commit-config.yaml     # ruff + EOF/whitespace + check-yaml + local pytest with coverage
└── requirements.txt            # HA, frontend, paho-mqtt, ruff, pre-commit, pytest helpers
```

## Dev workflow

```bash
# First time inside the devcontainer (PostCreateCommand=scripts/setup):
pre-commit install                                  # If not already

# One-command dev stack (Mosquitto + HA + fake locks)
./scripts/develop                                   # All three
./scripts/develop --no-sim                          # Skip the simulator
./scripts/develop --mqtt-verbose                    # Verbose broker logs

# scripts/seed_dev_mqtt.py runs first — pre-seeds the MQTT integration in .storage/
# so HA boots with MQTT already configured. No manual "Add Integration" step needed.

# HA dashboard: http://localhost:8123
# Lockly integration is added via UI: Settings → Devices & Services → Add → Lockly

# Tests
python3 -m pytest tests/ -v --tb=short --cov=custom_components.lockly

# Lint
./scripts/lint
pre-commit run --all-files

# Run a CI job locally
act -W .github/workflows/tests.yml
```

## Conventions and gotchas

- **`manifest.json` version is `"0.0.0"`.** The release workflow rewrites it to the tag name via `yq -i` before zipping. In dev, `const.py:_resolve_version()` detects the sentinel and falls back to `max(mtime)` of `frontend/*.js` files — that's how cache-busting works between releases. Don't edit the manifest version manually; don't remove the sentinel logic.
- **Lovelace resource URLs include `?v=<version>`** — the cards verify the version on load and warn the user if backend ≠ frontend. If you change a card's API, bump the resolved version somehow (touch the file or cut a release) so users see fresh JS.
- **`www/lockly-card/lockly-card.js` is a *legacy* fallback** that `frontend/__init__.py` actively *removes* from Lovelace resources (lines 55–61). Don't re-add it; new installs use the integration-served path under `/api/lockly/static/`.
- **Activity dedup happens at display time, not storage time.** `ActivityBuffer` keeps every raw event but applies four merge rules (firmware echo within 5s, same-action repeats within 5s, physical+automation collision within 60s, fallback) when rendering. Don't filter at insert — you'll lose the audit trail.
- **Coordinator is push-based.** `LocklySlotCoordinator` extends `DataUpdateCoordinator` but sets `update_interval=None`; entities are notified via `async_set_updated_data()` on MQTT events. Don't add a polling interval — it'd duplicate work and rate-limit the broker.
- **Mosquitto configs are checked in under `config/`.** That's intentional — bharat wants reproducible dev. Don't move them to a script-generated location.
- **`scripts/seed_dev_mqtt.py` uses Crockford-base32 ULIDs** to match HA's native config-entry ID format. If HA ever changes its ID format, update the seed accordingly so HA recognizes the entry on boot.
- **MQTT topic structure**: actions on `{base}/{lock_name}/action`, state on `{base}/{lock_name}`, control on `{base}/{lock_name}/set`. Base topic is per-config-entry (default `zigbee2mqtt`).

## Existing docs

- `README.md` — features, install (HACS + manual), Lovelace card setup, services reference, activity replay, slot export/import.
- `CONTRIBUTING.md` — fork/PR flow.
- `assets/lockly-logos.md` — design exploration for the logo set.

## Releases

Tags use **SemVer**: `v<MAJOR>.<MINOR>.<PATCH>` (e.g. `v1.0.4`). Release titles use `Lockly v<MAJOR>.<MINOR>.<PATCH>` (e.g. `Lockly v1.0.4`).

The release workflow (`.github/workflows/release.yml`) fires on **release published** (not on tag push). It rewrites `manifest.json` version to the tag via `yq`, zips `custom_components/lockly`, and uploads the zip as a release asset.

Build the GitHub release body in three parts:

1. **Lead paragraph** (no header): 1–3 sentences of plain-English summary of what this release means for users.
2. **`## What's Changed`**: bullet list of non-dependabot merged PRs since the previous tag, one per line: `* <commit subject> by @<author> in <PR url>`. Skip dependabot PRs.
3. **`N dependabot updates:`** (rollup at the bottom): one line per dependency: `* <package>: <oldest version in window> → <newest version>`. Collapse all bumps for the same dep into one line.

End with `**Full Changelog**: <compare link>` (GitHub auto-generates).

**Canonical example**: https://github.com/bharat/homeassistant-lockly/releases/tag/v1.0.4 — bharat established this format on 2026-05-10. When in doubt, mirror that release's shape.

## What NOT to touch

- `manifest.json`'s `"version": "0.0.0"` — sentinel; release workflow rewrites it.
- `const.py:_resolve_version()` — without the mtime fallback, dev installs wouldn't get cache-busted.
- `www/lockly-card/lockly-card.js` — actively cleaned up by the integration; don't repopulate.
- `frontend/__init__.py` legacy-resource cleanup (lines 55–61) — required for upgrading users.
- `config/mosquitto*.conf` — moving these breaks `scripts/develop`.
