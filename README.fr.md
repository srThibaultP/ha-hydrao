# Hydrao pour Home Assistant

*[English](README.md)*

Intégration Home Assistant pour les pommeaux de douche connectés **Hydrao**.

Le Bluetooth LE est géré directement par Home Assistant, avec son Bluetooth natif.

## Appareils pris en charge

Les pommeaux Hydrao qui émettent en Bluetooth LE sous le nom `HYDRAO_SHOWER*`. Testé avec le Hydrao Aloe. Les modèles dont le matériel est antérieur à la version 8 ne remontent pas de débit : une valeur fixe de 6,8 L/min est utilisée, en direct comme dans l'historique.

L'intégration suit l'application open source de Hydrao, [hydrao-eco](https://github.com/hydrao-opensource/hydrao-eco) : même décodage, mêmes étapes de connexion, mêmes règles pour les seuils LED et même pause savonnage.

## Prérequis

- Home Assistant 2025.2 ou plus récent, avec le **Bluetooth** activé
- Un adaptateur Bluetooth sur la machine qui fait tourner Home Assistant (ou un proxy Bluetooth ESPHome, voir plus bas)
- Un pommeau Hydrao

## Installation

### Via le Marketplace (recommandé)

1. Marketplace → ⋮ → **Dépôts personnalisés** → coller `https://github.com/srThibaultP/ha-hydrao` → catégorie **Intégration**
2. Installer **Hydrao Shower Head**
3. Redémarrer Home Assistant

### Manuelle

```
cp -r custom_components/hydrao  <config_dir>/custom_components/hydrao
```
Redémarrer Home Assistant.

## Configuration

Le pommeau Hydrao **n'émet en Bluetooth que pendant une douche** : il est normal de ne pas le voir le reste du temps.

1. Prendre une douche (ou faire couler l'eau dans le pommeau) pour qu'il commence à émettre
2. Home Assistant détecte l'annonce `HYDRAO_SHOWER*` et affiche une notification dans **Paramètres → Appareils et services**
3. Cliquer sur la notification et confirmer

Le pommeau peut aussi être ajouté à la main pendant que l'eau coule : **Paramètres → Appareils et services → Ajouter une intégration → Hydrao Shower Head**. Home Assistant propose le pommeau qu'il voit à ce moment-là, et explique quoi faire s'il n'en voit aucun.

Aucune adresse MAC n'est à saisir : le pommeau est toujours trouvé grâce à son annonce Bluetooth.

> **À noter :** après le démarrage de Home Assistant, les entités existent immédiatement mais restent **indisponibles** tant que le pommeau n'a pas été vu une fois, à la douche suivante. Elles restent ensuite disponibles entre deux douches, avec les valeurs en direct remises à zéro. Le volume total, les seuils LED et le bouton de fin de douche font exception : ils sont disponibles tout de suite.

## Entités créées (par pommeau)

| Nom | Type | Description |
|-----|------|-------------|
| Volume en cours | Capteur | Volume en cours (L) |
| Débit en cours | Capteur | Débit instantané (L/min) |
| Température en cours | Capteur | Température de l'eau en cours (°C) |
| Débit moyen en cours | Capteur | Débit moyen de la douche en cours (L/min) |
| Température moyenne en cours | Capteur | Température moyenne de la douche en cours (°C) |
| Durée en cours | Capteur | Durée de la douche en cours (min), calculée avec le débit moyen |
| Volume total | Capteur | Eau totale consommée (L), pour le tableau de bord Énergie |
| Volume dernière douche | Capteur | Volume de la dernière douche (L) |
| Température dernière douche | Capteur | Température de la dernière douche (°C) |
| Débit moyen dernière douche | Capteur | Débit moyen de la dernière douche (L/min) |
| Durée dernière douche | Capteur | Durée de la dernière douche (min) |
| Temps savonnage dernière douche | Capteur | Temps de savonnage (min) |
| Date dernière douche | Capteur | Horodatage de la dernière douche |
| Douche en cours | Capteur binaire | Douche en cours (on/off) |
| Savonnage en cours | Capteur binaire | Eau coupée pour le savonnage, la douche n'est pas encore terminée |
| Terminer la douche | Bouton | Terminer la douche maintenant, pour que la suivante reparte de zéro |
| Volume du seuil LED 1 à 4 *(Configuration)* | Nombre | Volume de chaque seuil LED (L) |
| Couleur du seuil LED 1 à 4 *(Configuration)* | Sélection | Couleur de chaque seuil LED |
| Signal BLE *(Diagnostic, désactivé par défaut)* | Capteur | Signal BLE (dBm) |
| Version firmware *(Diagnostic)* | Capteur | Version du firmware |
| Calibration du débit *(Diagnostic, désactivé par défaut)* | Capteur | Calibration du débit enregistrée dans le pommeau |

Les identifiants des entités sont construits avec le nom du pommeau et le nom de l'entité, dans la langue de Home Assistant. En français, un pommeau nommé `HYDRAO_SHOWER` donne `sensor.hydrao_shower_volume_en_cours`. Les exemples ci-dessous utilisent ce nom, à remplacer par le vôtre.

Tous les capteurs numériques (volume, débit, température, durées) affichent **2 décimales maximum**.
Les entités marquées *Configuration* et *Diagnostic* apparaissent dans leurs propres sections sur la fiche de l'appareil.

## Seuils LED

Le pommeau affiche une couleur jusqu'à ce que la douche atteigne le volume du premier seuil, puis la couleur du deuxième, et ainsi de suite. Les quatre seuils se règlent depuis Home Assistant avec les mêmes règles que l'application Hydrao :

- volumes de 2 à 250 L, chaque seuil au moins 2 L au-dessus du précédent
- couleurs de l'application : jaune, orange, rouge, violet, bleu, bleu clair, vert, vert clair, ou éteint

Les seuils sont connus dès que le pommeau a été vu une fois, et restent modifiables entre deux douches. Un changement fait pendant une douche est écrit en quelques secondes. Sinon il est conservé, même après un redémarrage, et écrit au début de la douche suivante, comme le fait l'application.

## Savonnage et fin de douche

L'eau peut rester coupée jusqu'à 2 minutes sans terminer la douche : le pommeau garde son compteur et reprend quand l'eau revient. Pendant ce temps le capteur binaire **Savonnage en cours** est actif, et les capteurs de la dernière douche affichent déjà la douche en l'état.

Le bouton **Terminer la douche** est le bouton « J'ai fini ma douche » de l'application. Il remet à zéro le volume du pommeau, pour que la personne suivante reparte de zéro et ait sa propre douche. Le pommeau n'est joignable que quand l'eau coule : la remise à zéro est donc envoyée à la connexion suivante, et le pommeau redémarre en la recevant.

## Mise à jour des données

Le pommeau n'a pas de pile, il est alimenté par le passage de l'eau : il n'est joignable que pendant une douche. Quand il émet, Home Assistant se connecte, lit les versions et les réglages, envoie les changements en attente, lit une fois la douche en cours, lit dans l'historique les douches qu'il ne connaît pas, puis interroge les valeurs en direct toutes les 2 secondes. Quand l'eau s'arrête, la connexion se perd. Un signal faible la fait perdre aussi : la douche reste donc en cours avec ses dernières valeurs pendant 20 secondes, puis les valeurs en direct sont remises à zéro et la pause savonnage commence. Rien n'est interrogé entre deux douches.

## Cas d'usage et exemples

- Suivre l'eau des douches dans le tableau de bord Énergie
- Afficher le volume en cours dans la salle de bain et prévenir au-delà d'une limite :

```yaml
triggers:
  - trigger: numeric_state
    entity_id: sensor.hydrao_shower_volume_en_cours
    above: 50
actions:
  - action: notify.notify
    data:
      message: "Déjà 50 L pour cette douche"
```

- Démarrer la ventilation quand `binary_sensor.hydrao_shower_douche_en_cours` passe à on

## Tableau de bord Énergie

Ajouter le capteur **Volume total** dans **Paramètres → Tableaux de bord → Énergie → Consommation d'eau**. Les autres capteurs de volume ne sont pas des compteurs : ils ne contiennent qu'une douche à la fois.

Le total vient de l'historique stocké dans le pommeau : chaque douche est comptée une seule fois et les redémarrages ne le modifient pas. Une douche est ajoutée à la connexion suivante du pommeau, c'est-à-dire au début de la douche d'après. La première synchronisation fixe la valeur de départ et n'est pas comptée comme une consommation.

## Limites connues

- Les douches ne peuvent être lues que lorsque le pommeau émet : après un redémarrage, les entités restent indisponibles jusqu'à la douche suivante, sauf le volume total, les seuils LED et le bouton de fin de douche, disponibles tout de suite
- L'historique ne contient pas de date. Une douche suivie en direct garde la sienne quand l'historique la renvoie, une douche prise hors de portée n'en a pas
- Un changement des seuils LED et le bouton de fin de douche attendent la douche suivante quand le pommeau est éteint
- La calibration du débit est en lecture seule, l'application Hydrao ne l'écrit jamais
- Le volume total est ajouté avec une douche de retard, à la connexion suivante
- L'historique ignore les douches de moins de 3 L

## Dépannage

- **Le pommeau n'est pas découvert :** faire couler l'eau, il n'émet que pendant une douche. Vérifier qu'un adaptateur ou un proxy Bluetooth est à portée
- **Les entités restent indisponibles :** elles reviennent à la douche suivante. Sinon, chercher `Still unable to connect` dans les journaux, qui indique le niveau du signal, et rapprocher un proxy
- **Pas de valeurs en direct alors que l'historique fonctionne :** la connexion est trop courte ou trop faible, un proxy ESPHome près de la salle de bain aide
- **Signaler un problème :** joindre les diagnostics de l'intégration à l'issue, les identifiants y sont masqués

## Architecture

```
Pommeau Hydrao (BLE, n'émet que pendant une douche)
       ↕ GATT (bleak + bleak-retry-connector, fournis par Home Assistant)
Home Assistant, custom_components/hydrao
  ├── protocol.py      ← décodage binaire GATT (porté de hydrao-ble-raspberry)
  ├── ble_client.py    ← connexion, demandes en attente, synchro de l'historique, lecture en direct (2 s)
  ├── coordinator.py   ← mises à jour poussées aux entités, position d'historique et demandes sauvegardées
  ├── entity.py        ← entité de base
  ├── config_flow.py   ← découverte Bluetooth, ou ajout du pommeau vu à ce moment-là
  ├── sensor.py        ← 16 capteurs
  ├── binary_sensor.py ← douche en cours, savonnage
  ├── button.py        ← fin de douche
  ├── number.py        ← volumes des seuils LED
  └── select.py        ← couleurs des seuils LED
```

L'intégration ne bloque jamais le démarrage de Home Assistant, même si le pommeau est hors de portée : les entités sont créées immédiatement (indisponibles), puis un callback Bluetooth se connecte dès que le pommeau émet à nouveau.

## Protocole BLE

Basé sur le code open source [hydrao-ble-raspberry](https://github.com/hydrao-opensource/hydrao-ble-raspberry) et [hydrao-eco](https://github.com/hydrao-opensource/hydrao-eco) (Apache 2.0).

UUIDs GATT utilisés :

| Caractéristique | UUID |
|-----------------|------|
| UUID appareil   | `0000ca28-…` |
| Firmware        | `00002a26-…` |
| Hardware        | `0000ca24-…` |
| Volume en direct | `0000ca1c-…` |
| Débit en direct | `0000ca31-…` |
| Température en direct | `0000ca32-…` |
| Seuils LED (lecture et écriture) | `0000ca1d-…` |
| Remise à zéro du volume (écriture) | `0000ca20-…` |
| Calibration     | `0000ca30-…` |
| Plage douches   | `0000ca21-…` |
| Requête douche  | `0000ca22-…` |
| Données douche  | `0000ca23-…` |

## Portée BLE limitée ? Utiliser un proxy ESPHome

Si la machine Home Assistant n'a pas de Bluetooth ou est trop loin du pommeau, un **ESP32 + ESPHome** peut servir de proxy BLE.

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

[Apache 2.0](LICENSE), basé sur les projets open source [Hydrao](https://github.com/hydrao-opensource), voir [NOTICE](NOTICE).

L'icône et le logo sont ceux de Hydrao, repris de l'application [hydrao-eco](https://github.com/hydrao-opensource/hydrao-eco). Hydrao et son logo appartiennent à Hydrao. Ce projet n'est pas affilié à Hydrao.

## Désinstallation

1. **Paramètres → Appareils et services**
2. Cliquer sur l'intégration **Hydrao Shower Head**
3. Cliquer sur les **⋮** → **Supprimer**
4. Redémarrer Home Assistant
5. Supprimer manuellement le dossier `custom_components/hydrao/` si vous ne l'avez pas installée depuis le Marketplace
