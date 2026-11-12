"""Hydrao BLE client: connection, history sync and live polling of one device."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection

from . import protocol as proto
from .const import (
    CHAR,
    DEFAULT_CALIBRATION,
    DEFAULT_THRESHOLDS,
    LIVE_EVERY_N_SHOWERS,
    LINK_LOSS_GRACE,
    LIVE_POLL_INTERVAL,
    RESET_VOLUME_COMMAND,
    SOAPING_TIME,
)

_LOGGER = logging.getLogger(__name__)

# Callback signature: called whenever live or shower data changes
UpdateCallback = Callable[[dict[str, Any]], None]

# Consecutive failures, while the device is still advertising, before a
# connection problem is worth a warning instead of a debug line.
FAILURES_BEFORE_WARNING = 5


class HydraoDevice:
    """Manages a single Hydrao BLE device: connect → sync → live poll."""

    def __init__(self, ble_device: BLEDevice | None, rssi: int = 0) -> None:
        """Initialize the device."""
        self.ble_device = ble_device
        self.address: str = ble_device.address if ble_device else ""
        self.rssi: int = rssi

        # Device metadata (populated on first connect)
        self.uuid: str | None = None
        self.hw_version: int | None = None
        self.fw_version: str | None = None
        self.calibration: int = DEFAULT_CALIBRATION
        # LED thresholds of the shower head, sorted by volume. They are only
        # trusted once read from the shower head or restored from storage.
        self.thresholds: list[dict[str, Any]] = list(DEFAULT_THRESHOLDS)
        self.thresholds_known = False
        self.name: str = (ble_device.name if ble_device and ble_device.name else "Shower")

        # Live state
        self.live_volume: int = 0
        self.live_flow: float | None = None
        self.live_temperature: float | None = None
        self.live_average_flow: float | None = None
        self.live_average_temperature: float | None = None
        self.live_duration: float | None = None
        self.is_showering: bool = False
        # The water is off but the shower head still counts the same shower
        self.is_soaping: bool = False

        # Last completed shower
        self.last_shower: dict[str, Any] | None = None

        # Requests waiting for the next connection (persisted via HA storage),
        # as the shower head can only be reached while the water runs.
        self.threshold_request: list[dict[str, Any]] | None = None
        self.need_reset_volume: bool = False

        # History sync state (persisted via HA storage)
        self.last_sync_max_index: int | None = None

        # Water used by every shower read from the history (liters). Stays
        # None until the first sync, so the first value is a baseline.
        self.total_volume: int | None = None

        # Internal
        self._stop = asyncio.Event()
        self._client: BleakClient | None = None
        self._task: asyncio.Task[None] | None = None
        self._update_callbacks: list[UpdateCallback] = []
        self._shower_notif_event = asyncio.Event()
        self._shower_notif_data: bytes | None = None
        # Tells whether HA still sees the showerhead advertising. The
        # showerhead only advertises during a shower, so once it disappears
        # there is nothing to connect to and retrying would only fill the logs.
        self._is_present: Callable[[], bool] = lambda: True

        # Shower followed live. It survives the soaping break, during which
        # the shower head is off but keeps its count for the same shower.
        self._session_active = False
        self._session_volume = 0
        self._session_flow_samples: list[float] = []
        self._session_temp_samples: list[float] = []
        self._session_average_flow: float | None = None
        self._session_average_temperature: float | None = None
        self._session_start: datetime | None = None
        self._soaping_timer: asyncio.TimerHandle | None = None
        # A lost connection only means the water stopped once it lasted
        self._link_loss_timer: asyncio.TimerHandle | None = None
        # Date and volume of the last shower followed live, until the history
        # returns it: the history itself has no dates.
        self._finished_shower: dict[str, Any] | None = None

    # ── Public ────────────────────────────────────────────────────────────────

    def register_callback(self, cb: UpdateCallback) -> None:
        """Register a function called with every new snapshot."""
        self._update_callbacks.append(cb)

    def set_presence_check(self, is_present: Callable[[], bool]) -> None:
        """Set the function telling whether the device is still advertising."""
        self._is_present = is_present

    def start(self) -> None:
        """Start the background connection and polling task.

        No-op if no BLE device has been resolved yet (showerhead not
        advertising — e.g. no shower currently running). Call again via
        update_ble_device() once an advertisement is seen.
        """
        if self.ble_device is None:
            return
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._run_loop())

    def stop(self) -> None:
        """Stop the background task gracefully."""
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()

    def close(self) -> None:
        """Stop for good, when the integration is unloaded."""
        self.stop()
        self._cancel_link_loss_timer()
        self._cancel_soaping_timer()

    def set_thresholds(self, thresholds: list[dict[str, Any]]) -> None:
        """Ask for new LED thresholds.

        They are written within seconds during a shower, otherwise at the
        start of the next one.
        """
        self.threshold_request = None if thresholds == self.thresholds else thresholds
        self._notify_update()

    def end_shower(self) -> None:
        """End the current shower so that the next one starts from zero.

        The volume of the shower head is reset within seconds during a
        shower, otherwise at the start of the next one.
        """
        if self._session_active:
            self._publish_last_shower()
        self._end_session()
        self.need_reset_volume = True
        self._notify_update()

    def update_ble_device(self, ble_device: BLEDevice, rssi: int) -> None:
        """Update BLE device reference on rediscovery (used by scanner)."""
        changed = rssi != self.rssi or self.ble_device is None
        self.ble_device = ble_device
        self.address = ble_device.address
        self.rssi = rssi
        if changed:
            self._notify_update()

    def as_dict(self) -> dict[str, Any]:
        """Snapshot of all current data (passed to coordinator)."""
        return {
            "address": self.address,
            "name": self.name,
            "uuid": self.uuid,
            "hw_version": self.hw_version,
            "fw_version": self.fw_version,
            "calibration": self.calibration,
            "rssi": self.rssi,
            # live
            "live_volume": self.live_volume,
            "live_flow": self.live_flow,
            "live_temperature": self.live_temperature,
            "live_average_flow": self.live_average_flow,
            "live_average_temperature": self.live_average_temperature,
            "live_duration": self.live_duration,
            "is_showering": self.is_showering,
            "is_soaping": self.is_soaping,
            # last shower
            "last_shower": self.last_shower,
            "total_volume": self.total_volume,
            # settings, with the requested values while they wait to be sent
            "thresholds": self.threshold_request or self.thresholds,
            "thresholds_pending": self.threshold_request is not None,
            "reset_volume_pending": self.need_reset_volume,
        }

    # ── Connection loop ────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """Connect and reconnect for as long as the device is advertising.

        The loop ends as soon as the showerhead stops advertising (shower
        over, or out of range of every Bluetooth proxy). The next
        advertisement starts it again, so failures are expected and only
        logged at debug level unless they persist while the device is seen.
        """
        backoff = 5
        failures = 0
        while not self._stop.is_set():
            if not self._is_present():
                _LOGGER.debug("[%s] Not advertising, waiting for next shower", self.address)
                return
            try:
                await self._connect_and_run()
                backoff = 5
                failures = 0
            except asyncio.CancelledError:
                return
            except (BleakError, TimeoutError, OSError) as err:
                failures += 1
                if failures == FAILURES_BEFORE_WARNING and self._is_present():
                    _LOGGER.warning(
                        "[%s] Still unable to connect after %d attempts while the "
                        "device is advertising (signal %s dBm): %s",
                        self.address, failures, self.rssi, err,
                    )
                else:
                    _LOGGER.debug(
                        "[%s] BLE error (attempt %d): %s, retry in %ds",
                        self.address, failures, err, backoff,
                    )
            except Exception:
                _LOGGER.exception("[%s] Unexpected error", self.address)

            if self._stop.is_set():
                return
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    async def _connect_and_run(self) -> None:
        _LOGGER.debug("[%s] Connecting...", self.address)
        assert self.ble_device is not None
        client = await establish_connection(
            BleakClient,
            self.ble_device,
            self.address,
            disconnected_callback=lambda _: _LOGGER.debug("[%s] Disconnected", self.address),
            max_attempts=3,
        )
        self._client = client
        try:
            async with client:
                _LOGGER.debug("[%s] Connected", self.address)
                await self._on_connected(client)
        finally:
            self._client = None
            self._on_disconnected()

    # ── On connected ──────────────────────────────────────────────────────────

    async def _on_connected(self, client: BleakClient) -> None:
        """Follow the same steps as the Hydrao app once connected."""
        await self._read_metadata(client)
        if await self._send_requests(client):
            return
        # A first live read, so that the shower shows up before the history
        await self._live_tick(client)
        await self._sync_history(client)
        await self._live_monitor_loop(client)

    def _on_disconnected(self) -> None:
        """Handle the loss of the BLE connection.

        The shower head is powered by the water, so it disappears as soon as
        the water stops and we never see a natural 'volume = 0' frame at the
        end. A weak signal drops the connection the same way while the water
        still runs, so the shower is only paused once the connection stayed
        lost for a while. Until then the live values are kept.
        """
        if not self._session_active:
            self._clear_live()
            self._notify_update()
            return
        if self._link_loss_timer is None:
            self._link_loss_timer = asyncio.get_running_loop().call_later(
                LINK_LOSS_GRACE, self._on_link_loss_timeout
            )
            _LOGGER.debug("[%s] Connection lost during a shower", self.address)

    def _on_link_loss_timeout(self) -> None:
        """The connection did not come back: the water stopped."""
        self._link_loss_timer = None
        self._pause_session()
        self._clear_live()
        self._notify_update()

    def _cancel_link_loss_timer(self) -> None:
        if self._link_loss_timer is not None:
            self._link_loss_timer.cancel()
            self._link_loss_timer = None

    def _clear_live(self) -> None:
        self.live_volume = 0
        self.live_flow = None
        self.live_temperature = None
        self.live_average_flow = None
        self.live_average_temperature = None
        self.live_duration = None
        self.is_showering = False

    # ── Shower followed live ──────────────────────────────────────────────────

    def _follow_shower(self, volume: int, duration: float | None) -> None:
        """Start a shower, or resume the one paused for soaping.

        The duration is the one the shower head gives, in minutes: a shower
        joined late still gets the date it really started.
        """
        if not self._session_active:
            if self.is_soaping and volume >= self._session_volume:
                self._cancel_soaping_timer()
                self.is_soaping = False
                _LOGGER.info("[%s] Shower resumed after soaping", self.address)
            else:
                self._end_session()
                self._session_start = datetime.now(UTC) - timedelta(
                    minutes=duration or 0
                )
                _LOGGER.info("[%s] Shower started", self.address)
            self._session_active = True
        self._session_volume = volume

    def _publish_last_shower(self) -> None:
        """Build the last shower from what was read live.

        The history only returns it at the next connection, with the soaping
        time, and replaces this estimate.
        """
        volume = self._session_volume
        flows = self._session_flow_samples
        temperatures = self._session_temp_samples
        flow = self._session_average_flow or (sum(flows) / len(flows) if flows else None)
        temperature = self._session_average_temperature or (
            sum(temperatures) / len(temperatures) if temperatures else None
        )
        self.last_shower = {
            "volume": volume,
            "temperature": temperature,
            "flow": flow,
            "duration": volume / flow if flow else None,  # minutes
            "soaping_time": None,
            "date": self._session_start.isoformat() if self._session_start else None,
        }

    def _pause_session(self) -> None:
        """The water stopped: the shower is over unless it resumes in time."""
        self._publish_last_shower()
        self._session_active = False
        self.is_soaping = True
        self._soaping_timer = asyncio.get_running_loop().call_later(
            SOAPING_TIME - LINK_LOSS_GRACE, self._on_soaping_timeout
        )
        _LOGGER.info("[%s] Water stopped at %d L", self.address, self._session_volume)

    def _on_soaping_timeout(self) -> None:
        """The water stayed off too long, the shower head closed the shower."""
        self._soaping_timer = None
        self._end_session()
        self._notify_update()

    def _cancel_soaping_timer(self) -> None:
        if self._soaping_timer is not None:
            self._soaping_timer.cancel()
            self._soaping_timer = None

    def _end_session(self) -> None:
        """Close the shower followed live, the next volume is a new shower."""
        if self._session_start is not None:
            self._finished_shower = {
                "date": self._session_start.isoformat(),
                "volume": self._session_volume,
            }
        self._drop_session()

    def _drop_session(self) -> None:
        self._cancel_link_loss_timer()
        self._cancel_soaping_timer()
        self.is_soaping = False
        self._session_active = False
        self._session_volume = 0
        self._session_flow_samples = []
        self._session_temp_samples = []
        self._session_average_flow = None
        self._session_average_temperature = None
        self._session_start = None

    # ── Metadata ──────────────────────────────────────────────────────────────

    async def _read_metadata(self, client: BleakClient) -> None:
        uuid_data  = await self._read(client, "uuid")
        hw_data    = await self._read(client, "hw_version")
        fw_data    = await self._read(client, "fw_version")
        thresh_data = await self._read(client, "thresholds")
        cal_data   = await self._read(client, "calibration")

        if uuid_data:
            self.uuid = proto.decode_device_uuid(uuid_data)
        if hw_data:
            self.hw_version = hw_data[0]
        if fw_data:
            self.fw_version = fw_data.rstrip(b"\x00").decode("utf-8", errors="ignore")
        if thresh_data:
            decoded = proto.decode_thresholds(thresh_data)
            if not proto.thresholds_are_empty(decoded):
                self.thresholds = sorted(decoded, key=lambda t: t["liter"])
                self.thresholds_known = True
            elif await self._write(
                client, "thresholds", proto.encode_thresholds(DEFAULT_THRESHOLDS)
            ):
                self.thresholds = list(DEFAULT_THRESHOLDS)
                self.thresholds_known = True
        if cal_data:
            self.calibration = proto.decode_calibration(cal_data)

        _LOGGER.info(
            "[%s] Metadata: hw=%s fw=%s cal=%d",
            self.address, self.hw_version, self.fw_version, self.calibration,
        )
        self._notify_update()

    # ── Requests ──────────────────────────────────────────────────────────────

    async def _send_requests(self, client: BleakClient) -> bool:
        """Send what was asked while the shower head was away.

        Returns True when the volume was reset: the shower head restarts, so
        the connection is over.
        """
        request = self.threshold_request
        if request is not None and (
            request == self.thresholds
            or await self._write(client, "thresholds", proto.encode_thresholds(request))
        ):
            _LOGGER.info("[%s] LED thresholds set: %s", self.address, request)
            self.thresholds = request
            self.thresholds_known = True
            if self.threshold_request is request:
                self.threshold_request = None
            self._notify_update()

        if not self.need_reset_volume:
            return False
        # The shower head restarts right away and may not acknowledge the write
        await self._write(client, "reset_volume", RESET_VOLUME_COMMAND)
        _LOGGER.info("[%s] Volume reset", self.address)
        self.need_reset_volume = False
        # Anything read since the request still belonged to the ended shower
        self._drop_session()
        self._notify_update()
        return True

    # ── History sync ──────────────────────────────────────────────────────────

    async def _sync_history(self, client: BleakClient) -> None:
        range_data = await self._read(client, "shower_range")
        if not range_data:
            return
        device_min, device_max = proto.decode_shower_range(range_data)
        if device_max == 0:
            return

        stored_max = self.last_sync_max_index
        if stored_max is None:
            ids_to_fetch = list(range(device_min, device_max + 1))
        elif device_max < stored_max:
            # wraparound
            ids_to_fetch = list(range(0, device_max + 1))
        else:
            ids_to_fetch = list(range(stored_max + 1, device_max + 1))

        if not ids_to_fetch:
            _LOGGER.info("[%s] History up to date", self.address)
            return

        _LOGGER.info("[%s] Syncing %d shower(s)", self.address, len(ids_to_fetch))

        # Subscribe to notifications for faster transfer
        use_notify = False
        try:
            await client.start_notify(CHAR["shower_data"], self._on_shower_notification)
            await asyncio.sleep(0.2)
            use_notify = True
        except (BleakError, TimeoutError, OSError) as exc:
            _LOGGER.debug("[%s] Notifications unavailable (%s), falling back to polling", self.address, exc)

        last_shower_data = None
        try:
            for count, shower_id in enumerate(ids_to_fetch, start=1):
                if self._stop.is_set() or not client.is_connected:
                    break
                raw = await self._fetch_one_shower(client, shower_id, use_notify=use_notify)
                if raw is None:
                    # Not answered: read it again at the next connection
                    break
                # Empty showers are skipped for good, like the app does
                self.last_sync_max_index = shower_id
                data = proto.decode_shower_data(raw, self.calibration, self.hw_version)
                if data:
                    last_shower_data = data
                    self.total_volume = (self.total_volume or 0) + data["volume"]
                if count % LIVE_EVERY_N_SHOWERS == 0:
                    # Keep the running shower up to date during a long sync
                    await self._live_tick(client)
        finally:
            if use_notify:
                with contextlib.suppress(BleakError, TimeoutError, OSError):
                    await client.stop_notify(CHAR["shower_data"])

        # The newest shower of the history is the one followed live last
        # time, unless showers were taken out of range in between.
        finished, self._finished_shower = self._finished_shower, None
        if last_shower_data:
            if finished and last_shower_data["volume"] >= finished["volume"]:
                last_shower_data["date"] = finished["date"]
            self.last_shower = last_shower_data
            self._notify_update()
        _LOGGER.info("[%s] History sync done, last_index=%s", self.address, self.last_sync_max_index)

    def _on_shower_notification(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        self._shower_notif_data = bytes(data)
        self._shower_notif_event.set()

    async def _fetch_one_shower(
        self, client: BleakClient, shower_id: int, *, use_notify: bool
    ) -> bytes | None:
        self._shower_notif_event.clear()
        self._shower_notif_data = None
        await self._write(client, "shower_request", proto.encode_shower_request(shower_id))

        if use_notify:
            try:
                await asyncio.wait_for(self._shower_notif_event.wait(), timeout=3.0)
                data = self._shower_notif_data
            except TimeoutError:
                await asyncio.sleep(0.1)
                data = await self._read(client, "shower_data")
        else:
            await asyncio.sleep(0.2)
            data = await self._read(client, "shower_data")

        return data or None

    # ── Live monitor ──────────────────────────────────────────────────────────

    async def _live_monitor_loop(self, client: BleakClient) -> None:
        _LOGGER.info("[%s] Live monitor started", self.address)
        while not self._stop.is_set() and client.is_connected:
            if await self._send_requests(client):
                return
            await self._live_tick(client)
            await asyncio.sleep(LIVE_POLL_INTERVAL)

    async def _live_tick(self, client: BleakClient) -> None:
        """Read the running shower once."""
        vol_data = await self._read(client, "live_volume")
        if vol_data is None:
            return
        self._cancel_link_loss_timer()

        volume = proto.decode_live_volume(vol_data)

        if volume > 0:
            flow, average_flow = proto.decode_live_flow(
                await self._read(client, "live_flow"), self.calibration, self.hw_version
            )
            temperature, average_temperature = proto.decode_live_temperature(
                await self._read(client, "live_temp")
            )

            # Like the app, the duration comes from the average flow
            duration_flow = average_flow or flow
            duration = volume / duration_flow if duration_flow else None  # minutes

            self._follow_shower(volume, duration)
            if flow is not None:
                self._session_flow_samples.append(flow)
            if temperature is not None:
                self._session_temp_samples.append(temperature)
            self._session_average_flow = average_flow
            self._session_average_temperature = average_temperature

            self.live_volume = volume
            self.live_flow = flow
            self.live_temperature = temperature
            self.live_average_flow = average_flow
            self.live_average_temperature = average_temperature
            self.live_duration = duration
            self.is_showering = True

        else:
            # Connected with nothing counted: a new shower is starting
            if self._session_active:
                self._publish_last_shower()
            self._end_session()
            self._clear_live()

        self._notify_update()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _notify_update(self) -> None:
        snapshot = self.as_dict()
        for cb in self._update_callbacks:
            try:
                cb(snapshot)
            except Exception:
                _LOGGER.exception("[%s] Callback error", self.address)

    async def _read(self, client: BleakClient, char_name: str) -> bytes | None:
        try:
            return bytes(await client.read_gatt_char(CHAR[char_name]))
        except (BleakError, TimeoutError, OSError) as exc:
            _LOGGER.debug("[%s] Read %s failed: %s", self.address, char_name, exc)
            return None

    async def _write(self, client: BleakClient, char_name: str, data: bytes) -> bool:
        try:
            await client.write_gatt_char(CHAR[char_name], data, response=True)
            return True
        except (BleakError, TimeoutError, OSError) as exc:
            _LOGGER.debug("[%s] Write %s failed: %s", self.address, char_name, exc)
            return False
