"""Constants for Lockly."""

from __future__ import annotations

import json
from logging import Logger, getLogger
from pathlib import Path
from typing import Final

LOGGER: Logger = getLogger(__package__)

DOMAIN = "lockly"

MANIFEST_PATH = Path(__file__).parent / "manifest.json"
with MANIFEST_PATH.open(encoding="utf-8") as manifest_file:
    INTEGRATION_VERSION: Final[str] = json.load(manifest_file).get("version", "0.0.0")

URL_BASE = "/lockly"
JSMODULES: Final[list[dict[str, str]]] = [
    {
        "name": "Lockly Card",
        "filename": "lockly-card.js",
        "version": INTEGRATION_VERSION,
    }
]

CONF_LOCK_NAMES = "lock_names"
CONF_LOCK_ENTITIES = "lock_entities"
CONF_LOCK_GROUP_ENTITY = "lock_group_entity"
CONF_MAX_SLOTS = "max_slots"
CONF_MQTT_TOPIC = "mqtt_topic"
CONF_ENDPOINT = "endpoint"

DEFAULT_LOCK_NAMES: list[str] = []
DEFAULT_MAX_SLOTS = 20
DEFAULT_MQTT_TOPIC = "zigbee2mqtt"
DEFAULT_ENDPOINT = 1

STORAGE_KEY = "lockly_slots"
STORAGE_VERSION = 1

PIN_REGEX = r"^\d{4,8}$"

SERVICE_ADD_SLOT = "add_slot"
SERVICE_REMOVE_SLOT = "remove_slot"
SERVICE_APPLY_SLOT = "apply_slot"
SERVICE_PUSH_SLOT = "push_slot"
SERVICE_APPLY_ALL = "apply_all"
SERVICE_UPDATE_SLOT = "update_slot"
SERVICE_WIPE_SLOTS = "wipe_slots"
SERVICE_EXPORT_SLOTS = "export_slots"
SERVICE_IMPORT_SLOTS = "import_slots"
