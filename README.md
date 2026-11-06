# Hydrao for Home Assistant

*[Français](README.fr.md)*

Home Assistant custom integration for **Hydrao** connected shower heads.

Bluetooth LE is handled directly by Home Assistant through its native Bluetooth stack.

## Supported devices

Hydrao shower heads that advertise over Bluetooth LE as `HYDRAO_SHOWER*`. Tested with the Hydrao Aloe. Models with hardware older than version 8 report no flow rate, so a fixed 6.8 L/min is used for them.

## Requirements

- Home Assistant 2025.2 or later with **Bluetooth** enabled
- A Bluetooth adapter on the machine running Home Assistant (or an ESPHome Bluetooth proxy, see below)
- A Hydrao shower head

## Installation

### Marketplace / HACS (recommended)

1. Marketplace (HACS) → ⋮ → **Custom repositories** → paste `https://github.com/srThibaultP/ha-hydrao` → category **Integration**
2. Install **Hydrao Shower Head**
3. Restart Home Assistant

### Manual

```
cp -r custom_components/hydrao  <config_dir>/custom_components/hydrao
```

Restart Home Assistant.

## Configuration

The shower head **only broadcasts over Bluetooth during a shower**, so it is normal not to see it the rest of the time.

1. Take a shower (or run the water through the shower head) so that it starts advertising
2. Home Assistant detects the `HYDRAO_SHOWER*` advertisement and shows a notification in **Settings → Devices & services**
3. Click the notification and confirm

No MAC address is needed: the integration relies on automatic discovery only.

> **Note:** once the integration is added, the entities exist right away but stay **unavailable** while no shower is running. They become available again the next time the shower head is used.

## Entities (per shower head)

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.live_volume` | Sensor | Current volume (L) |
| `sensor.live_flow` | Sensor | Instant flow rate (L/min) |
| `sensor.live_temperature` | Sensor | Current water temperature (°C) |
| `sensor.live_duration` | Sensor | Current shower duration (min) |
| `sensor.total_volume` | Sensor | Total water used (L), for the Energy dashboard |
| `sensor.last_shower_volume` | Sensor | Last shower volume (L) |
| `sensor.last_shower_temperature` | Sensor | Last shower temperature (°C) |
| `sensor.last_shower_flow` | Sensor | Last shower average flow rate (L/min) |
| `sensor.last_shower_duration` | Sensor | Last shower duration (min) |
| `sensor.last_shower_soaping_time` | Sensor | Soaping time (min) |
| `sensor.last_shower_date` | Sensor | Last shower timestamp |
| `binary_sensor.is_showering` | Binary sensor | Shower in progress (on/off) |
| `sensor.rssi` *(Diagnostic, disabled by default)* | Sensor | BLE signal (dBm) |
| `sensor.firmware_version` *(Diagnostic)* | Sensor | Firmware version |

All numeric sensors (volume, flow, temperature, durations) show **2 decimals at most**.
Sensors marked *Diagnostic* appear in a separate collapsed section on the device page.

## How data is updated

The shower head has no battery and is powered by the water flow, so it can only be reached during a shower. When it starts advertising, Home Assistant connects, reads the versions, reads the showers it does not know yet from the history, then polls the live values every 2 seconds. When the shower ends the connection is lost and the live values are cleared. Nothing is polled between showers.

## Use cases and examples

- Track the water used by showers in the Energy dashboard
- Show the current volume on a bathroom display, and warn above a limit:

```yaml
triggers:
  - trigger: numeric_state
    entity_id: sensor.shower_live_volume
    above: 50
actions:
  - action: notify.notify
    data:
      message: "Already 50 L in this shower"
```

- Start the bathroom fan when `binary_sensor.shower_is_showering` turns on

## Energy dashboard

Add `sensor.total_volume` under **Settings → Dashboards → Energy → Water consumption**. The other volume sensors are not counters: they hold one shower at a time.

The total comes from the history stored in the shower head, so each shower is counted once and restarts do not change it. A shower is added when the shower head next connects, which means at the start of the following shower. The first sync sets the starting value and is not counted as consumption.

## Known limitations

- Showers cannot be read before the shower head advertises, so entities stay unavailable after a restart until the next shower. The total volume is the exception, it is restored right away
- The history has no dates, so showers read from it have no date. Only a shower followed live gets one
- The total volume is added one shower late, at the next connection
- Showers under 3 L are ignored by the history

## Troubleshooting

- **The shower head is not discovered:** run the water, it only advertises during a shower. Check that a Bluetooth adapter or proxy is in range
- **Entities stay unavailable:** they wake up at the next shower. If they do not, look for `Still unable to connect` in the logs, which gives the signal level, and move a proxy closer
- **Live values are missing but the history works:** the connection is too short or too weak, an ESPHome proxy near the bathroom helps
- **Reporting a problem:** add the diagnostics of the integration to the issue, identifiers are redacted

## Architecture

```
Hydrao shower head (BLE, broadcasts only during a shower)
       ↕ GATT (bleak + bleak-retry-connector, provided by Home Assistant)
Home Assistant, custom_components/hydrao
  ├── protocol.py      ← binary GATT decoding (ported from hydrao-ble-raspberry)
  ├── ble_client.py    ← connection, history sync, live polling (2 s)
  ├── coordinator.py   ← push callbacks to the entities, saved history position
  ├── entity.py        ← base entity
  ├── config_flow.py   ← passive BLE discovery only (no manual input)
  ├── sensor.py        ← 13 sensors
  └── binary_sensor.py ← shower in progress
```

The integration never blocks Home Assistant startup, even when the shower head is out of range: the entities are created immediately (unavailable), then a Bluetooth callback connects as soon as the shower head advertises again.

## BLE protocol

Based on the open source [hydrao-ble-raspberry](https://github.com/hydrao-opensource/hydrao-ble-raspberry) code (Apache 2.0).

GATT UUIDs used:

| Characteristic | UUID |
|----------------|------|
| Device UUID    | `0000ca28-…` |
| Firmware       | `00002a26-…` |
| Hardware       | `0000ca24-…` |
| Live volume    | `0000ca1c-…` |
| Live flow      | `0000ca31-…` |
| Live temperature | `0000ca32-…` |
| LED thresholds | `0000ca1d-…` |
| Calibration    | `0000ca30-…` |
| Shower range   | `0000ca21-…` |
| Shower request | `0000ca22-…` |
| Shower data    | `0000ca23-…` |

## Limited BLE range? Use an ESPHome proxy

If the Home Assistant machine has no Bluetooth or is too far from the shower head, an **ESP32 running ESPHome** can act as a BLE proxy.

```yaml
esphome:
  name: hydrao-proxy

esp32:
  board: esp32dev
  framework:
    type: esp-idf   # required for bluetooth_proxy

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password

api:
  encryption:
    key: !secret api_key

bluetooth_proxy:
  active: true   # required to allow outgoing GATT connections
```

## License

[Apache 2.0](LICENSE), based on the open source [Hydrao](https://github.com/hydrao-opensource) projects.

## Uninstall

1. **Settings → Devices & services**
2. Open the **Hydrao Shower Head** integration
3. Click **⋮** → **Delete**
4. Restart Home Assistant
5. Delete the `custom_components/hydrao/` folder by hand if you are not using the Marketplace / HACS
