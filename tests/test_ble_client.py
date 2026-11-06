"""Tests of the BLE client."""
from __future__ import annotations

import asyncio
import struct
from unittest.mock import AsyncMock, MagicMock, patch

from bleak.exc import BleakError
import pytest

from custom_components.hydrao.ble_client import FAILURES_BEFORE_WARNING, HydraoDevice
from custom_components.hydrao.const import CHAR, LEGACY_FLOW

from .conftest import ADDRESS, FakeClient, snapshot_collector

ESTABLISH = "custom_components.hydrao.ble_client.establish_connection"


def shower_frame(shower_id: int, volume: int) -> bytes:
    """Return a shower of the history."""
    return struct.pack("<HHBBB", shower_id, volume, 76, 25, 60)


def make_device() -> HydraoDevice:
    """Return a device with a known BLE device."""
    device = HydraoDevice(MagicMock(address=ADDRESS, name="Shower"), rssi=-60)
    device.name = "Shower"
    return device


def history_client(first: int, last: int, volumes: dict[int, int]) -> FakeClient:
    """Return a client serving a history over reads, without notifications."""
    client = FakeClient({"shower_range": struct.pack("<HH", first, last)})
    client.start_notify.side_effect = BleakError("no notify")

    async def write(uuid: str, data: bytes, response: bool) -> None:
        shower_id = struct.unpack("<H", data)[0]
        volume = volumes.get(shower_id, 0)
        client.values[CHAR["shower_data"]] = shower_frame(shower_id, volume)

    client.write_gatt_char = write  # type: ignore[method-assign]
    return client


def test_no_ble_device_yet() -> None:
    """Without a BLE device the name is generic and nothing starts."""
    device = HydraoDevice(None)
    assert device.address == ""
    assert device.name == "Shower"
    device.start()
    assert device._task is None
    device.stop()


def test_update_ble_device_notifies_on_change() -> None:
    """A new signal level is pushed, the same one is not."""
    device = HydraoDevice(None)
    callback, received = snapshot_collector()
    device.register_callback(callback)
    ble_device = MagicMock(address=ADDRESS)

    device.update_ble_device(ble_device, -60)
    assert received[-1]["rssi"] == -60
    device.update_ble_device(ble_device, -60)
    assert len(received) == 1


def test_callback_error_is_contained(caplog: pytest.LogCaptureFixture) -> None:
    """A failing callback does not stop the others."""
    device = make_device()
    other, received = snapshot_collector()
    device.register_callback(MagicMock(side_effect=ValueError))
    device.register_callback(other)
    device._notify_update()
    assert received
    assert "Callback error" in caplog.text


async def test_start_and_stop(no_sleep: AsyncMock) -> None:
    """The task starts once and stops on demand."""
    device = make_device()
    device._run_loop = AsyncMock(side_effect=lambda: asyncio.Event().wait())  # type: ignore[method-assign]
    device.start()
    task = device._task
    device.start()
    assert device._task is task
    await asyncio.sleep(0)
    device.stop()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_metadata_read_and_thresholds_kept() -> None:
    """Metadata is read, valid thresholds are not written back."""
    device = make_device()
    thresholds = bytes([5, 0, 255, 0] * 4)
    client = FakeClient(
        {
            "uuid": bytes(range(16)),
            "hw_version": b"\x09",
            "fw_version": b"1.2.3\x00",
            "thresholds": thresholds,
            "calibration": struct.pack("<H", 600),
        }
    )
    await device._read_metadata(client)  # type: ignore[arg-type]
    assert device.uuid is not None
    assert device.hw_version == 9
    assert device.fw_version == "1.2.3"
    assert device.calibration == 600
    assert device.thresholds[0]["liter"] == 5
    assert client.writes == []


