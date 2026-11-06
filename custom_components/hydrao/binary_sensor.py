"""Hydrao binary sensor: is a shower currently running."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import BINARY_IS_SHOWERING
from .coordinator import HydraoConfigEntry, HydraoCoordinator
from .entity import HydraoEntity

# Push integration, nothing is polled
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HydraoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensor."""
    async_add_entities([HydraoShoweringBinarySensor(entry.runtime_data)])


class HydraoShoweringBinarySensor(HydraoEntity, BinarySensorEntity):
    """On while the shower head reports a running shower."""

    _attr_translation_key = BINARY_IS_SHOWERING
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator: HydraoCoordinator) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, BINARY_IS_SHOWERING)

    @property
    def is_on(self) -> bool:
        """Return whether a shower is running."""
        return bool(self.coordinator.data.get("is_showering", False))
