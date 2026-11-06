"""Hydrao sensor platform."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    MANUFACTURER,
    SENSOR_FW_VERSION,
    SENSOR_LAST_DATE,
    SENSOR_LAST_DURATION,
    SENSOR_LAST_FLOW,
    SENSOR_LAST_SOAPING,
    SENSOR_LAST_TEMPERATURE,
    SENSOR_LAST_VOLUME,
    SENSOR_LIVE_DURATION,
    SENSOR_LIVE_FLOW,
    SENSOR_LIVE_TEMPERATURE,
    SENSOR_LIVE_VOLUME,
    SENSOR_RSSI,
    SENSOR_TOTAL_VOLUME,
)
from .coordinator import HydraoCoordinator

# IQS parallel-updates: push integration, no parallel polling needed
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class HydraoSensorDescription(SensorEntityDescription):
    """Sensor description with a data extraction function."""
    value_key: str = ""
    sub_key: str | None = None   # if set: data["last_shower"][sub_key]
    transform: Any = None        # optional value transformer


SENSOR_DESCRIPTIONS: tuple[HydraoSensorDescription, ...] = (
    # ── Live ──────────────────────────────────────────────────────────────────
    HydraoSensorDescription(
        key=SENSOR_LIVE_VOLUME,
        translation_key=SENSOR_LIVE_VOLUME,
        name="Volume en cours",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.VOLUME,
        state_class=None,  # volume live repart à 0 → pas de state_class
        suggested_display_precision=2,
        icon="mdi:shower-head",
        value_key="live_volume",
    ),
    HydraoSensorDescription(
        key=SENSOR_LIVE_FLOW,
        translation_key=SENSOR_LIVE_FLOW,
        name="Débit en cours",
        native_unit_of_measurement="L/min",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:water-pump",
        value_key="live_flow",
    ),
    HydraoSensorDescription(
        key=SENSOR_LIVE_TEMPERATURE,
        translation_key=SENSOR_LIVE_TEMPERATURE,
        name="Température en cours",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_key="live_temperature",
    ),
    HydraoSensorDescription(
        key=SENSOR_LIVE_DURATION,
        translation_key=SENSOR_LIVE_DURATION,
        name="Durée en cours",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:timer",
        value_key="live_duration",
        # already in minutes from ble_client
    ),
    # Cumulative counter for the Energy dashboard. Showers are counted once,
    # from the showerhead history, at the next connection after they end.
    HydraoSensorDescription(
        key=SENSOR_TOTAL_VOLUME,
        translation_key=SENSOR_TOTAL_VOLUME,
        name="Volume total",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        icon="mdi:water-sync",
        value_key="total_volume",
    ),
    # ── Dernière douche ────────────────────────────────────────────────────────
    HydraoSensorDescription(
        key=SENSOR_LAST_VOLUME,
        translation_key=SENSOR_LAST_VOLUME,
        name="Volume dernière douche",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.VOLUME,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        icon="mdi:water",
        value_key="last_shower",
        sub_key="volume",
    ),
    HydraoSensorDescription(
        key=SENSOR_LAST_TEMPERATURE,
        translation_key=SENSOR_LAST_TEMPERATURE,
        name="Température dernière douche",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_key="last_shower",
        sub_key="temperature",
    ),
    HydraoSensorDescription(
        key=SENSOR_LAST_FLOW,
        translation_key=SENSOR_LAST_FLOW,
        name="Débit moyen dernière douche",
        native_unit_of_measurement="L/min",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:water-pump",
        value_key="last_shower",
        sub_key="flow",
    ),
    HydraoSensorDescription(
        key=SENSOR_LAST_DURATION,
        translation_key=SENSOR_LAST_DURATION,
        name="Durée dernière douche",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:timer-check",
        value_key="last_shower",
        sub_key="duration",
        # already in minutes from protocol.py / ble_client
    ),
    HydraoSensorDescription(
        key=SENSOR_LAST_SOAPING,
        translation_key=SENSOR_LAST_SOAPING,
        name="Temps savonnage dernière douche",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:hand-wash",
        value_key="last_shower",
        sub_key="soaping_time",
        transform=lambda v: round(v / 60, 2) if v else None,  # BLE stores raw seconds
    ),
    HydraoSensorDescription(
        key=SENSOR_LAST_DATE,
        translation_key=SENSOR_LAST_DATE,
        name="Date dernière douche",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:calendar-clock",
        value_key="last_shower",
        sub_key="date",
        transform=lambda v: datetime.fromisoformat(v) if v else None,
    ),
    # ── Appareil (diagnostic) ─────────────────────────────────────────────────
    HydraoSensorDescription(
        key=SENSOR_RSSI,
        translation_key=SENSOR_RSSI,
        name="Signal BLE",
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_key="rssi",
    ),
    HydraoSensorDescription(
        key=SENSOR_FW_VERSION,
        translation_key=SENSOR_FW_VERSION,
        name="Version firmware",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_key="fw_version",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HydraoCoordinator = entry.runtime_data
    async_add_entities(
        HydraoSensorEntity(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
    )


class HydraoSensorEntity(CoordinatorEntity[HydraoCoordinator], SensorEntity):
    """A Hydrao sensor entity backed by the BLE coordinator."""

    entity_description: HydraoSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HydraoCoordinator,
        description: HydraoSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        address = coordinator.device.address
        self._attr_unique_id = f"{address}_{description.key}"
        self._attr_device_info = _device_info(coordinator)

    @property
    def available(self) -> bool:
        """Unavailable until the showerhead has been seen advertising at least once."""
        device = self.coordinator.device
        if self.entity_description.key == SENSOR_TOTAL_VOLUME:
            # Known from storage, no need to wait for the next shower
            return device.total_volume is not None
        return device.ble_device is not None

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data
        if not data:
            return None

        raw = data.get(self.entity_description.value_key)

        if self.entity_description.sub_key is not None:
            if not isinstance(raw, dict):
                return None
            raw = raw.get(self.entity_description.sub_key)

        if raw is None:
            return None

        if self.entity_description.transform:
            return self.entity_description.transform(raw)

        if isinstance(raw, float):
            return round(raw, 2)

        return raw


def _device_info(coordinator: HydraoCoordinator) -> DeviceInfo:
    d = coordinator.device
    data = coordinator.data or {}
    return DeviceInfo(
        identifiers={(DOMAIN, d.address)},
        name=data.get("name", d.address),
        manufacturer=MANUFACTURER,
        model=f"HW v{data.get('hw_version')}" if data.get("hw_version") else "Shower Head",
        sw_version=data.get("fw_version"),
    )
