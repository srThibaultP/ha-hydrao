"""Hydrao GATT binary protocol decoder."""
from __future__ import annotations

import struct
from typing import Any

from .const import (
    DEFAULT_CALIBRATION,
    LEGACY_FLOW,
    MAX_SOAPING_TIME,
    MIN_VALID_VOLUME,
    THRESHOLD_COLOR_ALIASES,
    THRESHOLD_COLORS,
)

_COLOR_NAMES = {
    **{value: name for name, value in THRESHOLD_COLORS.items()},
    **THRESHOLD_COLOR_ALIASES,
}

# ── Device UUID ───────────────────────────────────────────────────────────────

def decode_device_uuid(data: bytes) -> str:
    """Decode the device UUID."""
    if len(data) >= 16:
        p1 = struct.unpack_from("<I", data, 0)[0]
        p2 = struct.unpack_from("<H", data, 4)[0]
        p3 = struct.unpack_from("<H", data, 6)[0]
        p4 = struct.unpack_from("<H", data, 8)[0]
        p5 = data[10:16].hex().upper()
        return f"{p1:08X}-{p2:04X}-{p3:04X}-{p4:04X}-{p5}"
    elif len(data) >= 12:
        p1 = struct.unpack_from("<I", data, 0)[0]
        p2 = struct.unpack_from("<I", data, 4)[0]
        p3 = struct.unpack_from("<I", data, 8)[0]
        return f"{p1:08X}-{p2:08X}-{p3:08X}"
    return data.hex().upper()


# ── Calibration ───────────────────────────────────────────────────────────────

def decode_calibration(data: bytes) -> int:
    """Decode the flow calibration."""
    if len(data) < 2:
        return DEFAULT_CALIBRATION
    return int(struct.unpack_from("<H", data, 0)[0])


# ── Thresholds ────────────────────────────────────────────────────────────────

def decode_thresholds(data: bytes) -> list[dict[str, Any]]:
    """Decode the LED thresholds."""
    if len(data) < 16:
        return []
    result = []
    for i in range(4):
        off = i * 4
        liters = data[off]
        r, g, b = data[off + 1], data[off + 2], data[off + 3]
        result.append({"color": f"#{r:02X}{g:02X}{b:02X}", "liter": float(liters)})
    return result

def thresholds_are_empty(thresholds: list[dict[str, Any]]) -> bool:
    """Return whether no threshold is set."""
    return all(t["liter"] == 0 for t in thresholds)

def encode_thresholds(thresholds: list[dict[str, Any]]) -> bytes:
    """Encode the LED thresholds."""
    result = bytearray(16)
    for i, t in enumerate(thresholds[:4]):
        off = i * 4
        result[off] = int(t["liter"])
        color = t["color"].lstrip("#")
        result[off + 1] = int(color[0:2], 16)
        result[off + 2] = int(color[2:4], 16)
        result[off + 3] = int(color[4:6], 16)
    return bytes(result)

def threshold_color_name(color: str) -> str:
    """Return the name the app gives to a color, "off" when it has none."""
    return _COLOR_NAMES.get(color.upper(), "off")


# ── Shower range ──────────────────────────────────────────────────────────────

def decode_shower_range(data: bytes) -> tuple[int, int]:
    """Decode the first and last shower ids of the history."""
    if len(data) < 4:
        return 0, 0
    return struct.unpack_from("<H", data, 0)[0], struct.unpack_from("<H", data, 2)[0]

def encode_shower_request(shower_id: int) -> bytes:
    """Encode the request for one shower of the history."""
    return struct.pack("<H", shower_id)


# ── Live characteristics ──────────────────────────────────────────────────────

def decode_live_volume(data: bytes) -> int:
    """Decode the volume of the running shower."""
    if len(data) < 3:
        return 0
    return data[2]


def is_legacy(hw_version: int | None) -> bool:
    """Return whether the hardware is too old to measure the flow."""
    return hw_version is not None and hw_version < 8


def _convert_flow(raw: int, calibration: int, hw_version: int | None = None) -> float | None:
    if is_legacy(hw_version):
        return LEGACY_FLOW
    if raw == 0 or calibration == 0:
        return None
    return (1000 * 60 * 20) / (calibration * raw)


def decode_live_flow(
    data: bytes | None, calibration: int, hw_version: int | None = None
) -> tuple[float | None, float | None]:
    """Decode the instant and average flow rates."""
    if is_legacy(hw_version):
        return LEGACY_FLOW, LEGACY_FLOW
    if data is None or len(data) < 4:
        return None, None
    instant_raw = struct.unpack_from("<H", data, 0)[0]
    average_raw = struct.unpack_from("<H", data, 2)[0]
    return _convert_flow(instant_raw, calibration), _convert_flow(average_raw, calibration)


def _convert_temperature(raw: int) -> float | None:
    if raw == 0 or raw > 3000:
        return None
    elif raw > 100:
        return -0.02635 * (raw * 16) + 79.48293
    else:
        return raw / 2


def decode_live_temperature(data: bytes | None) -> tuple[float | None, float | None]:
    """Decode the instant and average temperatures."""
    if data is None or len(data) < 4:
        return None, None
    instant_raw = struct.unpack_from("<H", data, 0)[0]
    average_raw = struct.unpack_from("<H", data, 2)[0]
    return _convert_temperature(instant_raw), _convert_temperature(average_raw)


# ── Historical shower ─────────────────────────────────────────────────────────

def decode_shower_data(
    data: bytes, calibration: int, hw_version: int | None = None
) -> dict[str, Any] | None:
    """Decode one shower of the history."""
    if len(data) < 7:
        return None
    if all(b == 0xFF for b in data[1:]):
        return None

    shower_id = struct.unpack_from("<H", data, 0)[0]
    volume    = struct.unpack_from("<H", data, 2)[0]

    if volume == 0 or volume == 65535 or volume < MIN_VALID_VOLUME:
        return None

    temp_raw    = data[4]
    flow_raw    = data[5]
    soaping_time = min(data[6], MAX_SOAPING_TIME)

    temperature = None if temp_raw == 0xFF else _convert_temperature(temp_raw)
    flow = _convert_flow(flow_raw * 4, calibration, hw_version)
    duration = volume / flow if flow else None  # minutes (volume L / flow L/min)

    return {
        "id": shower_id,
        "volume": volume,
        "temperature": temperature,
        "flow": flow,
        "duration": duration,
        "soaping_time": soaping_time,
        "date": None,  # not stored in the history, known when followed live
    }
