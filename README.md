# Lockly

Lockly is a custom Home Assistant integration and Lovelace card that manage
Zigbee2MQTT lock slots across one or more locks.

## Features

- Add/remove lock slots dynamically (up to a configured maximum).
- Edit slot name, PIN, and enabled status in a Lockly edit dialog.
- View slot status in a read-only card until you click Apply.
- Apply a slot to all configured locks.
- Apply all pushes enabled slots only; disabled slots are skipped.
- Wipe slots removes slots and clears their PINs from locks.

## Installation (HACS)

1. Add this repository to HACS as a custom repository.
2. Install the integration.
3. Restart Home Assistant.

## Configuration

1. Go to Settings > Devices & Services and add the Lockly integration.
2. Set the maximum number of slots, MQTT base topic, and update endpoint.

## Lovelace Card

1. Add the card:

```
type: custom:lockly-card
entry_id: YOUR_ENTRY_ID
title: Lockly
lock_entities:
  - lock.front_door
  - group.downstairs_locks
admin_only: true
dry_run: true
```

To find the entry ID, open the Lockly integration in Settings > Devices & Services
and copy the entry ID from the browser URL.

In the visual editor, add the locks or lock groups that this card should manage.
Enable "Only admins can see PINs and edit" to restrict edits and PIN visibility.
Enable "Simulation mode (no MQTT)" to test the UI without touching locks.

### Resource registration

- Storage mode (default): the integration registers the card automatically.
- YAML mode: add a resource pointing to `/lockly/lockly-card.js` (type `module`).

## Services

- `lockly.add_slot`
- `lockly.remove_slot`
- `lockly.apply_slot`
- `lockly.push_slot`
- `lockly.apply_all`
- `lockly.update_slot`
- `lockly.wipe_slots`

See `custom_components/lockly/services.yaml` for fields and descriptions.
