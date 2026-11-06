"""
Hydrao BLE client for Home Assistant.
Handles connection, history sync and live polling for one device.

"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from bleak import BleakClient, BleakError
from bleak.backends.device import BLEDevice
from bleak_retry_connector import establish_connection

from .const import (
    CHAR,
    CONNECT_TIMEOUT,
    DEFAULT_CALIBRATION,
    DEFAULT_THRESHOLDS,
    LEGACY_FLOW,
    LIVE_POLL_INTERVAL,
    MAX_SOAPING_TIME,
    MIN_VALID_VOLUME,
)
from . import protocol as proto

_LOGGER = logging.getLogger(__name__)

# Callback signature: called whenever live or shower data changes
UpdateCallback = Callable[[dict[str, Any]], None]

# Consecutive failures, while the device is still advertising, before a
# connection problem is worth a warning instead of a debug line.
FAILURES_BEFORE_WARNING = 5


class HydraoDevice:
    """Manages a single Hydrao BLE device: connect → sync → live poll."""

    def __init__(self, ble_device: Optional[BLEDevice], rssi: int = 0) -> None:
        self.ble_device = ble_device
        self.address: str = ble_device.address if ble_device else ""
        self.rssi: int = rssi

        # Device metadata (populated on first connect)
        self.uuid: Optional[str] = None
        self.hw_version: Optional[int] = None
        self.fw_version: Optional[str] = None
        self.calibration: int = DEFAULT_CALIBRATION
        self.thresholds: list[dict] = list(DEFAULT_THRESHOLDS)
        self.name: str = (ble_device.name if ble_device and ble_device.name else "Shower")

        # Live state
        self.live_volume: int = 0
        self.live_flow: Optional[float] = None
        self.live_temperature: Optional[float] = None
        self.live_duration: Optional[float] = None
        self.is_showering: bool = False

        # Last completed shower
        self.last_shower: Optional[dict] = None

        # History sync state (persisted via HA storage)
        self.last_sync_max_index: Optional[int] = None

        # Water used by every shower read from the history (liters). Stays
        # None until the first sync, so the first value is a baseline.
        self.total_volume: Optional[int] = None

        # Internal
        self._stop = asyncio.Event()
        self._client: Optional[BleakClient] = None
        self._task: Optional[asyncio.Task] = None
        self._update_callbacks: list[UpdateCallback] = []
        self._shower_notif_event = asyncio.Event()
        self._shower_notif_data: Optional[bytes] = None
        # Tells whether HA still sees the showerhead advertising. The
        # showerhead only advertises during a shower, so once it disappears
        # there is nothing to connect to and retrying would only fill the logs.
        self._is_present: Callable[[], bool] = lambda: True

        # Live session accumulator
        self._session_active = False
        self._session_volume = 0
        self._session_flow_samples: list[float] = []
        self._session_temp_samples: list[float] = []
        self._session_start: Optional[datetime] = None

    # ── Public ────────────────────────────────────────────────────────────────

    def register_callback(self, cb: UpdateCallback) -> None:
        self._update_callbacks.append(cb)

    def unregister_callback(self, cb: UpdateCallback) -> None:
        self._update_callbacks.discard(cb) if hasattr(self._update_callbacks, "discard") else None
        if cb in self._update_callbacks:
            self._update_callbacks.remove(cb)

    def set_presence_check(self, is_present: Callable[[], bool]) -> None:
        """Set the function telling whether the device is still advertising."""
        self._is_present = is_present

    def start(self) -> None:
        """
        Start the background connection+polling task.
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
            "live_duration": self.live_duration,
            "is_showering": self.is_showering,
            # last shower
            "last_shower": self.last_shower,
            "total_volume": self.total_volume,
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
            except (BleakError, asyncio.TimeoutError, OSError) as err:
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
        await self._read_metadata(client)
        await self._sync_history(client)
        await self._live_monitor_loop(client)

    def _on_disconnected(self) -> None:
        """Reset all live state when the BLE connection is lost.

        The showerhead stops advertising as soon as it is put back on its
        holder, so we never see a natural 'volume = 0' frame at the end.
        We must clear live values here to avoid sensors staying stuck.
        """
        if self._session_active:
            # Build last_shower from whatever we accumulated
            avg_flow = (
                sum(self._session_flow_samples) / len(self._session_flow_samples)
                if self._session_flow_samples else None
            )
            avg_temp = (
                sum(self._session_temp_samples) / len(self._session_temp_samples)
                if self._session_temp_samples else None
            )
            duration = (self._session_volume / avg_flow) if avg_flow else None
            self.last_shower = {
                "volume": self._session_volume,
                "temperature": avg_temp,
                "flow": avg_flow,
                "duration": duration,
                "soaping_time": None,
                "date": (self._session_start or datetime.now(timezone.utc)).isoformat(),
            }
            _LOGGER.info(
                "[%s] Shower ended (disconnected): vol=%dL flow=%s temp=%s dur=%s",
                self.address, self._session_volume,
                f"{avg_flow:.1f}L/min" if avg_flow else "N/A",
                f"{avg_temp:.1f}°C" if avg_temp else "N/A",
                f"{duration:.1f}min" if duration else "N/A",
            )
            self._session_active = False
            self._session_volume = 0
            self._session_flow_samples = []
            self._session_temp_samples = []
            self._session_start = None

        # Reset all live sensors to zero / None
        self.live_volume = 0
        self.live_flow = None
        self.live_temperature = None
        self.live_duration = None
        self.is_showering = False
        self._notify_update()

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
                self.thresholds = decoded
            else:
                await self._write(client, "thresholds", proto.encode_thresholds(DEFAULT_THRESHOLDS))
        if cal_data:
            self.calibration = proto.decode_calibration(cal_data)

        _LOGGER.info(
            "[%s] Metadata: hw=%s fw=%s cal=%d",
            self.address, self.hw_version, self.fw_version, self.calibration,
        )
        self._notify_update()

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
        except Exception as exc:
            _LOGGER.debug("[%s] Notifications unavailable (%s), falling back to polling", self.address, exc)

        last_shower_data = None
        try:
            for shower_id in ids_to_fetch:
                if self._stop.is_set() or not client.is_connected:
                    break
                data = await self._fetch_one_shower(client, shower_id, use_notify=use_notify)
                if data:
                    last_shower_data = data
                    self.last_sync_max_index = shower_id
                    self.total_volume = (self.total_volume or 0) + data["volume"]
        finally:
            if use_notify:
                try:
                    await client.stop_notify(CHAR["shower_data"])
                except Exception:
                    pass

        if last_shower_data:
            self.last_shower = last_shower_data
            self._notify_update()
        _LOGGER.info("[%s] History sync done, last_index=%s", self.address, self.last_sync_max_index)

    def _on_shower_notification(self, _sender: int, data: bytearray) -> None:
        self._shower_notif_data = bytes(data)
        self._shower_notif_event.set()

    async def _fetch_one_shower(
        self, client: BleakClient, shower_id: int, *, use_notify: bool
    ) -> Optional[dict]:
        self._shower_notif_event.clear()
        self._shower_notif_data = None
        await self._write(client, "shower_request", proto.encode_shower_request(shower_id))

        if use_notify:
            try:
                await asyncio.wait_for(self._shower_notif_event.wait(), timeout=3.0)
                data = self._shower_notif_data
            except asyncio.TimeoutError:
                await asyncio.sleep(0.1)
                data = await self._read(client, "shower_data")
        else:
            await asyncio.sleep(0.2)
            data = await self._read(client, "shower_data")

        if not data:
            return None
        return proto.decode_shower_data(data, self.calibration)

    # ── Live monitor ──────────────────────────────────────────────────────────

    async def _live_monitor_loop(self, client: BleakClient) -> None:
        _LOGGER.info("[%s] Live monitor started", self.address)
        legacy = self.hw_version is not None and self.hw_version < 8

        while not self._stop.is_set() and client.is_connected:
            vol_data = await self._read(client, "live_volume")
            if vol_data is None:
                await asyncio.sleep(LIVE_POLL_INTERVAL)
                continue

            volume = proto.decode_live_volume(vol_data)

            if volume > 0:
                flow_data = await self._read(client, "live_flow")
                temp_data = await self._read(client, "live_temp")

                instant_flow, _ = proto.decode_live_flow(flow_data, self.calibration) if flow_data else (None, None)
                instant_temp, _ = proto.decode_live_temperature(temp_data) if temp_data else (None, None)

                if legacy:
                    instant_flow = LEGACY_FLOW

                if not self._session_active:
                    self._session_active = True
                    self._session_start = datetime.now(timezone.utc)
                    self._session_flow_samples = []
                    self._session_temp_samples = []
                    _LOGGER.info("[%s] Shower started", self.address)

                self._session_volume = volume
                if instant_flow is not None:
                    self._session_flow_samples.append(instant_flow)
                if instant_temp is not None:
                    self._session_temp_samples.append(instant_temp)

                live_duration = (volume / instant_flow) if instant_flow else None  # minutes

                self.live_volume = volume
                self.live_flow = instant_flow
                self.live_temperature = instant_temp
                self.live_duration = live_duration
                self.is_showering = True

            else:
                if self._session_active:
                    # Shower just ended → build last_shower record
                    self._session_active = False
                    avg_flow = (
                        sum(self._session_flow_samples) / len(self._session_flow_samples)
                        if self._session_flow_samples else None
                    )
                    avg_temp = (
                        sum(self._session_temp_samples) / len(self._session_temp_samples)
                        if self._session_temp_samples else None
                    )
                    duration = (self._session_volume / avg_flow) if avg_flow else None  # minutes
                    self.last_shower = {
                        "volume": self._session_volume,
                        "temperature": avg_temp,
                        "flow": avg_flow,
                        "duration": duration,
                        "soaping_time": None,
                        "date": (self._session_start or datetime.now(timezone.utc)).isoformat(),
                    }
                    _LOGGER.info(
                        "[%s] Shower ended: vol=%dL flow=%s temp=%s dur=%s",
                        self.address, self._session_volume,
                        f"{avg_flow:.1f}L/min" if avg_flow else "N/A",
                        f"{avg_temp:.1f}°C" if avg_temp else "N/A",
                        f"{duration:.1f}min" if duration else "N/A",
                    )

                self.live_volume = 0
                self.live_flow = None
                self.live_temperature = None
                self.live_duration = None
                self.is_showering = False

            self._notify_update()
            await asyncio.sleep(LIVE_POLL_INTERVAL)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _notify_update(self) -> None:
        snapshot = self.as_dict()
        for cb in self._update_callbacks:
            try:
                cb(snapshot)
            except Exception:
                _LOGGER.exception("[%s] Callback error", self.address)

    async def _read(self, client: BleakClient, char_name: str) -> Optional[bytes]:
        try:
            return bytes(await client.read_gatt_char(CHAR[char_name]))
        except Exception as exc:
            _LOGGER.debug("[%s] Read %s failed: %s", self.address, char_name, exc)
            return None

    async def _write(self, client: BleakClient, char_name: str, data: bytes) -> bool:
        try:
            await client.write_gatt_char(CHAR[char_name], data, response=True)
            return True
        except Exception as exc:
            _LOGGER.debug("[%s] Write %s failed: %s", self.address, char_name, exc)
            return False
