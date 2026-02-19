#!/usr/bin/env python3
"""
Simulate Lockly Z2M lock devices for development.

Publishes fake Zigbee2MQTT MQTT messages for 3 simulated Yale Assure locks
so the integration can be developed and tested without real hardware.

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
        "model_id": "YRD226C4",
        "definition": {
            "model": "ZYA-YRLD226C4 20BP",
            "vendor": "Yale",
            "description": "Assure Lock Touchscreen Deadbolt",
        },
    },
    {
        "ieee_address": "0x00158d0001aaa002",
        "friendly_name": "Back Door",
        "model_id": "YRD226C4",
        "definition": {
            "model": "ZYA-YRLD226C4 20BP",
            "vendor": "Yale",
            "description": "Assure Lock Touchscreen Deadbolt",
        },
    },
    {
        "ieee_address": "0x00158d0001aaa003",
        "friendly_name": "Garage Door",
        "model_id": "YRD226C4",
        "definition": {
            "model": "ZYA-YRLD226C4 20BP",
            "vendor": "Yale",
            "description": "Assure Lock Touchscreen Deadbolt",
        },
    },
]


def _slugify(name: str) -> str:
    """Convert a friendly name to a slug for object IDs."""
    return name.lower().replace(" ", "_").replace("-", "_")


def build_discovery_payload(dev: dict, topic: str) -> dict:
    """Build an HA MQTT discovery payload for a lock entity."""
    ieee = dev["ieee_address"]
    name = dev["friendly_name"]
    defn = dev["definition"]
    return {
        "availability": [
            {
                "topic": f"{topic}/bridge/state",
                "value_template": "{{ value_json.state }}",
            }
        ],
        "command_topic": f"{topic}/{name}/set",
        "device": {
            "identifiers": [f"zigbee2mqtt_{ieee}"],
            "manufacturer": defn["vendor"],
            "model": defn["model"],
            "name": name,
            "via_device": "zigbee2mqtt_bridge",
        },
        "json_attributes_topic": f"{topic}/{name}",
        "name": None,
        "object_id": _slugify(name),
        "payload_lock": "LOCK",
        "payload_unlock": "UNLOCK",
        "state_locked": "LOCK",
        "state_unlocked": "UNLOCK",
        "state_topic": f"{topic}/{name}",
        "unique_id": f"{ieee}_lock_zigbee2mqtt",
        "value_template": "{{ value_json.state }}",
    }


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


def build_lock_state(_dev: dict) -> dict:
    """Build a realistic initial lock state payload."""
    return {
        "battery": random.randint(60, 100),  # noqa: S311
        "linkquality": random.randint(80, 255),  # noqa: S311
        "lock_state": "locked",
        "state": "LOCK",
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
            self.device_states[name] = build_lock_state(dev)
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

        # Extract device name from zigbee2mqtt/{device_name}/set
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

        pin_code = payload.get("pin_code")
        if pin_code and isinstance(pin_code, dict):
            self._handle_pin_code(device_name, pin_code)
            return

        state = self.device_states[device_name]
        for key, value in payload.items():
            state[key] = value
        self.publish_state(device_name)

    def _handle_pin_code(self, device_name: str, pin_code: dict) -> None:
        """Simulate lock processing a pin code command."""
        user_id = pin_code.get("user")
        user_enabled = pin_code.get("user_enabled", False)
        pin = pin_code.get("pin_code")

        if user_id is None:
            return

        # Simulate the lock's processing delay
        time.sleep(random.uniform(0.1, 0.5))  # noqa: S311

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

        # Respond via the state topic with action + action_user so the
        # integration can match the response to the pending slot.
        state = self.device_states[device_name].copy()
        state["action"] = action
        state["action_user"] = user_id
        self.client.publish(
            f"{self.topic}/{device_name}",
            json.dumps(state),
            retain=False,
        )

        # Clear the transient action and re-publish clean state
        time.sleep(0.05)
        self.publish_state(device_name)

    def publish_ha_discovery(self) -> None:
        """Publish HA MQTT discovery configs so lock.* entities are created."""
        self.client.publish(
            f"{self.topic}/bridge/state",
            json.dumps({"state": "online"}),
            retain=True,
        )
        for dev in DEVICES:
            disco = build_discovery_payload(dev, self.topic)
            disco_topic = f"homeassistant/lock/{dev['ieee_address']}/lock/config"
            self.client.publish(disco_topic, json.dumps(disco), retain=True)
            log.info("Discovery published for %s", dev["friendly_name"])

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
