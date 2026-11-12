"""Tests of the setup, the sensors and the diagnostics."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
import pytest

from custom_components.hydrao.const import DOMAIN
from custom_components.hydrao.diagnostics import async_get_config_entry_diagnostics
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .conftest import ADDRESS, NAME, make_service_info

PREFIX = "hydrao_shower_test"
TOTAL = f"sensor.{PREFIX}_total_water_volume"
VOLUME = f"sensor.{PREFIX}_last_shower_volume"
SOAPING = f"sensor.{PREFIX}_last_shower_soaping_time"
DATE = f"sensor.{PREFIX}_last_shower_date"
TEMPERATURE = f"sensor.{PREFIX}_last_shower_temperature"
LIVE_FLOW = f"sensor.{PREFIX}_live_flow_rate"
AVERAGE_FLOW = f"sensor.{PREFIX}_live_average_flow_rate"
AVERAGE_TEMPERATURE = f"sensor.{PREFIX}_live_average_temperature"
CALIBRATION = f"sensor.{PREFIX}_flow_calibration"
SOAPING_NOW = f"binary_sensor.{PREFIX}_soaping"
SHOWERING = f"binary_sensor.{PREFIX}_showering"


def push(entry: MockConfigEntry, **changes: Any) -> None:
    """Change the device and push the new data."""
    device = entry.runtime_data.device
    for key, value in changes.items():
        setattr(device, key, value)
    device._notify_update()


async def test_setup_and_unload(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Entities exist right away, unavailable, and the entry unloads."""
    assert init_integration.state is ConfigEntryState.LOADED
    assert hass.states.get(VOLUME).state == STATE_UNAVAILABLE
    assert hass.states.get(SHOWERING).state == STATE_UNAVAILABLE
    assert hass.states.get(TOTAL).state == STATE_UNAVAILABLE

    assert await hass.config_entries.async_unload(init_integration.entry_id)
    assert init_integration.state is ConfigEntryState.NOT_LOADED


