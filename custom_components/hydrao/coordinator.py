"""Hydrao coordinator: bridges the BLE client callbacks to Home Assistant."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .ble_client import HydraoDevice
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

type HydraoConfigEntry = ConfigEntry[HydraoCoordinator]


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
        store: Store[dict[str, int | None]],
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
        self._saved_index = device.last_sync_max_index
        self._was_showering = False
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

        # The history position and the total must be saved together
        if self.device.last_sync_max_index != self._saved_index:
            self._saved_index = self.device.last_sync_max_index
            self._store.async_delay_save(self._history_state, 1)

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

    def _history_state(self) -> dict[str, int | None]:
        """Return what has to survive a restart."""
        return {
            "last_sync_max_index": self.device.last_sync_max_index,
            "total_volume": self.device.total_volume,
        }

    async def _async_update_data(self) -> dict[str, Any]:
        """Return the current snapshot, a refresh has nothing to fetch."""
        return self.device.as_dict()