async def test_metadata_empty_thresholds_are_written() -> None:
    """A shower head without thresholds gets the default ones."""
    device = make_device()
    client = FakeClient(
        {
            "uuid": b"\x01",
            "hw_version": b"\x09",
            "fw_version": b"1",
            "thresholds": bytes(16),
            "calibration": struct.pack("<H", 600),
        }
    )
    await device._read_metadata(client)  # type: ignore[arg-type]
    assert client.writes[0][0] == CHAR["thresholds"]


async def test_metadata_unreadable() -> None:
    """Failed reads leave the defaults."""
    device = make_device()
    client = FakeClient(
        dict.fromkeys(("uuid", "hw_version", "fw_version", "thresholds", "calibration"), BleakError("x"))  # type: ignore[arg-type]
    )
    await device._read_metadata(client)  # type: ignore[arg-type]
    assert device.uuid is None
    assert device.fw_version is None


async def test_write_failure_is_reported() -> None:
    """A failed write returns False."""
    device = make_device()
    client = FakeClient()
    client.write_gatt_char = AsyncMock(side_effect=BleakError("x"))  # type: ignore[method-assign]
    assert await device._write(client, "thresholds", b"\x00") is False  # type: ignore[arg-type]


async def test_sync_counts_each_shower_once(no_sleep: AsyncMock) -> None:
    """A second sync of the same history adds nothing."""
    device = make_device()
    callback, received = snapshot_collector()
    device.register_callback(callback)
    client = history_client(1, 4, {1: 10, 2: 20, 4: 40})  # 3 is not a valid shower

    await device._sync_history(client)  # type: ignore[arg-type]
    assert device.total_volume == 70
    assert device.last_sync_max_index == 4
    assert received[-1]["total_volume"] == 70
    assert received[-1]["last_shower"]["volume"] == 40

    await device._sync_history(client)  # type: ignore[arg-type]
    assert device.total_volume == 70


async def test_sync_adds_new_showers_only(no_sleep: AsyncMock) -> None:
    """A restored position only reads what is new."""
    device = make_device()
    device.last_sync_max_index = 4
    device.total_volume = 70
    await device._sync_history(history_client(1, 5, {5: 50}))  # type: ignore[arg-type]
    assert device.total_volume == 120
    assert device.last_sync_max_index == 5


async def test_sync_after_wraparound(no_sleep: AsyncMock) -> None:
    """A counter that went back to 0 is read from the start."""
    device = make_device()
    device.last_sync_max_index = 100
    device.total_volume = 500
    await device._sync_history(history_client(0, 1, {0: 10, 1: 20}))  # type: ignore[arg-type]
    assert device.total_volume == 530
    assert device.last_sync_max_index == 1


async def test_sync_nothing_to_read() -> None:
    """No range or an empty history leaves the total unknown."""
    device = make_device()
    await device._sync_history(FakeClient({"shower_range": b""}))  # type: ignore[arg-type]
    client = FakeClient({"shower_range": struct.pack("<HH", 0, 0)})
    await device._sync_history(client)  # type: ignore[arg-type]
    assert device.total_volume is None
    assert device.last_sync_max_index is None


async def test_sync_stops_when_disconnected(no_sleep: AsyncMock) -> None:
    """The sync stops with the connection, the rest is read next time."""
    device = make_device()
    client = history_client(1, 3, {1: 10, 2: 20, 3: 30})
    client.is_connected = False
    await device._sync_history(client)  # type: ignore[arg-type]
    assert device.total_volume is None


async def test_sync_with_notifications(no_sleep: AsyncMock) -> None:
    """Showers can come from notifications."""
    device = make_device()
    client = FakeClient({"shower_range": struct.pack("<HH", 1, 1)})
    client.stop_notify.side_effect = BleakError("gone")

    async def write(uuid: str, data: bytes, response: bool) -> None:
        device._on_shower_notification(MagicMock(), bytearray(shower_frame(1, 30)))

    client.write_gatt_char = write  # type: ignore[method-assign]
    await device._sync_history(client)  # type: ignore[arg-type]
    assert device.total_volume == 30


