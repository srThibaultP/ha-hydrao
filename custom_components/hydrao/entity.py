"""Base entity of the Hydrao integration."""
from __future__ import annotations

from typing import Any

from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import HydraoCoordinator, device_details


class HydraoEntity(CoordinatorEntity[HydraoCoordinator]):
    """An entity of a Hydrao shower head."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HydraoCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        device = coordinator.device
        self._attr_unique_id = f"{device.address}_{key}"
        # The versions and the serial number are only known once the shower
        # head was reached: the coordinator completes the device then.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.address)},
            connections={(CONNECTION_BLUETOOTH, device.address)},
            name=device.name,
            manufacturer=MANUFACTURER,
            model=MODEL,
            **device_details(device),
        )

    @property
    def available(self) -> bool:
        """Unavailable until the shower head has been seen advertising once."""
        return self.coordinator.device.ble_device is not None


class HydraoThresholdEntity(HydraoEntity):
    """A setting of one of the four LED thresholds.

    The shower head lights a color until the shower reaches the volume of the
    threshold, then moves on to the next one. The settings are known between
    showers and a change waits for the shower head to come back.
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: HydraoCoordinator, index: int, key: str) -> None:
        """Initialize the setting of the threshold at this position."""
        super().__init__(coordinator, f"threshold_{index + 1}_{key}")
        self._index = index
        self._attr_translation_placeholders = {"number": str(index + 1)}

    @property
    def available(self) -> bool:
        """Available once the thresholds were read from the shower head."""
        return self.coordinator.device.thresholds_known

    @property
    def _thresholds(self) -> list[dict[str, Any]]:
        thresholds: list[dict[str, Any]] = self.coordinator.data["thresholds"]
        return thresholds

    def _change(self, key: str, value: Any) -> None:
        """Ask the shower head for the thresholds with one value changed."""
        thresholds = [dict(threshold) for threshold in self._thresholds]
        thresholds[self._index][key] = value
        self.coordinator.device.set_thresholds(thresholds)
