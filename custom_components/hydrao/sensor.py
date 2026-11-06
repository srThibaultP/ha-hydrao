"""Hydrao sensor platform."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
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
from .coordinator import HydraoConfigEntry, HydraoCoordinator
from .entity import HydraoEntity

# Push integration, nothing is polled
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class HydraoSensorDescription(SensorEntityDescription):
    """Sensor description with the way to read its value."""

    value_key: str
    sub_key: str | None = None  # if set: data[value_key][sub_key]
    transform: Callable[[Any], Any] | None = None


SENSOR_DESCRIPTIONS: tuple[HydraoSensorDescription, ...] = (
    # Current shower
    HydraoSensorDescription(
        key=SENSOR_LIVE_VOLUME,
        translation_key=SENSOR_LIVE_VOLUME,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.VOLUME,
        suggested_display_precision=2,
        value_key="live_volume",
    ),
    HydraoSensorDescription(
        key=SENSOR_LIVE_FLOW,
        translation_key=SENSOR_LIVE_FLOW,
        native_unit_of_measurement=UnitOfVolumeFlowRate.LITERS_PER_MINUTE,
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_key="live_flow",
    ),
    HydraoSensorDescription(
        key=SENSOR_LIVE_TEMPERATURE,
        translation_key=SENSOR_LIVE_TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_key="live_temperature",
    ),
    HydraoSensorDescription(
        key=SENSOR_LIVE_DURATION,
        translation_key=SENSOR_LIVE_DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_key="live_duration",
    ),
    # Cumulative counter for the Energy dashboard. Showers are counted once,
    # from the showerhead history, at the next connection after they end.
    HydraoSensorDescription(
        key=SENSOR_TOTAL_VOLUME,
        translation_key=SENSOR_TOTAL_VOLUME,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        value_key="total_volume",
    ),
    # Last shower
    HydraoSensorDescription(
        key=SENSOR_LAST_VOLUME,
        translation_key=SENSOR_LAST_VOLUME,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.VOLUME,
        suggested_display_precision=2,
        value_key="last_shower",
        sub_key="volume",
    ),
    HydraoSensorDescription(
        key=SENSOR_LAST_TEMPERATURE,
        translation_key=SENSOR_LAST_TEMPERATURE,
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
        native_unit_of_measurement=UnitOfVolumeFlowRate.LITERS_PER_MINUTE,
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_key="last_shower",
        sub_key="flow",
    ),
    HydraoSensorDescription(
        key=SENSOR_LAST_DURATION,
        translation_key=SENSOR_LAST_DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_key="last_shower",
        sub_key="duration",
    ),
    HydraoSensorDescription(
        key=SENSOR_LAST_SOAPING,
        translation_key=SENSOR_LAST_SOAPING,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_key="last_shower",
        sub_key="soaping_time",
        transform=lambda v: round(v / 60, 2) if v else None,  # stored in seconds
    ),
    HydraoSensorDescription(
        key=SENSOR_LAST_DATE,
        translation_key=SENSOR_LAST_DATE,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_key="last_shower",
        sub_key="date",
        transform=lambda v: datetime.fromisoformat(v) if v else None,
    ),
    # Diagnostics
    HydraoSensorDescription(
        key=SENSOR_RSSI,
        translation_key=SENSOR_RSSI,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_key="rssi",
    ),
    HydraoSensorDescription(
        key=SENSOR_FW_VERSION,
        translation_key=SENSOR_FW_VERSION,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_key="fw_version",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HydraoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        HydraoSensorEntity(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
    )


class HydraoSensorEntity(HydraoEntity, SensorEntity):
    """A sensor of a Hydrao shower head."""

    entity_description: HydraoSensorDescription

    def __init__(
        self,
        coordinator: HydraoCoordinator,
        description: HydraoSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Return whether the value can be trusted."""
        if self.entity_description.key == SENSOR_TOTAL_VOLUME:
            # Known from storage, no need to wait for the next shower
            return self.coordinator.device.total_volume is not None
        return super().available

    @property
    def native_value(self) -> Any:
        """Return the value of the sensor."""
        description = self.entity_description
        raw = self.coordinator.data.get(description.value_key)

        if description.sub_key is not None:
            if raw is None:
                return None
            raw = raw.get(description.sub_key)

        if raw is None:
            return None
        if description.transform:
            return description.transform(raw)
        if isinstance(raw, float):
            return round(raw, 2)
        return raw