async def test_sync_notification_timeout(no_sleep: AsyncMock) -> None:
    """A missing notification falls back to a read."""
    device = make_device()
    client = FakeClient(
        {"shower_range": struct.pack("<HH", 1, 1), "shower_data": shower_frame(1, 30)}
    )
    with patch(
        "custom_components.hydrao.ble_client.asyncio.wait_for",
        AsyncMock(side_effect=TimeoutError),
    ) as wait_for:
        await device._sync_history(client)  # type: ignore[arg-type]
    wait_for.call_args.args[0].close()
    assert device.total_volume == 30


async def test_sync_unreadable_shower(no_sleep: AsyncMock) -> None:
    """A shower that can not be read is not counted."""
    device = make_device()
    client = FakeClient(
        {"shower_range": struct.pack("<HH", 1, 1), "shower_data": BleakError("x")}  # type: ignore[dict-item]
    )
    client.start_notify.side_effect = BleakError("no notify")
    await device._sync_history(client)  # type: ignore[arg-type]
    assert device.total_volume is None


def live_client(volumes: list[int], hw_flow: int = 100) -> FakeClient:
    """Return a client whose live volume follows a list, then disconnects."""
    client = FakeClient(
        {
            "live_flow": struct.pack("<HH", hw_flow, hw_flow),
            "live_temp": struct.pack("<HH", 76, 76),
        }
    )
    frames = iter(volumes)
    read = client.read_gatt_char

    async def read_gatt_char(uuid: str) -> bytes:
        if uuid != CHAR["live_volume"]:
            return await read(uuid)
        volume = next(frames)
        client.is_connected = bool(client.is_connected and volumes)
        if volume < 0:
            raise BleakError("x")
        return bytes([0, 0, volume])

    client.read_gatt_char = read_gatt_char  # type: ignore[method-assign]
    return client


async def run_live(device: HydraoDevice, client: FakeClient, frames: int) -> None:
    """Run the live loop for a number of frames."""
    remaining = frames

    async def tick(_: float) -> None:
        nonlocal remaining
        remaining -= 1
        if remaining == 0:
            client.is_connected = False

    with patch("custom_components.hydrao.ble_client.asyncio.sleep", tick):
        await device._live_monitor_loop(client)  # type: ignore[arg-type]


async def test_live_shower() -> None:
    """A running shower is followed, its end builds the last shower."""
    device = make_device()
    callback, received = snapshot_collector()
    device.register_callback(callback)

    await run_live(device, live_client([10, 20, 0]), 3)

    assert received[0]["is_showering"] is True
    assert received[0]["live_volume"] == 10
    assert received[0]["live_duration"] is not None
    assert received[-1]["is_showering"] is False
    assert received[-1]["live_volume"] == 0
    assert device.last_shower is not None
    assert device.last_shower["volume"] == 20
    assert device.last_shower["temperature"] == 38
    assert device.last_shower["duration"] is not None


async def test_live_read_failure_is_retried() -> None:
    """A failed live read waits for the next poll."""
    device = make_device()
    callback, received = snapshot_collector()
    device.register_callback(callback)
    await run_live(device, live_client([-1]), 1)
    assert received == []


async def test_live_legacy_hardware() -> None:
    """Old hardware has a fixed flow rate."""
    device = make_device()
    device.hw_version = 7
    await run_live(device, live_client([10]), 1)
    assert device.live_flow == LEGACY_FLOW


async def test_live_without_flow_and_temperature() -> None:
    """A shower is still tracked with no flow or temperature."""
    device = make_device()
    client = live_client([10, 0])
    client.values[CHAR["live_flow"]] = BleakError("x")  # type: ignore[assignment]
    client.values[CHAR["live_temp"]] = BleakError("x")  # type: ignore[assignment]
    await run_live(device, client, 2)
    assert device.last_shower is not None
    assert device.last_shower["flow"] is None
    assert device.last_shower["temperature"] is None
    assert device.last_shower["duration"] is None


