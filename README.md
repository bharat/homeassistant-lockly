# Lockly

Lockly is a custom Home Assistant integration and Lovelace card that manage
Zigbee2MQTT lock slots across one or more locks.

## Features

- Add/remove lock slots dynamically (up to a configured maximum).
- Edit slot name and PIN with standard Home Assistant entity dialogs.
- Toggle slots on/off without applying changes until you click Apply.
- Apply a slot to all configured locks.
- Wipe slots (remove and clear them) in bulk.

## Installation (HACS)

1. Add this repository to HACS as a custom repository.
2. Install the integration.
3. Restart Home Assistant.

## Configuration

1. Go to Settings > Devices & Services and add the Lockly integration.
2. Enter the Zigbee2MQTT lock friendly names (comma-separated).
3. Set the maximum number of slots, MQTT base topic, and endpoint.

## Lovelace Card

1. Add the resource:
   - URL: `/local/lockly-card/lockly-card.js`
   - Type: `JavaScript Module`
2. Add the card:

```
type: custom:lockly-card
entry_id: YOUR_ENTRY_ID
title: Lockly
```

To find the entry ID, open the Lockly integration in Settings > Devices & Services
and copy the entry ID from the browser URL.

## Services

- `lockly.add_slot`
- `lockly.remove_slot`
- `lockly.apply_slot`
- `lockly.apply_all`
- `lockly.wipe_slots`

See `custom_components/lockly/services.yaml` for fields and descriptions.
