# Hydrao — Custom Component Home Assistant

*[English](README.md)*

Intégration Home Assistant pour les pommeaux de douche connectés **Hydrao**.

La communication BLE est gérée directement par HA via son subsystem Bluetooth natif.

## Prérequis

- Home Assistant ≥ 2024.1 avec le subsystem **Bluetooth** activé
- Un adaptateur Bluetooth sur la machine qui fait tourner HA (Raspberry Pi, NUC, etc.)
- Le pommeau Hydrao

## Installation

### Via le Marketplace / HACS (recommandé)

1. Marketplace (HACS) → ⋮ → **Dépôts personnalisés** → coller `https://github.com/srThibaultP/ha-hydrao` → catégorie **Intégration**
2. Installer **Hydrao Shower Head**
3. Redémarrer Home Assistant

### Manuelle

```
cp -r custom_components/hydrao  <config_dir>/custom_components/hydrao
```
Redémarrer Home Assistant.

## Configuration

Le pommeau Hydrao **ne broadcast en Bluetooth que pendant une douche active** — c'est normal qu'il n'apparaisse pas en dehors de ces moments.

1. Prendre une douche (ou activer le pommeau) pour qu'il commence à émettre
2. HA détecte automatiquement l'advertisement `HYDRAO_SHOWER*` et affiche une notification dans **Paramètres → Appareils et Services**
3. Cliquer sur la notification → confirmer

Aucune saisie d'adresse MAC n'est nécessaire : l'intégration est uniquement basée sur la découverte automatique.

> **À noter :** une fois l'intégration ajoutée, les entités existent immédiatement mais restent **indisponibles** (grisées) tant qu'aucune douche n'est en cours. Elles repassent disponibles dès la prochaine utilisation du pommeau.

## Entités créées (par pommeau)

| Entité | Type | Description |
|--------|------|-------------|
| `sensor.live_volume` | Sensor | Volume en cours (L) |
| `sensor.live_flow` | Sensor | Débit instantané (L/min) |
| `sensor.live_temperature` | Sensor | Température eau en cours (°C) |
| `sensor.live_duration` | Sensor | Durée douche en cours (s) |
| `sensor.total_volume` | Sensor | Eau totale consommée (L), pour le dashboard Énergie |
| `sensor.last_shower_volume` | Sensor | Volume dernière douche (L) |
| `sensor.last_shower_temperature` | Sensor | Température dernière douche (°C) |
| `sensor.last_shower_flow` | Sensor | Débit moyen dernière douche (L/min) |
| `sensor.last_shower_duration` | Sensor | Durée dernière douche (s) |
| `sensor.last_shower_soaping_time` | Sensor | Temps savonnage (s) |
| `sensor.last_shower_date` | Sensor | Horodatage dernière douche |
| `binary_sensor.is_showering` | Binary Sensor | Douche en cours (ON/OFF) |
| `sensor.rssi` *(Diagnostic)* | Sensor | Signal BLE (dBm) |
| `sensor.firmware_version` *(Diagnostic)* | Sensor | Version firmware |

Tous les capteurs numériques (volume, débit, température, durées) affichent **2 décimales maximum**.
Les capteurs marqués *Diagnostic* apparaissent dans une section repliée à part sur la fiche de l'appareil.

## Dashboard Énergie

Ajouter `sensor.total_volume` dans **Paramètres → Tableaux de bord → Énergie → Consommation d'eau**. Les autres capteurs de volume ne sont pas des compteurs : ils ne contiennent qu'une douche à la fois.

Le total vient de l'historique stocké dans le pommeau : chaque douche est comptée une seule fois et les redémarrages ne le modifient pas. Une douche est ajoutée à la connexion suivante du pommeau, c'est-à-dire au début de la douche d'après. La première synchronisation fixe la valeur de départ et n'est pas comptée comme une consommation.

## Architecture

```
Pommeau Hydrao (BLE — broadcast uniquement pendant une douche)
       ↕ GATT (bleak + bleak-retry-connector, fournis par HA)
Home Assistant — custom_components/hydrao
  ├── protocol.py      ← décodage binaire GATT (porté de hydrao-ble-raspberry)
  ├── ble_client.py    ← connexion, sync historique, polling live (2s)
  ├── coordinator.py   ← push callbacks → entités HA
  ├── config_flow.py   ← découverte BLE passive uniquement (aucune saisie manuelle)
  ├── sensor.py        ← 13 capteurs
  └── binary_sensor.py ← douche en cours
```

L'intégration ne bloque jamais le démarrage de HA même si le pommeau est hors de portée : les entités sont créées immédiatement (indisponibles), puis un callback Bluetooth se connecte automatiquement dès la prochaine émission du pommeau.

## Protocole BLE

Basé sur le code open source [hydrao-ble-raspberry](https://github.com/hydrao-opensource/hydrao-ble-raspberry) (Apache 2.0).

UUIDs GATT utilisés :

| Caracteristique | UUID |
|-----------------|------|
| UUID appareil   | `0000ca28-…` |
| Firmware        | `00002a26-…` |
| Hardware        | `0000ca24-…` |
| Volume live     | `0000ca1c-…` |
| Débit live      | `0000ca31-…` |
| Température live| `0000ca32-…` |
| Seuils LED      | `0000ca1d-…` |
| Calibration     | `0000ca30-…` |
| Plage douches   | `0000ca21-…` |
| Requête douche  | `0000ca22-…` |
| Données douche  | `0000ca23-…` |

## Portée BLE limitée ? Utiliser un proxy ESPHome

Si la machine HA n'a pas de Bluetooth ou est trop loin du pommeau, un **ESP32 + ESPHome** peut servir de proxy BLE.

```yaml
esphome:
  name: hydrao-proxy

esp32:
  board: esp32dev
  framework:
    type: esp-idf   # requis pour bluetooth_proxy

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password

api:
  encryption:
    key: !secret api_key

bluetooth_proxy:
  active: true   # requis pour autoriser les connexions GATT sortantes
```

## Licence

[Apache 2.0](LICENSE) — basé sur les projets open source [Hydrao](https://github.com/hydrao-opensource).

## Désinstallation

1. **Paramètres → Appareils et Services**
2. Cliquer sur l'intégration **Hydrao Shower Head**
3. Cliquer sur les **⋮** → **Supprimer**
4. Redémarrer Home Assistant
5. Supprimer manuellement le dossier `custom_components/hydrao/` si vous n'utilisez pas le Marketplace / HACS
