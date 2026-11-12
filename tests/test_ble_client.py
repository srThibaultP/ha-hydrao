"""Tests of the BLE client."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import struct
from unittest.mock import AsyncMock, MagicMock, patch

from bleak.exc import BleakError
import pytest

from custom_components.hydrao.ble_client import FAILURES_BEFORE_WARNING, HydraoDevice
from custom_components.hydrao.const import (
    CHAR,
    DEFAULT_THRESHOLDS,
    LEGACY_FLOW,
    RESET_VOLUME_COMMAND,
)
from custom_components.hydrao.protocol import encode_thresholds

from .conftest import ADDRESS, FakeClient, snapshot_collector

ESTABLISH = "custom_components.hydrao.ble_client.establish_connection"

NEW_THRESHOLDS = [
    {"color": "#FAB900", "liter": 8.0},
    {"color": "#FF5000", "liter": 16.0},
    {"color": "#FF0000", "liter": 24.0},
    {"color": "#000000", "liter": 32.0},
]


def shower_frame(shower_id: int, volume: int) -> bytes:
    """Return a shower of the history."""
    return struct.pack("<HHBBB", shower_id, volume, 76, 25, 60)


def make_device() -> HydraoDevice:
    """Return a device with a known BLE device."""
    device = HydraoDevice(MagicMock(address=ADDRESS, name="Shower"), rssi=-60)
    device.name = "Shower"
    return device


def water_stopped(device: HydraoDevice) -> None:
    """Lose the connection for longer than a weak signal would."""
    device._on_disconnected()
    assert device._link_loss_timer is not None
    device._cancel_link_loss_timer()
    device._on_link_loss_timeout()


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
    assert device.thresholds_known is True
    assert client.writes == []


async def test_metadata_thresholds_are_sorted() -> None:
    """Thresholds are kept in the order of their volumes."""
    device = make_device()
    client = FakeClient(
        {"thresholds": encode_thresholds(list(reversed(DEFAULT_THRESHOLDS)))}
    )
    for name in ("uuid", "hw_version", "fw_version", "calibration"):
        client.values[CHAR[name]] = b""
    await device._read_metadata(client)  # type: ignore[arg-type]
    assert device.thresholds == DEFAULT_THRESHOLDS


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
    assert client.writes == [(CHAR["thresholds"], encode_thresholds(DEFAULT_THRESHOLDS))]
    assert device.thresholds == DEFAULT_THRESHOLDS
    assert device.thresholds_known is True


async def test_metadata_unreadable() -> None:
    """Failed reads leave the defaults."""
    device = make_device()
    client = FakeClient(
        dict.fromkeys(("uuid", "hw_version", "fw_version", "thresholds", "calibration"), BleakError("x"))  # type: ignore[arg-type]
    )
    await device._read_metadata(client)  # type: ignore[arg-type]
    assert device.uuid is None
    assert device.fw_version is None
    assert device.thresholds_known is False


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


async def test_sync_skips_empty_showers_for_good(no_sleep: AsyncMock) -> None:
    """An empty shower at the end is not asked again at each connection."""
    device = make_device()
    await device._sync_history(history_client(1, 3, {1: 10}))  # type: ignore[arg-type]
    assert device.total_volume == 10
    assert device.last_sync_max_index == 3


async def test_sync_reads_live_during_a_long_history(no_sleep: AsyncMock) -> None:
    """The running shower is refreshed every few showers."""
    device = make_device()
    device._live_tick = AsyncMock()  # type: ignore[method-assign]
    client = history_client(1, 11, dict.fromkeys(range(1, 12), 10))
    await device._sync_history(client)  # type: ignore[arg-type]
    assert device._live_tick.await_count == 2
    assert device.total_volume == 110


async def test_sync_dates_the_shower_followed_live(no_sleep: AsyncMock) -> None:
    """The history has no dates, the shower followed live gives its own."""
    device = make_device()
    await run_live(device, live_client([10, 30, 0]), 3)
    assert device.last_shower is not None
    date = device.last_shower["date"]
    assert device.last_shower["soaping_time"] is None

    await device._sync_history(history_client(1, 2, {1: 12, 2: 31}))  # type: ignore[arg-type]
    assert device.last_shower["volume"] == 31
    assert device.last_shower["soaping_time"] == 60
    assert device.last_shower["date"] == date

    # The date is used once
    await device._sync_history(history_client(1, 3, {3: 50}))  # type: ignore[arg-type]
    assert device.last_shower["date"] is None


async def test_sync_does_not_date_another_shower(no_sleep: AsyncMock) -> None:
    """A smaller shower is not the one that was followed live."""
    device = make_device()
    await run_live(device, live_client([10, 30, 0]), 3)
    await device._sync_history(history_client(1, 1, {1: 12}))  # type: ignore[arg-type]
    assert device.last_shower is not None
    assert device.last_shower["volume"] == 12
    assert device.last_shower["date"] is None


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
    """A shower that can not be read is asked again at the next connection."""
    device = make_device()
    client = FakeClient(
        {"shower_range": struct.pack("<HH", 1, 2), "shower_data": BleakError("x")}  # type: ignore[dict-item]
    )
    client.start_notify.side_effect = BleakError("no notify")
    await device._sync_history(client)  # type: ignore[arg-type]
    assert device.total_volume is None
    assert device.last_sync_max_index is None
    assert len(client.writes) == 1


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
    assert device.is_soaping is False


async def test_live_averages() -> None:
    """The averages of the shower head are shown and give the duration."""
    device = make_device()
    device.calibration = 500
    client = live_client([12])
    client.values[CHAR["live_flow"]] = struct.pack("<HH", 100, 200)
    client.values[CHAR["live_temp"]] = struct.pack("<HH", 76, 70)
    await run_live(device, client, 1)
    assert device.live_flow == pytest.approx(24)
    assert device.live_average_flow == pytest.approx(12)
    assert device.live_temperature == 38
    assert device.live_average_temperature == 35
    assert device.live_duration == pytest.approx(1)

    water_stopped(device)
    assert device.last_shower is not None
    assert device.last_shower["flow"] == pytest.approx(12)
    assert device.last_shower["temperature"] == 35
    assert device.live_average_flow is None
    device.close()


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
    assert device.live_average_flow == LEGACY_FLOW


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

    water_stopped(device)
    assert device.is_showering is False
    assert device.is_soaping is True
    assert device.live_volume == 0
    assert device.last_shower is not None
    assert device.last_shower["volume"] == 15

    # A second disconnection changes nothing
    timer = device._soaping_timer
    device._on_disconnected()
    assert device._soaping_timer is timer
    device.close()
    assert device._soaping_timer is None


async def test_short_connection_loss_keeps_the_shower() -> None:
    """A weak signal drops the connection without pausing the shower."""
    device = make_device()
    callback, received = snapshot_collector()
    device.register_callback(callback)
    await run_live(device, live_client([15]), 1)
    count = len(received)

    device._on_disconnected()
    timer = device._link_loss_timer
    assert timer is not None
    device._on_disconnected()
    assert device._link_loss_timer is timer
    assert device.is_showering is True
    assert device.is_soaping is False
    assert device.live_volume == 15
    assert device.last_shower is None
    assert len(received) == count

    await run_live(device, live_client([18]), 1)
    assert device._link_loss_timer is None
    assert device.live_volume == 18
    assert device.is_showering is True
    device.close()


async def test_long_connection_loss_pauses_the_shower() -> None:
    """The connection staying lost means the water stopped."""
    device = make_device()
    await run_live(device, live_client([15]), 1)
    with patch("custom_components.hydrao.ble_client.LINK_LOSS_GRACE", 0):
        device._on_disconnected()
        await asyncio.sleep(0.01)
    assert device._link_loss_timer is None
    assert device.is_showering is False
    assert device.is_soaping is True
    assert device.last_shower is not None
    assert device.last_shower["volume"] == 15

    device._on_disconnected()
    assert device._link_loss_timer is None
    device.close()


async def test_shower_joined_late_gets_its_real_start() -> None:
    """The date is the start of the shower, not of the connection."""
    device = make_device()
    device.calibration = 500
    client = live_client([24])
    client.values[CHAR["live_flow"]] = struct.pack("<HH", 100, 200)
    before = datetime.now(UTC)
    await run_live(device, client, 1)
    assert device.live_duration == pytest.approx(2)
    assert device._session_start is not None
    assert device._session_start <= before - timedelta(minutes=2) + timedelta(seconds=1)
    assert device._session_start >= before - timedelta(minutes=2, seconds=1)
    device.close()


async def test_shower_resumes_after_soaping() -> None:
    """Water back within the soaping time goes on with the same shower."""
    device = make_device()
    await run_live(device, live_client([15]), 1)
    water_stopped(device)
    assert device.last_shower is not None
    date = device.last_shower["date"]

    await run_live(device, live_client([15, 22]), 2)
    assert device.is_soaping is False
    assert device.is_showering is True
    assert device._soaping_timer is None
    water_stopped(device)
    assert device.last_shower["volume"] == 22
    assert device.last_shower["date"] == date
    device.close()


async def test_soaping_times_out() -> None:
    """Water off for too long closes the shower."""
    device = make_device()
    callback, received = snapshot_collector()
    device.register_callback(callback)
    await run_live(device, live_client([15]), 1)
    with patch("custom_components.hydrao.ble_client.SOAPING_TIME", 0):
        water_stopped(device)
    assert received[-1]["is_soaping"] is True
    await asyncio.sleep(0.01)
    assert received[-1]["is_soaping"] is False
    assert device._soaping_timer is None
    assert device._finished_shower is not None
    assert device._finished_shower["volume"] == 15


async def test_new_shower_during_soaping() -> None:
    """A lower volume during the soaping time is another shower."""
    device = make_device()
    await run_live(device, live_client([15]), 1)
    water_stopped(device)
    assert device.last_shower is not None
    date = device.last_shower["date"]

    await run_live(device, live_client([3]), 1)
    assert device.is_soaping is False
    assert device._finished_shower == {"date": date, "volume": 15}
    water_stopped(device)
    assert device.last_shower["volume"] == 3
    device.close()


async def test_end_shower_while_showering() -> None:
    """Ending a running shower closes it and resets the volume."""
    device = make_device()
    client = live_client([15, 16])
    await run_live(device, client, 1)

    device.end_shower()
    assert device.need_reset_volume is True
    assert device.last_shower is not None
    assert device.last_shower["volume"] == 15
    assert device.as_dict()["reset_volume_pending"] is True

    # The loop sends the reset and leaves, the shower head restarts
    client.is_connected = True
    await run_live(device, client, 5)
    assert client.writes == [(CHAR["reset_volume"], RESET_VOLUME_COMMAND)]
    assert device.need_reset_volume is False
    device._on_disconnected()
    assert device.is_soaping is False
    assert device.last_shower["volume"] == 15


async def test_end_shower_while_soaping() -> None:
    """Ending a paused shower stops the soaping and waits for the shower head."""
    device = make_device()
    await run_live(device, live_client([15]), 1)
    device._on_disconnected()

    device.end_shower()
    assert device.is_soaping is False
    assert device._soaping_timer is None
    assert device.need_reset_volume is True


async def test_reset_is_sent_even_when_not_acknowledged() -> None:
    """The shower head restarts on a reset and may not answer."""
    device = make_device()
    device.need_reset_volume = True
    client = FakeClient()
    client.write_gatt_char = AsyncMock(side_effect=BleakError("gone"))  # type: ignore[method-assign]
    assert await device._send_requests(client) is True  # type: ignore[arg-type]
    assert device.need_reset_volume is False


async def test_thresholds_request() -> None:
    """New thresholds wait for the shower head, then are written."""
    device = make_device()
    callback, received = snapshot_collector()
    device.register_callback(callback)

    device.set_thresholds(NEW_THRESHOLDS)
    assert received[-1]["thresholds"] == NEW_THRESHOLDS
    assert received[-1]["thresholds_pending"] is True

    client = FakeClient()
    assert await device._send_requests(client) is False  # type: ignore[arg-type]
    assert client.writes == [(CHAR["thresholds"], encode_thresholds(NEW_THRESHOLDS))]
    assert device.thresholds == NEW_THRESHOLDS
    assert device.thresholds_known is True
    assert received[-1]["thresholds_pending"] is False


async def test_thresholds_request_kept_until_written() -> None:
    """A failed write is tried again at the next occasion."""
    device = make_device()
    device.set_thresholds(NEW_THRESHOLDS)
    client = FakeClient()
    client.write_gatt_char = AsyncMock(side_effect=BleakError("x"))  # type: ignore[method-assign]
    assert await device._send_requests(client) is False  # type: ignore[arg-type]
    assert device.threshold_request == NEW_THRESHOLDS
    assert device.thresholds == DEFAULT_THRESHOLDS


async def test_thresholds_request_already_applied() -> None:
    """Asking for the current thresholds writes nothing."""
    device = make_device()
    device.set_thresholds(NEW_THRESHOLDS)
    device.set_thresholds([dict(threshold) for threshold in DEFAULT_THRESHOLDS])
    assert device.threshold_request is None

    device.threshold_request = list(DEFAULT_THRESHOLDS)
    client = FakeClient()
    await device._send_requests(client)  # type: ignore[arg-type]
    assert client.writes == []
    assert device.threshold_request is None


async def test_thresholds_changed_again_during_the_write() -> None:
    """A request made while another is written is not lost."""
    device = make_device()
    device.set_thresholds(NEW_THRESHOLDS)
    client = FakeClient()

    async def write(uuid: str, data: bytes, response: bool) -> None:
        device.threshold_request = list(DEFAULT_THRESHOLDS)

    client.write_gatt_char = write  # type: ignore[method-assign]
    await device._send_requests(client)  # type: ignore[arg-type]
    assert device.thresholds == NEW_THRESHOLDS
    assert device.threshold_request == DEFAULT_THRESHOLDS


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
    device._send_requests = manager.requests = AsyncMock(return_value=False)  # type: ignore[method-assign]
    device._live_tick = manager.tick = AsyncMock()  # type: ignore[method-assign]
    device._sync_history = manager.sync = AsyncMock()  # type: ignore[method-assign]
    device._live_monitor_loop = manager.live = AsyncMock()  # type: ignore[method-assign]
    await device._on_connected(MagicMock())
    assert [call[0] for call in manager.mock_calls] == [
        "metadata",
        "requests",
        "tick",
        "sync",
        "live",
    ]


async def test_connection_from_start_to_end() -> None:
    """A whole connection: settings, requests, history, then the shower."""
    device = make_device()
    device.set_thresholds(NEW_THRESHOLDS)
    callback, received = snapshot_collector()
    device.register_callback(callback)

    client = live_client([10, 11, 12])
    client.start_notify.side_effect = BleakError("no notify")
    client.values.update(
        {
            CHAR["uuid"]: bytes(range(16)),
            CHAR["hw_version"]: b"\x09",
            CHAR["fw_version"]: b"1.2.3\x00",
            CHAR["thresholds"]: encode_thresholds(DEFAULT_THRESHOLDS),
            CHAR["calibration"]: struct.pack("<H", 500),
            CHAR["shower_range"]: struct.pack("<HH", 1, 1),
            CHAR["shower_data"]: shower_frame(1, 30),
        }
    )
    remaining = 3  # one wait in the history, two in the live loop

    async def tick(_: float) -> None:
        nonlocal remaining
        remaining -= 1
        if remaining == 0:
            client.is_connected = False

    with patch("custom_components.hydrao.ble_client.asyncio.sleep", tick):
        await device._on_connected(client)  # type: ignore[arg-type]
    water_stopped(device)

    assert client.writes == [
        (CHAR["thresholds"], encode_thresholds(NEW_THRESHOLDS)),
        (CHAR["shower_request"], struct.pack("<H", 1)),
    ]
    assert device.thresholds == NEW_THRESHOLDS
    assert device.total_volume == 30
    # The shower was visible before the history was read
    showering = [snapshot["is_showering"] for snapshot in received]
    totals = [snapshot["total_volume"] for snapshot in received]
    assert showering.index(True) < totals.index(30)
    assert device.last_shower is not None
    assert device.last_shower["volume"] == 12
    assert device.is_soaping is True
    device.close()


async def test_on_connected_ends_after_a_reset() -> None:
    """Nothing is read from a shower head that restarts."""
    device = make_device()
    device._read_metadata = AsyncMock()  # type: ignore[method-assign]
    device._send_requests = AsyncMock(return_value=True)  # type: ignore[method-assign]
    device._live_tick = AsyncMock()  # type: ignore[method-assign]
    await device._on_connected(MagicMock())
    device._live_tick.assert_not_awaited()


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
