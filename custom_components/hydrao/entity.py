"""Base entity of the Hydrao integration."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import HydraoCoordinator


class HydraoEntity(CoordinatorEntity[HydraoCoordinator]):
    """An entity of a Hydrao shower head."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HydraoCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        device = coordinator.device
        self._attr_unique_id = f"{device.address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.address)},
            name=device.name,
            manufacturer=MANUFACTURER,
            model=f"HW v{device.hw_version}" if device.hw_version else "Shower Head",
            sw_version=device.fw_version,
        )

    @property
    def available(self) -> bool:
        """Unavailable until the shower head has been seen advertising once."""
        return self.coordinator.device.ble_device is not None
