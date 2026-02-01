# INDI Event Stream Format

This document describes the JSON Lines format used for recording and replaying INDI server events.

## File Format

Events are stored in JSON Lines format (`.jsonl`), where each line contains a complete JSON object representing one event. This format is:
- Easy to read and edit with any text editor
- Streamable and appendable
- Can be processed line-by-line
- Human-readable and debuggable

## Event Structure

Each event has the following top-level structure:

```json
{
    "timestamp": 1640995200.123,
    "relative_time": 0.123,
    "event_number": 0,
    "event_type": "server_connected",
    "data": { ... }
}
```

### Common Fields

- `timestamp`: Unix timestamp (seconds since epoch) when the event occurred
- `relative_time`: Time in seconds since recording started
- `event_number`: Sequential event number (0-based)
- `event_type`: Type of INDI event (see below)
- `data`: Event-specific data payload

## Event Types

### Connection Events

#### `server_connected`
```json
{
    "event_type": "server_connected",
    "data": {
        "host": "localhost",
        "port": 7624
    }
}
```

#### `server_disconnected`
```json
{
    "event_type": "server_disconnected",
    "data": {
        "host": "localhost",
        "port": 7624,
        "exit_code": 0
    }
}
```

### Device Events

#### `new_device`
```json
{
    "event_type": "new_device",
    "data": {
        "device_name": "Telescope Simulator",
        "driver_name": "indi_simulator_telescope",
        "driver_exec": "indi_simulator_telescope",
        "driver_version": "1.0"
    }
}
```

#### `remove_device`
```json
{
    "event_type": "remove_device",
    "data": {
        "device_name": "Telescope Simulator"
    }
}
```

### Property Events

#### `new_property`
```json
{
    "event_type": "new_property",
    "data": {
        "name": "EQUATORIAL_EOD_COORD",
        "device_name": "Telescope Simulator",
        "type": "Number",
        "state": "Idle",
        "permission": "ReadWrite",
        "group": "Main Control",
        "label": "Equatorial EOD",
        "rule": "AtMostOne",
        "widgets": [
            {
                "name": "RA",
                "label": "RA (hh:mm:ss)",
                "value": 0.0,
                "min": 0.0,
                "max": 24.0,
                "step": 0.0,
                "format": "%010.6m"
            },
            {
                "name": "DEC",
                "label": "DEC (dd:mm:ss)",
                "value": 90.0,
                "min": -90.0,
                "max": 90.0,
                "step": 0.0,
                "format": "%010.6m"
            }
        ]
    }
}
```

#### `update_property`
```json
{
    "event_type": "update_property",
    "data": {
        "name": "EQUATORIAL_EOD_COORD",
        "device_name": "Telescope Simulator",
        "type": "Number",
        "state": "Ok",
        "permission": "ReadWrite",
        "group": "Main Control",
        "label": "Equatorial EOD",
        "rule": "AtMostOne",
        "widgets": [
            {
                "name": "RA",
                "label": "RA (hh:mm:ss)",
                "value": 12.5,
                "min": 0.0,
                "max": 24.0,
                "step": 0.0,
                "format": "%010.6m"
            },
            {
                "name": "DEC",
                "label": "DEC (dd:mm:ss)",
                "value": 45.0,
                "min": -90.0,
                "max": 90.0,
                "step": 0.0,
                "format": "%010.6m"
            }
        ]
    }
}
```

#### `remove_property`
```json
{
    "event_type": "remove_property",
    "data": {
        "name": "EQUATORIAL_EOD_COORD",
        "device_name": "Telescope Simulator",
        "type": "Number"
    }
}
```

### Message Events

#### `new_message`
```json
{
    "event_type": "new_message",
    "data": {
        "device_name": "Telescope Simulator",
        "message": "Telescope is ready."
    }
}
```

## Property Types and Widget Data

### Text Properties
```json
"widgets": [
    {
        "name": "DRIVER_INFO",
        "label": "Driver Info",
        "value": "Telescope Simulator v1.0"
    }
]
```

### Number Properties
```json
"widgets": [
    {
        "name": "TEMPERATURE",
        "label": "Temperature (C)",
        "value": 20.5,
        "min": -50.0,
        "max": 80.0,
        "step": 0.1,
        "format": "%6.2f"
    }
]
```

### Switch Properties
```json
"widgets": [
    {
        "name": "CONNECT",
        "label": "Connect",
        "state": "On"
    },
    {
        "name": "DISCONNECT",
        "label": "Disconnect",
        "state": "Off"
    }
]
```

### Light Properties
```json
"widgets": [
    {
        "name": "STATUS",
        "label": "Status",
        "state": "Ok"
    }
]
```

### BLOB Properties
```json
"widgets": [
    {
        "name": "CCD1",
        "label": "Image",
        "format": ".fits",
        "size": 1048576,
        "has_data": true
    }
]
```

## Editing Event Streams

### Common Editing Tasks

1. **Adjust Timing**: Modify `relative_time` values to change event timing
2. **Change Values**: Edit widget values in property update events
3. **Add/Remove Events**: Insert or delete entire lines
4. **Modify Sequences**: Reorder events by changing `event_number`

### Example Edits

#### Speed up playback (halve all relative times):
```bash
sed 's/"relative_time":\s*\([0-9.]*\)/"relative_time": \1/2/g' events.jsonl
```

#### Change a coordinate value:
Find the line with `EQUATORIAL_EOD_COORD` update and edit the RA/DEC values.

#### Add a delay:
Insert a custom event or modify relative times to add pauses.

### Validation

After editing, validate the JSON format:
```bash
# Check each line is valid JSON
while IFS= read -r line; do
    echo "$line" | python3 -m json.tool > /dev/null || echo "Invalid JSON: $line"
done < events.jsonl
```

### Best Practices

1. **Backup**: Always backup original recordings before editing
2. **Incremental**: Make small changes and test frequently
3. **Consistent**: Keep event numbers sequential after reordering
4. **Realistic**: Maintain realistic timing and state transitions
5. **Comments**: Use separate documentation for complex scenarios

## File Naming Conventions

- `scenario_name.jsonl` - Main event stream
- `scenario_name_edited.jsonl` - Edited version
- `scenario_name_notes.md` - Documentation for the scenario

## Integration with Mock Client

The mock client reads these files and replays events with proper timing:
- Events are sorted by `relative_time`
- Timing can be scaled (e.g., 2x speed, 0.5x speed)
- Events can be filtered by type or device
- Playback can be paused/resumed