async def test_rssi_disabled_by_default(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    init_integration: MockConfigEntry,
) -> None:
    """The signal sensor has to be enabled by hand."""
    entry = entity_registry.async_get(f"sensor.{PREFIX}_ble_signal_strength")
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_restored_metadata_and_history(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """Versions, history position and total survive a restart."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={"fw_version": "1.2", "hw_version": 9}
    )
    hass_storage[f"{DOMAIN}.{mock_config_entry.entry_id}"] = {
        "version": 1,
        "data": {"last_sync_max_index": 12, "total_volume": 345},
    }
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    device = mock_config_entry.runtime_data.device
    assert device.fw_version == "1.2"
    assert device.hw_version == 9
    assert device.last_sync_max_index == 12
    assert hass.states.get(TOTAL).state == "345"


async def test_shower_head_already_advertising(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A shower running at startup connects right away."""
    mock_config_entry.add_to_hass(hass)
    info = make_service_info()
    with (
        patch(
            "custom_components.hydrao.async_ble_device_from_address",
            return_value=info.device,
        ),
        patch(
            "custom_components.hydrao.async_last_service_info", return_value=info
        ),
        patch(
            "custom_components.hydrao.ble_client.HydraoDevice.start"
        ) as start,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    start.assert_called_once()
    assert mock_config_entry.runtime_data.device.rssi == -60


async def test_shower_head_advertising_without_last_info(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The signal stays unknown without an advertisement."""
    mock_config_entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.hydrao.async_ble_device_from_address",
            return_value=make_service_info().device,
        ),
        patch("custom_components.hydrao.async_last_service_info", return_value=None),
        patch("custom_components.hydrao.ble_client.HydraoDevice.start"),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_config_entry.runtime_data.device.rssi == 0


async def test_advertisement_and_loss(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """An advertisement starts the client, its loss stops it."""
    callbacks: dict[str, Any] = {}

    def register(_hass: HomeAssistant, callback: Any, *_: Any) -> Any:
        callbacks["seen"] = callback
        return lambda: None

    def track(_hass: HomeAssistant, callback: Any, *_: Any, **__: Any) -> Any:
        callbacks["lost"] = callback
        return lambda: None

    mock_config_entry.add_to_hass(hass)
    with (
        patch("custom_components.hydrao.async_register_callback", register),
        patch("custom_components.hydrao.async_track_unavailable", track),
        patch("custom_components.hydrao.ble_client.HydraoDevice.start") as start,
        patch("custom_components.hydrao.ble_client.HydraoDevice.stop") as stop,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        info = make_service_info()
        callbacks["seen"](info, None)
        await hass.async_block_till_done()
        start.assert_called_once()
        assert hass.states.get(SHOWERING).state == STATE_OFF

        callbacks["lost"](info)
        stop.assert_called_once()
        await hass.config_entries.async_unload(mock_config_entry.entry_id)


async def test_presence_check(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The client asks Bluetooth whether the shower head is still there."""
    assert init_integration.runtime_data.device._is_present() is False


async def test_values(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Sensors show what the client pushes."""
    date = datetime(2026, 11, 6, 7, 30, tzinfo=UTC)
    push(init_integration, ble_device=make_service_info().device)
    await hass.async_block_till_done()
    assert hass.states.get(VOLUME).state == STATE_UNKNOWN
    assert hass.states.get(TOTAL).state == STATE_UNAVAILABLE

    push(
        init_integration,
        is_showering=True,
        is_soaping=True,
        live_flow=7.126,
        live_average_flow=6.5,
        live_average_temperature=37.25,
        calibration=600,
        last_shower={
            "volume": 40,
            "temperature": None,
            "soaping_time": 90,
            "date": date.isoformat(),
        },
        total_volume=120,
    )
    await hass.async_block_till_done()
    assert hass.states.get(SHOWERING).state == STATE_ON
    assert hass.states.get(VOLUME).state == "40"
    assert hass.states.get(TEMPERATURE).state == STATE_UNKNOWN
    assert hass.states.get(SOAPING_NOW).state == STATE_ON
    assert hass.states.get(LIVE_FLOW).state == "7.13"
    assert hass.states.get(AVERAGE_FLOW).state == "6.5"
    assert hass.states.get(AVERAGE_TEMPERATURE).state == "37.25"
    assert hass.states.get(CALIBRATION).state == "600"
    assert float(hass.states.get(SOAPING).state) == 1.5
    assert hass.states.get(DATE).state == date.isoformat()
    state = hass.states.get(TOTAL)
    assert state.state == "120"
    assert state.attributes["device_class"] == "water"
    assert state.attributes["state_class"] == "total_increasing"
    assert state.attributes["unit_of_measurement"] == "L"


async def test_transforms_keep_empty_values(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A zero soaping time and a missing date stay unknown."""
    push(
        init_integration,
        ble_device=make_service_info().device,
        last_shower={"soaping_time": 0, "date": ""},
    )
    await hass.async_block_till_done()
    assert hass.states.get(SOAPING).state == STATE_UNKNOWN
    assert hass.states.get(DATE).state == STATE_UNKNOWN


async def test_history_is_saved(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """The position and the total are written once they change."""
    push(init_integration, last_sync_max_index=7, total_volume=90)
    async_fire_time_changed(hass, dt_util.utcnow().replace(year=2100))
    await hass.async_block_till_done()
    assert hass_storage[f"{DOMAIN}.{init_integration.entry_id}"]["data"] == {
        "last_sync_max_index": 7,
        "total_volume": 90,
        "thresholds": None,
        "threshold_request": None,
        "need_reset_volume": False,
    }


async def test_versions_are_saved(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The versions go to the entry options."""
    push(init_integration, fw_version="1.3", hw_version=9)
    await hass.async_block_till_done()
    assert init_integration.options == {"fw_version": "1.3", "hw_version": 9}


async def test_showering_is_logged_on_change(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Start and end are logged once each."""
    caplog.set_level("INFO", "custom_components.hydrao")
    push(init_integration, is_showering=True)
    push(init_integration, is_showering=True)
    push(init_integration, is_showering=False)
    assert caplog.text.count("Shower running") == 1
    assert caplog.text.count("Shower ended or out of range") == 1


async def test_refresh_returns_snapshot(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A manual refresh keeps the current data."""
    coordinator = init_integration.runtime_data
    await coordinator.async_refresh()
    assert coordinator.data["address"] == ADDRESS


async def test_diagnostics(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Identifiers are redacted."""
    push(init_integration, uuid="SECRET", total_volume=12)
    result = await async_get_config_entry_diagnostics(hass, init_integration)
    assert result["entry"]["data"]["address"] == "**REDACTED**"
    assert result["entry"]["data"]["name"] == "**REDACTED**"
    assert result["device"]["address"] == "**REDACTED**"
    assert result["device"]["uuid"] == "**REDACTED**"
    assert result["device"]["total_volume"] == 12
    assert NAME not in str(result)
