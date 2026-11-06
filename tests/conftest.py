"""Common fixtures for the Hydrao tests."""
from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.components.bluetooth import generate_advertisement_data, generate_ble_device

from custom_components.hydrao.const import CHAR, DOMAIN
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant

ADDRESS = "E0:BF:E9:5A:10:52"
NAME = "HYDRAO_SHOWER_TEST"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the integration from custom_components."""


@pytest.fixture(autouse=True)
def auto_mock_bluetooth(mock_bluetooth: None) -> None:
    """Set up Bluetooth without an adapter."""


def make_service_info(
    address: str = ADDRESS, name: str | None = NAME
) -> BluetoothServiceInfoBleak:
    """Return the advertisement of a shower head."""
    return BluetoothServiceInfoBleak(
        name=name or "",
        address=address,
        rssi=-60,
        manufacturer_data={},
        service_data={},
        service_uuids=[],
        source="local",
        device=generate_ble_device(address, name),
        advertisement=generate_advertisement_data(local_name=name),
        connectable=True,
        time=0,
        tx_power=None,
    )


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=NAME,
        data={CONF_ADDRESS: ADDRESS, CONF_NAME: NAME},
        unique_id=ADDRESS,
    )


@pytest.fixture
async def init_integration(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> MockConfigEntry:
    """Set up the integration with no shower head around."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry


@pytest.fixture
def no_sleep() -> Generator[AsyncMock]:
    """Do not wait in the BLE client."""
    with patch(
        "custom_components.hydrao.ble_client.asyncio.sleep", AsyncMock()
    ) as sleep:
        yield sleep


class FakeClient:
    """A BLE client answering from a dict of characteristics."""

    def __init__(self, values: dict[str, bytes] | None = None) -> None:
        """Initialize the client."""
        self.values = {CHAR[name]: data for name, data in (values or {}).items()}
        self.is_connected = True
        self.writes: list[tuple[str, bytes]] = []
        self.start_notify = AsyncMock()
        self.stop_notify = AsyncMock()

    async def __aenter__(self) -> FakeClient:
        """Enter the connection."""
        return self

    async def __aexit__(self, *_: Any) -> None:
        """Leave the connection."""

    async def read_gatt_char(self, uuid: str) -> bytes:
        """Read a characteristic."""
        value = self.values[uuid]
        if isinstance(value, Exception):
            raise value
        return value

    async def write_gatt_char(self, uuid: str, data: bytes, response: bool) -> None:
        """Write a characteristic."""
        self.writes.append((uuid, data))


def snapshot_collector() -> tuple[MagicMock, list[dict[str, Any]]]:
    """Return a callback and the list of snapshots it receives."""
    received: list[dict[str, Any]] = []
    return MagicMock(side_effect=received.append), received
