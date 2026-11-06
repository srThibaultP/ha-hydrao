"""Diagnostics support for Hydrao."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant

from .coordinator import HydraoConfigEntry

TO_REDACT = {CONF_ADDRESS, CONF_NAME, "uuid"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: HydraoConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a Hydrao config entry."""
    coordinator = entry.runtime_data
    device = coordinator.device
    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "device": {
                "ble_device_known": device.ble_device is not None,
                "last_sync_max_index": device.last_sync_max_index,
                **coordinator.data,
            },
        },
        TO_REDACT,
    )
