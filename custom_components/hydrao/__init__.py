"""Hydrao BLE integration for Home Assistant."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_address_present,
    async_ble_device_from_address,
    async_last_service_info,
    async_register_callback,
    async_track_unavailable,
)
from homeassistant.const import CONF_ADDRESS, CONF_NAME, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .ble_client import HydraoDevice
from .const import DOMAIN
from .coordinator import HydraoConfigEntry, HydraoCoordinator

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: HydraoConfigEntry) -> bool:
    """Set up a Hydrao device from a config entry.

    The showerhead only advertises over BLE while a shower is running, so it
    is normal for it to be unreachable most of the time. We never block setup
    on it being present: entities are created right away in an "unavailable"
    state, and a Bluetooth callback resolves/reconnects the device as soon as
    it shows up again (i.e. next time someone showers).
    """
    address: str = entry.data[CONF_ADDRESS]
    name: str = entry.data.get(CONF_NAME, address)

    device = HydraoDevice(ble_device=None, rssi=0)
    device.address = address
    device.name = name

    # Restore persisted metadata so firmware/hw sensors show right away,
    # even before the next shower connects.
    opts = entry.options
    if opts.get("fw_version"):
        device.fw_version = opts["fw_version"]
    if opts.get("hw_version") is not None:
        device.hw_version = opts["hw_version"]

    # Restore the history position and the total, so a restart neither reads
    # the showers again nor counts them twice. The LED thresholds and the
    # requests waiting for the next shower are restored too.
    store: Store[dict[str, Any]] = Store(
        hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
    )
    if stored := await store.async_load():
        device.last_sync_max_index = stored.get("last_sync_max_index")
        device.total_volume = stored.get("total_volume")
        if thresholds := stored.get("thresholds"):
            device.thresholds = thresholds
            device.thresholds_known = True
        device.threshold_request = stored.get("threshold_request")
        device.need_reset_volume = bool(stored.get("need_reset_volume"))

    # Stop reconnecting as soon as HA no longer sees the showerhead.
    device.set_presence_check(
        lambda: async_address_present(hass, address, connectable=True)
    )

    coordinator = HydraoCoordinator(hass, device, entry, store)

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # If the device is already visible (mid-shower at HA startup), start now.
    ble_device = async_ble_device_from_address(hass, address, connectable=True)
    if ble_device is not None:
        last_info = async_last_service_info(hass, address, connectable=True)
        device.update_ble_device(ble_device, last_info.rssi if last_info else 0)
        device.start()

    @callback
    def _on_bluetooth_event(
        service_info: BluetoothServiceInfoBleak, change: BluetoothChange
    ) -> None:
        """Connect to the shower head when it advertises."""
        device.update_ble_device(service_info.device, service_info.rssi or 0)
        device.start()  # no-op if already running

    @callback
    def _on_unavailable(service_info: BluetoothServiceInfoBleak) -> None:
        """Showerhead stopped advertising: stop trying to reach it."""
        _LOGGER.debug("[%s] No longer advertising, stopping connection loop", address)
        device.stop()

    unregister = async_register_callback(
        hass,
        _on_bluetooth_event,
        BluetoothCallbackMatcher(address=address, connectable=True),
        BluetoothScanningMode.ACTIVE,
    )

    entry.async_on_unload(unregister)
    entry.async_on_unload(
        async_track_unavailable(hass, _on_unavailable, address, connectable=True)
    )
    entry.async_on_unload(device.close)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: HydraoConfigEntry) -> bool:
    """Unload a Hydrao config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
