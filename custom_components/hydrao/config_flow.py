"""Config flow for Hydrao — BLE discovery, with standard manual entry point."""
from __future__ import annotations

from typing import Any

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS, CONF_NAME

from .const import DEVICE_NAME_PREFIX, DOMAIN


class HydraoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow of Hydrao.

    Hydrao devices are found via passive BLE discovery (the showerhead only
    advertises while a shower is active). This flow supports both:
      - async_step_bluetooth: HA notifies automatically when it sees one.
      - async_step_user: standard "+ Add integration" entry point, showing
        any already-discovered device or guiding the user if none is found
        yet — this matches the pattern used by official BLE integrations
        (e.g. Govee, SwitchBot, Inkbird).
    """

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._address: str = ""
        self._name: str = ""

    # ── Automatic discovery (HA notification) ───────────────────────────────────

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Called by HA when a HYDRAO_SHOWER* advertisement is seen."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._address = discovery_info.address
        self._name = discovery_info.name or discovery_info.address
        self.context["title_placeholders"] = {"name": self._name}

        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Single confirm dialog — no fields to fill."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._name,
                data={CONF_ADDRESS: self._address, CONF_NAME: self._name},
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._name},
        )

    # ── Manual entry point ("+ Add integration") ────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the "+ Add integration" entry point.

        Standard entry point shown when the user clicks "+ Add integration"
        and searches for "Hydrao".

        Hydrao showerheads only advertise over BLE while a shower is active,
        so we can't trigger a scan here. Instead we check for any device
        HA's Bluetooth subsystem has already seen recently, and offer it
        directly. If none, we explain what to do.
        """
        already_configured = self._async_current_ids(include_ignore=False)

        discovered = [
            info
            for info in async_discovered_service_info(self.hass, connectable=True)
            if info.name
            and info.name.startswith(DEVICE_NAME_PREFIX)
            and info.address not in already_configured
        ]

        if not discovered:
            # No device seen yet — guide the user instead of showing an
            # empty/confusing form.
            return self.async_abort(reason="no_devices_found")

        # Exactly one (or more) device already advertising right now:
        # reuse the same confirm step as automatic discovery.
        info = discovered[0]
        await self.async_set_unique_id(info.address)
        self._abort_if_unique_id_configured()

        self._address = info.address
        self._name = info.name or info.address
        self.context["title_placeholders"] = {"name": self._name}

        return await self.async_step_bluetooth_confirm()
