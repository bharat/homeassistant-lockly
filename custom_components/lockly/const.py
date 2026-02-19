"""Constants for Lockly."""

from __future__ import annotations

import json
from contextlib import suppress
from logging import Logger, getLogger
from pathlib import Path

LOGGER: Logger = getLogger(__package__)

DOMAIN = "lockly"

_PACKAGE_DIR = Path(__file__).parent
URL_BASE = "/lockly"


def _resolve_version() -> str:
    """Read version from manifest.json.

    Called once at module load (before the event loop starts) so the
    result is cached and never triggers blocking I/O inside async code.
    """
    version = "0.0.0"
    with (
        suppress(FileNotFoundError, json.JSONDecodeError),
        (_PACKAGE_DIR / "manifest.json").open(encoding="utf-8") as fh,
    ):
        version = json.load(fh).get("version", "0.0.0")
    if version == "0.0.0":
        with suppress(FileNotFoundError):
            version = str(
                int((_PACKAGE_DIR / "frontend" / "lockly-card.js").stat().st_mtime)
            )
    return version


INTEGRATION_VERSION: str = _resolve_version()


def get_jsmodules() -> list[dict[str, str]]:
    """Return JS module descriptors."""
    return [
        {
            "name": "Lockly Card",
            "filename": "lockly-card.js",
            "version": INTEGRATION_VERSION,
        },
        {
            "name": "Lockly Activity Card",
            "filename": "lockly-activity-card.js",
            "version": INTEGRATION_VERSION,
        },
    ]


CONF_LOCK_NAMES = "lock_names"
CONF_LOCK_ENTITIES = "lock_entities"
CONF_LOCK_GROUP_ENTITY = "lock_group_entity"
CONF_FIRST_SLOT = "first_slot"
CONF_LAST_SLOT = "last_slot"
CONF_MAX_SLOTS = "max_slots"
CONF_MQTT_TOPIC = "mqtt_topic"
CONF_ENDPOINT = "endpoint"

DEFAULT_LOCK_NAMES: list[str] = []
DEFAULT_MAX_SLOTS = 20
DEFAULT_FIRST_SLOT = 1
DEFAULT_LAST_SLOT = DEFAULT_MAX_SLOTS
DEFAULT_MQTT_TOPIC = "zigbee2mqtt"
DEFAULT_ENDPOINT = 1

STORAGE_KEY = "lockly_slots"
ACTIVITY_STORAGE_KEY = "lockly_activity"
STORAGE_VERSION = 1

PIN_REGEX = r"^\d{4,8}$"

SERVICE_ADD_SLOT = "add_slot"
SERVICE_REMOVE_SLOT = "remove_slot"
SERVICE_APPLY_SLOT = "apply_slot"
SERVICE_PUSH_SLOT = "push_slot"
SERVICE_APPLY_ALL = "apply_all"
SERVICE_UPDATE_SLOT = "update_slot"
SERVICE_EXPORT_SLOTS = "export_slots"
SERVICE_IMPORT_SLOTS = "import_slots"
