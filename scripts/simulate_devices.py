#!/usr/bin/env python3
"""
Simulate Lockly Z2M lock devices for development.

Publishes fake Zigbee2MQTT MQTT messages for 3 simulated Yale Assure locks
so the integration can be developed and tested without real hardware.

All entity types that real Yale YRD226 locks expose via Z2M are simulated:
lock, battery, battery_low, action, action_source_name, action_user,
pin_code, auto_relock_time, and sound_volume.

Usage:
    python3 scripts/simulate_devices.py [--broker host] [--port 1883]

Requires: paho-mqtt
    pip install paho-mqtt
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from typing import Any

try:
    import paho.mqtt.client as mqtt_client
except ImportError:
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("lockly-simulator")

# ─── Simulated lock devices ───

DEVICES = [
    {
        "ieee_address": "0x00158d0001aaa001",
        "friendly_name": "Front Door",
        "model_id": "YRD226HA2619",
        "definition": {
            "model": "YRD226HA2619",
            "vendor": "Yale",
            "description": "Assure lock",
        },
    },
    {
        "ieee_address": "0x00158d0001aaa002",
        "friendly_name": "Back Door",
        "model_id": "YRD226HA2619",
        "definition": {
            "model": "YRD226HA2619",
            "vendor": "Yale",
            "description": "Assure lock",
        },
    },
    {
        "ieee_address": "0x00158d0001aaa003",
        "friendly_name": "Garage Door",
        "model_id": "YRD226HA2619",
        "definition": {
            "model": "YRD226HA2619",
            "vendor": "Yale",
            "description": "Assure lock",
        },
    },
]

# Matches Z2M exposes.action.values exactly
ACTION_VALUES = [
    "unknown",
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
]

ACTION_SOURCE_VALUES = ["keypad", "rfid", "manual", "rf"]

SOUND_VOLUME_VALUES = ["silent_mode", "low_volume", "high_volume"]


def _slugify(name: str) -> str:
    """Convert a friendly name to a slug for object IDs."""
    return name.lower().replace(" ", "_").replace("-", "_")


def _device_block(dev: dict, _topic: str) -> dict:
    """Shared HA device block so all entities group under one device."""
    defn = dev["definition"]
    return {
        "identifiers": [f"zigbee2mqtt_{dev['ieee_address']}"],
        "manufacturer": defn["vendor"],
        "model": defn["model"],
        "name": dev["friendly_name"],
        "via_device": "zigbee2mqtt_bridge",
    }


def _availability_block(topic: str) -> list[dict]:
    return [
        {
            "topic": f"{topic}/bridge/state",
            "value_template": "{{ value_json.state }}",
        }
    ]


def build_all_discovery_payloads(dev: dict, topic: str) -> list[tuple[str, dict]]:
    """Build HA MQTT discovery payloads for every entity type on a Yale lock."""
    ieee = dev["ieee_address"]
    name = dev["friendly_name"]
    slug = _slugify(name)
    device = _device_block(dev, topic)
    avail = _availability_block(topic)
    state_topic = f"{topic}/{name}"
    command_topic = f"{topic}/{name}/set"

    payloads: list[tuple[str, dict]] = []

    # Lock
    payloads.append(
        (
            f"homeassistant/lock/{ieee}/lock/config",
            {
                "availability": avail,
                "command_topic": command_topic,
                "device": device,
                "json_attributes_topic": state_topic,
                "name": None,
                "object_id": slug,
                "payload_lock": "LOCK",
                "payload_unlock": "UNLOCK",
                "state_locked": "LOCK",
                "state_unlocked": "UNLOCK",
                "state_topic": state_topic,
                "unique_id": f"{ieee}_lock_zigbee2mqtt",
                "value_template": "{{ value_json.state }}",
            },
        )
    )

    # Battery sensor
    payloads.append(
        (
            f"homeassistant/sensor/{ieee}/battery/config",
            {
                "availability": avail,
                "device": device,
                "device_class": "battery",
                "entity_category": "diagnostic",
                "name": "Battery",
                "object_id": f"{slug}_battery",
                "state_class": "measurement",
                "state_topic": state_topic,
                "unique_id": f"{ieee}_battery_zigbee2mqtt",
                "unit_of_measurement": "%",
                "value_template": "{{ value_json.battery }}",
            },
        )
    )

    # Battery low binary sensor
    payloads.append(
        (
            f"homeassistant/binary_sensor/{ieee}/battery_low/config",
            {
                "availability": avail,
                "device": device,
                "device_class": "battery",
                "entity_category": "diagnostic",
                "name": "Battery low",
                "object_id": f"{slug}_battery_low",
                "payload_off": False,
                "payload_on": True,
                "state_topic": state_topic,
                "unique_id": f"{ieee}_battery_low_zigbee2mqtt",
                "value_template": "{{ value_json.battery_low }}",
            },
        )
    )

    # Action sensor (diagnostic)
    payloads.append(
        (
            f"homeassistant/sensor/{ieee}/action/config",
            {
                "availability": avail,
                "device": device,
                "enabled_by_default": True,
                "entity_category": "diagnostic",
                "icon": "mdi:gesture-double-tap",
                "name": "Action",
                "object_id": f"{slug}_action",
                "state_topic": state_topic,
                "unique_id": f"{ieee}_action_zigbee2mqtt",
                "value_template": "{{ value_json.action }}",
            },
        )
    )

    # Action source name sensor
    payloads.append(
        (
            f"homeassistant/sensor/{ieee}/action_source_name/config",
            {
                "availability": avail,
                "device": device,
                "icon": "mdi:lock-question",
                "name": "Action source name",
                "object_id": f"{slug}_action_source_name",
                "state_topic": state_topic,
                "unique_id": f"{ieee}_action_source_name_zigbee2mqtt",
                "value_template": "{{ value_json.action_source_name }}",
            },
        )
    )

    # Action user sensor
    payloads.append(
        (
            f"homeassistant/sensor/{ieee}/action_user/config",
            {
                "availability": avail,
                "device": device,
                "icon": "mdi:account",
                "name": "Action user",
                "object_id": f"{slug}_action_user",
                "state_topic": state_topic,
                "unique_id": f"{ieee}_action_user_zigbee2mqtt",
                "value_template": "{{ value_json.action_user }}",
            },
        )
    )

    # Pin code sensor
    payloads.append(
        (
            f"homeassistant/sensor/{ieee}/pin_code/config",
            {
                "availability": avail,
                "device": device,
                "icon": "mdi:pin",
                "name": "Pin code",
                "object_id": f"{slug}_pin_code",
                "state_topic": state_topic,
                "unique_id": f"{ieee}_pin_code_zigbee2mqtt",
                "value_template": "{{ value_json.pin_code }}",
            },
        )
    )

    # Auto relock time number
    payloads.append(
        (
            f"homeassistant/number/{ieee}/auto_relock_time/config",
            {
                "availability": avail,
                "command_topic": command_topic,
                "command_template": '{"auto_relock_time": {{ value }} }',
                "device": device,
                "icon": "mdi:timer-lock-outline",
                "max": 3600,
                "min": 0,
                "name": "Auto relock time",
                "object_id": f"{slug}_auto_relock_time",
                "state_topic": state_topic,
                "unique_id": f"{ieee}_auto_relock_time_zigbee2mqtt",
                "unit_of_measurement": "s",
                "value_template": "{{ value_json.auto_relock_time }}",
            },
        )
    )

    # Sound volume select
    payloads.append(
        (
            f"homeassistant/select/{ieee}/sound_volume/config",
            {
                "availability": avail,
                "command_topic": command_topic,
                "command_template": '{"sound_volume": "{{ value }}"}',
                "device": device,
                "icon": "mdi:volume-high",
                "name": "Sound volume",
                "object_id": f"{slug}_sound_volume",
                "options": SOUND_VOLUME_VALUES,
                "state_topic": state_topic,
                "unique_id": f"{ieee}_sound_volume_zigbee2mqtt",
                "value_template": "{{ value_json.sound_volume }}",
            },
        )
    )

    # Linkquality sensor (diagnostic)
    payloads.append(
        (
            f"homeassistant/sensor/{ieee}/linkquality/config",
            {
                "availability": avail,
                "device": device,
                "entity_category": "diagnostic",
                "icon": "mdi:signal",
                "name": "Linkquality",
                "object_id": f"{slug}_linkquality",
                "state_class": "measurement",
                "state_topic": state_topic,
                "unique_id": f"{ieee}_linkquality_zigbee2mqtt",
                "unit_of_measurement": "lqi",
                "value_template": "{{ value_json.linkquality }}",
            },
        )
    )

    return payloads


def build_bridge_devices(devices: list[dict]) -> list[dict]:
    """Build the zigbee2mqtt/bridge/devices payload."""
    return [
        {
            "ieee_address": dev["ieee_address"],
            "friendly_name": dev["friendly_name"],
            "model_id": dev["model_id"],
            "manufacturer": "Yale",
            "type": "EndDevice",
            "network_address": random.randint(1000, 65000),  # noqa: S311
            "supported": True,
            "disabled": False,
            "definition": dev["definition"],
            "endpoints": {
                "1": {
                    "bindings": [],
                    "configured_reportings": [],
                    "clusters": {
                        "input": ["closuresDoorLock", "genPowerCfg"],
                        "output": [],
                    },
                },
            },
        }
        for dev in devices
    ]


def build_lock_state() -> dict:
    """Build a realistic initial lock state with all Z2M fields."""
    return {
        "battery": random.randint(60, 100),  # noqa: S311
        "battery_low": False,
        "linkquality": random.randint(80, 255),  # noqa: S311
        "lock_state": "locked",
        "state": "LOCK",
        "action": "",
        "action_source_name": "",
        "action_user": None,
        "pin_code": None,
        "auto_relock_time": 30,
        "sound_volume": "low_volume",
    }


class LocklySimulator:
    """MQTT-based Lockly lock simulator."""

    def __init__(self, broker: str, port: int, topic: str) -> None:
        """Initialize simulator with MQTT connection parameters."""
        self.broker = broker
        self.port = port
        self.topic = topic
        self.client = mqtt_client.Client(
            mqtt_client.CallbackAPIVersion.VERSION2,
            client_id=f"lockly-sim-{os.getpid()}",
        )
        self._connected_once = False
        self.device_states: dict[str, dict] = {}
        self.pin_codes: dict[str, dict[int, dict]] = {}

        for dev in DEVICES:
            name = dev["friendly_name"]
            self.device_states[name] = build_lock_state()
            self.pin_codes[name] = {}

    def on_connect(
        self,
        client: Any,
        _userdata: Any,
        _flags: Any,
        _rc: Any,
        _properties: Any = None,
    ) -> None:
        """Handle MQTT broker connection and resubscribe."""
        if not self._connected_once:
            self._connected_once = True
            log.info("Connected to MQTT broker at %s:%d", self.broker, self.port)
        else:
            log.debug("Reconnected to MQTT broker")
        client.subscribe(f"{self.topic}/+/set")

    def on_message(
        self,
        _client: Any,
        _userdata: Any,
        msg: Any,
    ) -> None:
        """Handle incoming MQTT set commands."""
        topic = msg.topic
        if "/set" not in topic:
            return

        prefix = self.topic + "/"
        if not topic.startswith(prefix):
            return
        remainder = topic[len(prefix) :]
        if not remainder.endswith("/set"):
            return
        device_name = remainder[: -len("/set")]

        if device_name not in self.device_states:
            return

        try:
            payload = json.loads(msg.payload)
        except (json.JSONDecodeError, ValueError):
            return

        log.info("SET %s: %s", device_name, json.dumps(payload, indent=None))

        self._dispatch_command(device_name, payload)

    def _dispatch_command(self, device_name: str, payload: dict) -> None:
        """Route an incoming command to the appropriate handler."""
        pin_code = payload.get("pin_code")
        if pin_code and isinstance(pin_code, dict):
            self._handle_pin_code(device_name, pin_code)
            return

        new_state = payload.get("state")
        if new_state in ("LOCK", "UNLOCK"):
            self._handle_lock_command(device_name, new_state)
            return

        state = self.device_states[device_name]
        for key, value in payload.items():
            if key in state:
                state[key] = value
        self.publish_state(device_name)

    def _handle_lock_command(self, device_name: str, command: str) -> None:
        """Simulate a lock/unlock command, populating action fields."""
        state = self.device_states[device_name]

        time.sleep(random.uniform(0.1, 0.3))  # noqa: S311

        if command == "UNLOCK":
            state["state"] = "UNLOCK"
            state["lock_state"] = "unlocked"

            known_users = list(self.pin_codes.get(device_name, {}).keys())
            action_user = (
                random.choice(known_users)  # noqa: S311
                if known_users
                else random.randint(1, 5)  # noqa: S311
            )
            state["action"] = "unlock"
            state["action_source_name"] = "keypad"
            state["action_user"] = action_user
            log.info("UNLOCK %s via keypad (user %s)", device_name, action_user)
        else:
            state["state"] = "LOCK"
            state["lock_state"] = "locked"
            state["action"] = "lock"
            state["action_source_name"] = "keypad"
            state["action_user"] = None
            log.info("LOCK %s", device_name)

        self.publish_state(device_name)

        # Clear transient action after a short delay, like real hardware
        time.sleep(0.1)
        state["action"] = ""
        self.publish_state(device_name)

    def _handle_pin_code(self, device_name: str, pin_code: dict) -> None:
        """Simulate lock processing a pin code command."""
        user_id = pin_code.get("user")
        user_enabled = pin_code.get("user_enabled", False)
        pin = pin_code.get("pin_code")

        if user_id is None:
            return

        time.sleep(random.uniform(0.1, 0.5))  # noqa: S311

        state = self.device_states[device_name]

        if user_enabled and pin:
            self.pin_codes[device_name][user_id] = {
                "pin": pin,
                "enabled": True,
            }
            action = "pin_code_added"
            log.info("PIN added: %s slot %s", device_name, user_id)
        else:
            self.pin_codes[device_name].pop(user_id, None)
            action = "pin_code_deleted"
            log.info("PIN deleted: %s slot %s", device_name, user_id)

        state["action"] = action
        state["action_source_name"] = "rf"
        state["action_user"] = user_id
        self.publish_state(device_name)

        time.sleep(0.05)
        state["action"] = ""
        self.publish_state(device_name)

    def publish_ha_discovery(self) -> None:
        """Publish HA MQTT discovery configs for all entity types."""
        self.client.publish(
            f"{self.topic}/bridge/state",
            json.dumps({"state": "online"}),
            retain=True,
        )
        for dev in DEVICES:
            for disco_topic, disco_payload in build_all_discovery_payloads(
                dev, self.topic
            ):
                self.client.publish(disco_topic, json.dumps(disco_payload), retain=True)
            log.info(
                "Discovery published for %s (10 entities)",
                dev["friendly_name"],
            )

    def publish_bridge_devices(self) -> None:
        """Publish the bridge/devices discovery payload."""
        payload = json.dumps(build_bridge_devices(DEVICES))
        self.client.publish(f"{self.topic}/bridge/devices", payload, retain=True)
        log.info("Published bridge/devices with %d locks", len(DEVICES))

    def publish_state(self, device_name: str) -> None:
        """Publish state for a single device."""
        state = self.device_states.get(device_name)
        if state is None:
            return
        self.client.publish(
            f"{self.topic}/{device_name}",
            json.dumps(state),
            retain=True,
        )

    def publish_all_states(self) -> None:
        """Publish state for all simulated devices."""
        for dev in DEVICES:
            self.publish_state(dev["friendly_name"])
        log.info("Published state for %d locks", len(DEVICES))

    def run(self) -> None:
        """Connect to the broker and run the event loop forever."""
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        log.info("Connecting to %s:%d...", self.broker, self.port)
        self.client.connect(self.broker, self.port, 60)

        self.publish_ha_discovery()
        self.publish_bridge_devices()
        self.publish_all_states()

        log.info(
            "Simulating %d locks: %s",
            len(DEVICES),
            ", ".join(d["friendly_name"] for d in DEVICES),
        )
        log.info("Simulator running. Press Ctrl+C to stop.")
        try:
            self.client.loop_forever()
        except KeyboardInterrupt:
            log.info("Shutting down.")
            self.client.disconnect()


def main() -> None:
    """Run the Lockly lock simulator."""
    parser = argparse.ArgumentParser(description="Simulate Lockly Z2M locks")
    parser.add_argument("--broker", default="localhost", help="MQTT broker host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--topic", default="zigbee2mqtt", help="Z2M base topic")
    args = parser.parse_args()

    sim = LocklySimulator(args.broker, args.port, args.topic)
    sim.run()


if __name__ == "__main__":
    main()
