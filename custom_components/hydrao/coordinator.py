"""Hydrao coordinator: bridges the BLE client callbacks to Home Assistant."""
from __future__ import annotations

import logging
from typing import Any, TypedDict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .ble_client import HydraoDevice
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

type HydraoConfigEntry = ConfigEntry[HydraoCoordinator]


class DeviceDetails(TypedDict, total=False):
    """What a shower head tells about itself once it was reached."""

    sw_version: str
    hw_version: str
    serial_number: str


def device_details(device: HydraoDevice) -> DeviceDetails:
    """Return what the shower head told about itself so far."""
    details = DeviceDetails()
    if device.fw_version:
        details["sw_version"] = device.fw_version
    if device.hw_version is not None:
        details["hw_version"] = str(device.hw_version)
    if device.uuid:
        details["serial_number"] = device.uuid
    return details


class HydraoCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for one shower head.

    Data is pushed by the BLE client, nothing is polled. The data is the latest
    snapshot from HydraoDevice.as_dict().
    """

    config_entry: HydraoConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        device: HydraoDevice,
        entry: HydraoConfigEntry,
        store: Store[dict[str, Any]],
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{device.address}",
        )
        self.device = device
        self._store = store
        self._saved_state = self._stored_state()
        self._was_showering = False
        self._device_details = device_details(device)
        self.data = device.as_dict()

        device.register_callback(self._on_device_update)

    @callback
    def _on_device_update(self, snapshot: dict[str, Any]) -> None:
        """Handle new data from the BLE client (live poll or history)."""
        self.async_set_updated_data(snapshot)

        # Log once when the shower head connects, once when it goes away
        showering = bool(snapshot.get("is_showering"))
        if showering != self._was_showering:
            _LOGGER.info(
                "[%s] %s",
                self.device.address,
                "Shower running" if showering else "Shower ended or out of range",
            )
        self._was_showering = showering

        # The history position and the total must be saved together, and the
        # requests must not be lost before the next shower
        if (state := self._stored_state()) != self._saved_state:
            self._saved_state = state
            self._store.async_delay_save(self._stored_state, 1)

        # Complete the device with what the shower head told about itself
        if (details := device_details(self.device)) != self._device_details:
            self._device_details = details
            dr.async_get(self.hass).async_get_or_create(
                config_entry_id=self.config_entry.entry_id,
                identifiers={(DOMAIN, self.device.address)},
                **details,
            )

        # Keep the versions so that they survive a restart
        entry = self.config_entry
        fw_version = snapshot.get("fw_version")
        hw_version = snapshot.get("hw_version")
        if fw_version and (
            entry.options.get("fw_version") != fw_version
            or entry.options.get("hw_version") != hw_version
        ):
            self.hass.config_entries.async_update_entry(
                entry,
                options={
                    **entry.options,
                    "fw_version": fw_version,
                    "hw_version": hw_version,
                },
            )

    def _stored_state(self) -> dict[str, Any]:
        """Return what has to survive a restart."""
        device = self.device
        return {
            "last_sync_max_index": device.last_sync_max_index,
            "total_volume": device.total_volume,
            "thresholds": device.thresholds if device.thresholds_known else None,
            "threshold_request": device.threshold_request,
            "need_reset_volume": device.need_reset_volume,
        }

    async def _async_update_data(self) -> dict[str, Any]:
        """Return the current snapshot, a refresh has nothing to fetch."""
        return self.device.as_dict()
