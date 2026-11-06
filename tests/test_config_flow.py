"""Tests of the config flow."""
from __future__ import annotations

from unittest.mock import patch

from pytest_homeassistant.common import MockConfigEntry

from custom_components.hydrao.const import DOMAIN
from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_USER
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import ADDRESS, NAME, make_service_info

DISCOVERED = "custom_components.hydrao.config_flow.async_discovered_service_info"


async def test_bluetooth_discovery(hass: HomeAssistant) -> None:
    """A discovered shower head is added after a confirmation."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=make_service_info()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == NAME
    assert result["data"] == {CONF_ADDRESS: ADDRESS, CONF_NAME: NAME}
    assert result["result"].unique_id == ADDRESS


async def test_bluetooth_already_configured(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A shower head is only added once."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=make_service_info()
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_no_device(hass: HomeAssistant) -> None:
    """The flow explains what to do when nothing was seen."""
    with patch(DISCOVERED, return_value=[make_service_info(name="OTHER")]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_user_skips_configured_device(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A configured shower head is not offered again."""
    mock_config_entry.add_to_hass(hass)
    with patch(DISCOVERED, return_value=[make_service_info()]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_user_found(hass: HomeAssistant) -> None:
    """A shower head advertising right now can be added by hand."""
    with patch(DISCOVERED, return_value=[make_service_info()]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
    assert result["step_id"] == "bluetooth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ADDRESS] == ADDRESS
