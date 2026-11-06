# Hydrao for Home Assistant

*[Français](README.fr.md)*

Home Assistant custom integration for **Hydrao** connected shower heads.

Bluetooth LE is handled directly by Home Assistant through its native Bluetooth stack.

## Requirements

- Home Assistant 2024.1 or later with **Bluetooth** enabled
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
| `sensor.live_duration` | Sensor | Current shower duration (s) |
| `sensor.last_shower_volume` | Sensor | Last shower volume (L) |
| `sensor.last_shower_temperature` | Sensor | Last shower temperature (°C) |
| `sensor.last_shower_flow` | Sensor | Last shower average flow rate (L/min) |
| `sensor.last_shower_duration` | Sensor | Last shower duration (s) |
| `sensor.last_shower_soaping_time` | Sensor | Soaping time (s) |
| `sensor.last_shower_date` | Sensor | Last shower timestamp |
| `binary_sensor.is_showering` | Binary sensor | Shower in progress (on/off) |
| `sensor.rssi` *(Diagnostic)* | Sensor | BLE signal (dBm) |
| `sensor.firmware_version` *(Diagnostic)* | Sensor | Firmware version |

All numeric sensors (volume, flow, temperature, durations) show **2 decimals at most**.
Sensors marked *Diagnostic* appear in a separate collapsed section on the device page.

## Architecture

```
Hydrao shower head (BLE, broadcasts only during a shower)
       ↕ GATT (bleak + bleak-retry-connector, provided by Home Assistant)
Home Assistant, custom_components/hydrao
  ├── protocol.py      ← binary GATT decoding (ported from hydrao-ble-raspberry)
  ├── ble_client.py    ← connection, history sync, live polling (2 s)
  ├── coordinator.py   ← push callbacks to the entities
  ├── config_flow.py   ← passive BLE discovery only (no manual input)
  ├── sensor.py        ← 12 sensors
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

Apache 2.0, based on the open source [Hydrao](https://github.com/hydrao-opensource) projects.

## Uninstall

1. **Settings → Devices & services**
2. Open the **Hydrao Shower Head** integration
3. Click **⋮** → **Delete**
4. Restart Home Assistant
5. Delete the `custom_components/hydrao/` folder by hand if you are not using the Marketplace / HACS
