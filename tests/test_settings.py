"""Tests of the settings: LED thresholds and end of the shower."""
from __future__ import annotations

from typing import Any

from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
import pytest

from custom_components.hydrao.const import DEFAULT_THRESHOLDS, DOMAIN
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.components.number import (
    ATTR_MAX,
    ATTR_MIN,
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.components.select import (
    ATTR_OPTION,
    ATTR_OPTIONS,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

PREFIX = "hydrao_shower_test"
END_SHOWER = f"button.{PREFIX}_end_shower"
VOLUME_1 = f"number.{PREFIX}_led_threshold_1_volume"
VOLUME_2 = f"number.{PREFIX}_led_threshold_2_volume"
VOLUME_4 = f"number.{PREFIX}_led_threshold_4_volume"
COLOR_1 = f"select.{PREFIX}_led_threshold_1_color"
COLOR_3 = f"select.{PREFIX}_led_threshold_3_color"


def storage_key(entry: MockConfigEntry) -> str:
    """Return where the integration stores its state."""
    return f"{DOMAIN}.{entry.entry_id}"


@pytest.fixture
async def known_thresholds(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> MockConfigEntry:
    """Set up the integration with thresholds read at an earlier shower."""
    mock_config_entry.add_to_hass(hass)
    hass_storage[storage_key(mock_config_entry)] = {
        "version": 1,
        "data": {"thresholds": DEFAULT_THRESHOLDS},
    }
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry


async def test_thresholds_unknown_before_the_first_shower(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The thresholds are not guessed."""
    assert hass.states.get(VOLUME_1).state == STATE_UNAVAILABLE
    assert hass.states.get(COLOR_1).state == STATE_UNAVAILABLE


async def test_thresholds_shown_between_showers(
    hass: HomeAssistant, known_thresholds: MockConfigEntry
) -> None:
    """Known thresholds are shown with the shower head away."""
    state = hass.states.get(VOLUME_1)
    assert float(state.state) == 5
    assert state.attributes[ATTR_MIN] == 2
    assert state.attributes[ATTR_MAX] == 8

    state = hass.states.get(VOLUME_2)
    assert float(state.state) == 10
    assert state.attributes[ATTR_MIN] == 7
    assert state.attributes[ATTR_MAX] == 13

    state = hass.states.get(VOLUME_4)
    assert float(state.state) == 20
    assert state.attributes[ATTR_MIN] == 17
    assert state.attributes[ATTR_MAX] == 250

    state = hass.states.get(COLOR_1)
    assert state.state == "green"
    assert "light_blue" in state.attributes[ATTR_OPTIONS]
    assert hass.states.get(COLOR_3).state == "purple"


async def test_set_threshold_volume(
    hass: HomeAssistant,
    known_thresholds: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """A new volume is shown at once and kept for the next shower."""
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: VOLUME_1, ATTR_VALUE: 7},
        blocking=True,
    )
    await hass.async_block_till_done()
    device = known_thresholds.runtime_data.device
    assert device.threshold_request is not None
    assert [t["liter"] for t in device.threshold_request] == [7, 10, 15, 20]
    assert device.thresholds == DEFAULT_THRESHOLDS
    assert float(hass.states.get(VOLUME_1).state) == 7
    assert hass.states.get(VOLUME_2).attributes[ATTR_MIN] == 9

    async_fire_time_changed(hass, dt_util.utcnow().replace(year=2100))
    await hass.async_block_till_done()
    stored = hass_storage[storage_key(known_thresholds)]["data"]
    assert stored["threshold_request"] == device.threshold_request
    assert stored["thresholds"] == DEFAULT_THRESHOLDS


async def test_threshold_volume_too_close_to_the_next(
    hass: HomeAssistant, known_thresholds: MockConfigEntry
) -> None:
    """Like in the app, thresholds stay 2 liters apart."""
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: VOLUME_1, ATTR_VALUE: 9},
            blocking=True,
        )
    assert known_thresholds.runtime_data.device.threshold_request is None


async def test_set_threshold_color(
    hass: HomeAssistant, known_thresholds: MockConfigEntry
) -> None:
    """A color is sent with the value the app uses."""
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: COLOR_3, ATTR_OPTION: "orange"},
        blocking=True,
    )
    await hass.async_block_till_done()
    device = known_thresholds.runtime_data.device
    assert device.threshold_request is not None
    assert device.threshold_request[2] == {"color": "#FF5000", "liter": 15.0}
    assert hass.states.get(COLOR_3).state == "orange"


async def test_requests_survive_a_restart(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """What waits for the shower head is restored."""
    request = [{**threshold, "color": "#FF0000"} for threshold in DEFAULT_THRESHOLDS]
    mock_config_entry.add_to_hass(hass)
    hass_storage[storage_key(mock_config_entry)] = {
        "version": 1,
        "data": {
            "thresholds": DEFAULT_THRESHOLDS,
            "threshold_request": request,
            "need_reset_volume": True,
        },
    }
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    device = mock_config_entry.runtime_data.device
    assert device.threshold_request == request
    assert device.need_reset_volume is True
    assert hass.states.get(COLOR_1).state == "red"


async def test_end_shower(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """The button works with the shower head away and the request is kept."""
    assert hass.states.get(END_SHOWER).state != STATE_UNAVAILABLE
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: END_SHOWER}, blocking=True
    )
    await hass.async_block_till_done()
    assert init_integration.runtime_data.device.need_reset_volume is True

    async_fire_time_changed(hass, dt_util.utcnow().replace(year=2100))
    await hass.async_block_till_done()
    stored = hass_storage[storage_key(init_integration)]["data"]
    assert stored["need_reset_volume"] is True
