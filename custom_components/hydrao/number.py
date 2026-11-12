"""Hydrao numbers: volumes of the LED thresholds."""
from __future__ import annotations

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    THRESHOLD_COUNT,
    THRESHOLD_MAX_VOLUME,
    THRESHOLD_MIN_GAP,
    THRESHOLD_MIN_VOLUME,
)
from .coordinator import HydraoConfigEntry
from .entity import HydraoThresholdEntity

# The request is queued, nothing is sent from here
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HydraoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the numbers."""
    async_add_entities(
        HydraoThresholdVolume(entry.runtime_data, index, "volume")
        for index in range(THRESHOLD_COUNT)
    )


class HydraoThresholdVolume(HydraoThresholdEntity, NumberEntity):
    """Volume up to which the shower head shows the color of a threshold.

    Like in the Hydrao app, a threshold stays at least 2 liters away from
    its neighbors.
    """

    _attr_translation_key = "threshold_volume"
    _attr_device_class = NumberDeviceClass.VOLUME
    _attr_native_unit_of_measurement = UnitOfVolume.LITERS
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    @property
    def native_value(self) -> float:
        """Return the volume of the threshold."""
        return float(self._thresholds[self._index]["liter"])

    @property
    def native_min_value(self) -> float:
        """Return the lowest volume the previous threshold allows."""
        if self._index == 0:
            return THRESHOLD_MIN_VOLUME
        return float(self._thresholds[self._index - 1]["liter"]) + THRESHOLD_MIN_GAP

    @property
    def native_max_value(self) -> float:
        """Return the highest volume the next threshold allows."""
        if self._index == THRESHOLD_COUNT - 1:
            return THRESHOLD_MAX_VOLUME
        return float(self._thresholds[self._index + 1]["liter"]) - THRESHOLD_MIN_GAP

    async def async_set_native_value(self, value: float) -> None:
        """Change the volume of the threshold."""
        self._change("liter", float(round(value)))
