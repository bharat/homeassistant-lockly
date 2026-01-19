"""Constants for Lockly."""

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "lockly"

CONF_LOCK_NAMES = "lock_names"
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
SERVICE_APPLY_ALL = "apply_all"
SERVICE_WIPE_SLOTS = "wipe_slots"
