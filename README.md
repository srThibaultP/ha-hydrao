# Hydrao for Home Assistant

*[Français](README.fr.md)*

Home Assistant custom integration for **Hydrao** connected shower heads.

Bluetooth LE is handled directly by Home Assistant through its native Bluetooth stack.

## Supported devices

Hydrao shower heads that advertise over Bluetooth LE as `HYDRAO_SHOWER*`. Tested with the Hydrao Aloe. Models with hardware older than version 8 report no flow rate, so a fixed 6.8 L/min is used for them, live and in the history.

The integration follows the open source Hydrao app, [hydrao-eco](https://github.com/hydrao-opensource/hydrao-eco): same decoding, same connection steps, same LED threshold rules and same soaping break.

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
| `sensor.live_average_flow` | Sensor | Average flow rate of the current shower (L/min) |
| `sensor.live_average_temperature` | Sensor | Average temperature of the current shower (°C) |
| `sensor.live_duration` | Sensor | Current shower duration (min), from the average flow rate |
| `sensor.total_volume` | Sensor | Total water used (L), for the Energy dashboard |
| `sensor.last_shower_volume` | Sensor | Last shower volume (L) |
| `sensor.last_shower_temperature` | Sensor | Last shower temperature (°C) |
| `sensor.last_shower_flow` | Sensor | Last shower average flow rate (L/min) |
| `sensor.last_shower_duration` | Sensor | Last shower duration (min) |
| `sensor.last_shower_soaping_time` | Sensor | Soaping time (min) |
| `sensor.last_shower_date` | Sensor | Last shower timestamp |
| `binary_sensor.is_showering` | Binary sensor | Shower in progress (on/off) |
| `binary_sensor.is_soaping` | Binary sensor | Water off for soaping, the shower is not over yet |
| `button.end_shower` | Button | End the shower now, so that the next one starts from zero |
| `number.threshold_1_volume` to `_4_volume` *(Configuration)* | Number | Volume of each LED threshold (L) |
| `select.threshold_1_color` to `_4_color` *(Configuration)* | Select | Color of each LED threshold |
| `sensor.rssi` *(Diagnostic, disabled by default)* | Sensor | BLE signal (dBm) |
| `sensor.firmware_version` *(Diagnostic)* | Sensor | Firmware version |
| `sensor.calibration` *(Diagnostic)* | Sensor | Flow calibration stored in the shower head |

All numeric sensors (volume, flow, temperature, durations) show **2 decimals at most**.
Sensors marked *Diagnostic* appear in a separate collapsed section on the device page.

## LED thresholds

The shower head lights a color until the shower reaches the volume of the first threshold, then the color of the second one, and so on. The four thresholds can be changed from Home Assistant with the same rules as the Hydrao app:

- volumes from 2 to 250 L, each threshold at least 2 L above the previous one
- colors of the app: yellow, orange, red, purple, blue, light blue, green, light green, or off

The thresholds are known once the shower head has been seen, and stay editable between showers. A change made during a shower is written within seconds. Otherwise it is kept, across restarts too, and written at the start of the next shower, like the app does.

## Soaping and end of the shower

The water can stay off for up to 2 minutes without ending the shower: the shower head keeps its count and goes on when the water comes back. During that time `binary_sensor.is_soaping` is on, and the last shower sensors already show the shower so far.

`button.end_shower` is the "I have finished my shower" button of the app. It resets the volume of the shower head, so that someone showering right after starts from zero and gets their own shower. The shower head can only be reached while the water runs, so the reset is sent at the next connection, and the shower head restarts when it receives it.

## How data is updated

The shower head has no battery and is powered by the water flow, so it can only be reached during a shower. When it starts advertising, Home Assistant connects, reads the versions and settings, sends the pending changes, reads the showers it does not know yet from the history, then polls the live values every 2 seconds. When the water stops the connection is lost and the live values are cleared. Nothing is polled between showers.

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
- The history has no dates. A shower followed live keeps its date when the history returns it, a shower taken out of range has none
- A change of the LED thresholds and the end of shower button wait for the next shower when the shower head is off
- The flow calibration is read only, the Hydrao app never writes it
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
  ├── ble_client.py    ← connection, pending requests, history sync, live polling (2 s)
  ├── coordinator.py   ← push callbacks to the entities, saved history position and requests
  ├── entity.py        ← base entity
  ├── config_flow.py   ← passive BLE discovery only (no manual input)
  ├── sensor.py        ← 16 sensors
  ├── binary_sensor.py ← shower in progress, soaping
  ├── button.py        ← end of the shower
  ├── number.py        ← LED threshold volumes
  └── select.py        ← LED threshold colors
```

The integration never blocks Home Assistant startup, even when the shower head is out of range: the entities are created immediately (unavailable), then a Bluetooth callback connects as soon as the shower head advertises again.

## BLE protocol

Based on the open source [hydrao-ble-raspberry](https://github.com/hydrao-opensource/hydrao-ble-raspberry) and [hydrao-eco](https://github.com/hydrao-opensource/hydrao-eco) code (Apache 2.0).

GATT UUIDs used:

| Characteristic | UUID |
|----------------|------|
| Device UUID    | `0000ca28-…` |
| Firmware       | `00002a26-…` |
| Hardware       | `0000ca24-…` |
| Live volume    | `0000ca1c-…` |
| Live flow      | `0000ca31-…` |
| Live temperature | `0000ca32-…` |
| LED thresholds (read and write) | `0000ca1d-…` |
| Volume reset (write) | `0000ca20-…` |
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
