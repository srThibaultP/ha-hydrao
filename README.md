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

### Marketplace (recommended)

1. Marketplace → ⋮ → **Custom repositories** → paste `https://github.com/srThibaultP/ha-hydrao` → category **Integration**
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

The shower head can also be added by hand while the water runs: **Settings → Devices & services → Add integration → Hydrao Shower Head**. Home Assistant offers the shower head it currently sees, and explains what to do when it sees none.

No MAC address is needed: the shower head is always found through its Bluetooth advertisement.

> **Note:** after Home Assistant starts, the entities exist right away but stay **unavailable** until the shower head is seen once, at the next shower. They then stay available between showers, with the live values cleared. The total volume, the LED thresholds and the End shower button are the exception: they are available right away.

## Entities (per shower head)

| Name | Type | Description |
|------|------|-------------|
| Live volume | Sensor | Current volume (L) |
| Live flow rate | Sensor | Instant flow rate (L/min) |
| Live temperature | Sensor | Current water temperature (°C) |
| Live average flow rate | Sensor | Average flow rate of the current shower (L/min) |
| Live average temperature | Sensor | Average temperature of the current shower (°C) |
| Live duration | Sensor | Current shower duration (min), from the average flow rate |
| Total water volume | Sensor | Total water used (L), for the Energy dashboard |
| Last shower volume | Sensor | Last shower volume (L) |
| Last shower temperature | Sensor | Last shower temperature (°C) |
| Last shower avg flow | Sensor | Last shower average flow rate (L/min) |
| Last shower duration | Sensor | Last shower duration (min) |
| Last shower soaping time | Sensor | Soaping time (min) |
| Last shower date | Sensor | Last shower timestamp |
| Showering | Binary sensor | Shower in progress (on/off) |
| Soaping | Binary sensor | Water off for soaping, the shower is not over yet |
| End shower | Button | End the shower now, so that the next one starts from zero |
| LED threshold 1 to 4 volume *(Configuration)* | Number | Volume of each LED threshold (L) |
| LED threshold 1 to 4 color *(Configuration)* | Select | Color of each LED threshold |
| BLE signal strength *(Diagnostic, disabled by default)* | Sensor | BLE signal (dBm) |
| Firmware version *(Diagnostic)* | Sensor | Firmware version |
| Flow calibration *(Diagnostic, disabled by default)* | Sensor | Flow calibration stored in the shower head |

Entity IDs are built from the name of the shower head and the name of the entity, in the language of Home Assistant. In English, a shower head named `HYDRAO_SHOWER` gives `sensor.hydrao_shower_live_volume`. The examples below use that name, replace it with yours.

All numeric sensors (volume, flow, temperature, durations) show **2 decimals at most**.
Entities marked *Configuration* and *Diagnostic* appear in their own sections on the device page.

## LED thresholds

The shower head lights a color until the shower reaches the volume of the first threshold, then the color of the second one, and so on. The four thresholds can be changed from Home Assistant with the same rules as the Hydrao app:

- volumes from 2 to 250 L, each threshold at least 2 L above the previous one
- colors of the app: yellow, orange, red, purple, blue, light blue, green, light green, or off

The thresholds are known once the shower head has been seen, and stay editable between showers. A change made during a shower is written within seconds. Otherwise it is kept, across restarts too, and written at the start of the next shower, like the app does.

## Soaping and end of the shower

The water can stay off for up to 2 minutes without ending the shower: the shower head keeps its count and goes on when the water comes back. During that time the **Soaping** binary sensor is on, and the last shower sensors already show the shower so far.

The **End shower** button is the "I have finished my shower" button of the app. It resets the volume of the shower head, so that someone showering right after starts from zero and gets their own shower. The shower head can only be reached while the water runs, so the reset is sent at the next connection, and the shower head restarts when it receives it.

## How data is updated

The shower head has no battery and is powered by the water flow, so it can only be reached during a shower. When it starts advertising, Home Assistant connects, reads the versions and settings, sends the pending changes, reads the running shower once, reads the showers it does not know yet from the history, then polls the live values every 2 seconds. When the water stops the connection is lost. A weak signal loses it too, so the shower stays in progress with its last values for 20 seconds, then the live values are cleared and the soaping break starts. Nothing is polled between showers.

## Use cases and examples

- Track the water used by showers in the Energy dashboard
- Show the current volume on a bathroom display, and warn above a limit:

```yaml
triggers:
  - trigger: numeric_state
    entity_id: sensor.hydrao_shower_live_volume
    above: 50
actions:
  - action: notify.notify
    data:
      message: "Already 50 L in this shower"
```

- Start the bathroom fan when `binary_sensor.hydrao_shower_showering` turns on

## Energy dashboard

Add the **Total water volume** sensor under **Settings → Dashboards → Energy → Water consumption**. The other volume sensors are not counters: they hold one shower at a time.

The total comes from the history stored in the shower head, so each shower is counted once and restarts do not change it. A shower is added when the shower head next connects, which means at the start of the following shower. The first sync sets the starting value and is not counted as consumption.

## Known limitations

- Showers cannot be read before the shower head advertises, so the entities stay unavailable after a restart until the next shower. The total volume, the LED thresholds and the End shower button are the exception, they are available right away
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
  ├── config_flow.py   ← Bluetooth discovery, or adding the shower head seen at that moment
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

[Apache 2.0](LICENSE), based on the open source [Hydrao](https://github.com/hydrao-opensource) projects, see [NOTICE](NOTICE).

The icon and the logo are those of Hydrao, taken from the [hydrao-eco](https://github.com/hydrao-opensource/hydrao-eco) app. Hydrao and its logo belong to Hydrao. This project is not affiliated with Hydrao.

## Uninstall

1. **Settings → Devices & services**
2. Open the **Hydrao Shower Head** integration
3. Click **⋮** → **Delete**
4. Restart Home Assistant
5. Delete the `custom_components/hydrao/` folder by hand if you did not install it from the Marketplace