async def test_disconnect_during_shower() -> None:
    """Losing the connection ends the shower and clears the live values."""
    device = make_device()
    await run_live(device, live_client([15]), 1)
    assert device.is_showering is True

    device._on_disconnected()
    assert device.is_showering is False
    assert device.live_volume == 0
    assert device.last_shower is not None
    assert device.last_shower["volume"] == 15


async def test_connect_and_run() -> None:
    """A connection reads the metadata, the history, then follows the shower."""
    device = make_device()
    device._on_connected = AsyncMock()  # type: ignore[method-assign]
    client = FakeClient()
    with patch(ESTABLISH, AsyncMock(return_value=client)) as establish:
        await device._connect_and_run()
    establish.call_args.kwargs["disconnected_callback"](client)
    device._on_connected.assert_awaited_once_with(client)
    assert device._client is None


async def test_on_connected_order() -> None:
    """The steps of a connection run in order."""
    device = make_device()
    manager = MagicMock()
    device._read_metadata = manager.metadata = AsyncMock()  # type: ignore[method-assign]
    device._sync_history = manager.sync = AsyncMock()  # type: ignore[method-assign]
    device._live_monitor_loop = manager.live = AsyncMock()  # type: ignore[method-assign]
    await device._on_connected(MagicMock())
    assert [call[0] for call in manager.mock_calls] == ["metadata", "sync", "live"]


async def test_run_loop_ends_when_not_advertising() -> None:
    """Nothing is attempted once the shower head is gone."""
    device = make_device()
    device.set_presence_check(lambda: False)
    device._connect_and_run = AsyncMock()  # type: ignore[method-assign]
    await device._run_loop()
    device._connect_and_run.assert_not_awaited()


async def test_run_loop_reconnects_until_gone(no_sleep: AsyncMock) -> None:
    """A finished connection is restarted while the device advertises."""
    device = make_device()
    present = iter([True, True, False])
    device.set_presence_check(lambda: next(present))
    device._connect_and_run = AsyncMock()  # type: ignore[method-assign]
    await device._run_loop()
    assert device._connect_and_run.await_count == 2


async def test_run_loop_warns_after_repeated_failures(
    no_sleep: AsyncMock, caplog: pytest.LogCaptureFixture
) -> None:
    """Failures are quiet at first, then worth one warning."""
    device = make_device()
    attempts = FAILURES_BEFORE_WARNING + 1
    device._connect_and_run = AsyncMock(side_effect=BleakError("x"))  # type: ignore[method-assign]
    checks = iter([True] * (attempts * 2) + [False] * 10)

    def present() -> bool:
        return next(checks)

    device.set_presence_check(present)
    await device._run_loop()
    assert caplog.text.count("Still unable to connect") == 1


async def test_run_loop_cancelled() -> None:
    """A cancellation ends the loop quietly."""
    device = make_device()
    device._connect_and_run = AsyncMock(side_effect=asyncio.CancelledError)  # type: ignore[method-assign]
    await device._run_loop()


async def test_run_loop_unexpected_error_then_stop(
    no_sleep: AsyncMock, caplog: pytest.LogCaptureFixture
) -> None:
    """An unexpected error is logged, a stop ends the loop right after."""
    device = make_device()

    async def fail() -> None:
        device._stop.set()
        raise ValueError

    device._connect_and_run = fail  # type: ignore[method-assign]
    await device._run_loop()
    assert "Unexpected error" in caplog.text
    no_sleep.assert_not_awaited()


async def test_run_loop_already_stopped() -> None:
    """A stopped device does not connect."""
    device = make_device()
    device._stop.set()
    device._connect_and_run = AsyncMock()  # type: ignore[method-assign]
    await device._run_loop()
    device._connect_and_run.assert_not_awaited()
