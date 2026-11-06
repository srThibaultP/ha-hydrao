"""Tests of the GATT decoders."""
from __future__ import annotations

import struct

import pytest

from custom_components.hydrao import protocol as proto
from custom_components.hydrao.const import DEFAULT_CALIBRATION, DEFAULT_THRESHOLDS


def test_device_uuid() -> None:
    """All the UUID lengths are decoded."""
    assert proto.decode_device_uuid(bytes(range(16))) == (
        "03020100-0504-0706-0908-0A0B0C0D0E0F"
    )
    assert proto.decode_device_uuid(bytes(range(12))) == "03020100-07060504-0B0A0908"
    assert proto.decode_device_uuid(b"\x01\x02") == "0102"


def test_calibration() -> None:
    """A short frame falls back to the default calibration."""
    assert proto.decode_calibration(b"\x01") == DEFAULT_CALIBRATION
    assert proto.decode_calibration(struct.pack("<H", 600)) == 600


def test_thresholds_round_trip() -> None:
    """Thresholds decode what they encode."""
    encoded = proto.encode_thresholds(DEFAULT_THRESHOLDS)
    assert proto.decode_thresholds(encoded) == DEFAULT_THRESHOLDS
    assert not proto.thresholds_are_empty(DEFAULT_THRESHOLDS)
    assert proto.thresholds_are_empty(proto.decode_thresholds(bytes(16)))
    assert proto.decode_thresholds(b"\x00") == []


def test_shower_range_and_request() -> None:
    """The history range and the request are little endian."""
    assert proto.decode_shower_range(b"\x00") == (0, 0)
    assert proto.decode_shower_range(struct.pack("<HH", 2, 9)) == (2, 9)
    assert proto.encode_shower_request(258) == b"\x02\x01"


def test_live_volume() -> None:
    """The volume is the third byte."""
    assert proto.decode_live_volume(b"\x00") == 0
    assert proto.decode_live_volume(b"\x00\x00\x2a") == 42


def test_live_flow() -> None:
    """Flow rates need a raw value and a calibration."""
    assert proto.decode_live_flow(b"\x00", 545) == (None, None)
    instant, average = proto.decode_live_flow(struct.pack("<HH", 100, 0), 500)
    assert instant == pytest.approx(24)
    assert average is None
    assert proto.decode_live_flow(struct.pack("<HH", 100, 100), 0) == (None, None)


def test_live_temperature() -> None:
    """Temperatures use a raw scale, a sensor scale, and a no value range."""
    assert proto.decode_live_temperature(b"\x00") == (None, None)
    low, high = proto.decode_live_temperature(struct.pack("<HH", 76, 101))
    assert low == 38
    assert high == pytest.approx(36.9, abs=0.1)
    assert proto.decode_live_temperature(struct.pack("<HH", 3001, 3001)) == (None, None)


@pytest.mark.parametrize(
    "frame",
    [
        b"\x00",
        b"\x01" + b"\xff" * 6,
        struct.pack("<HHBBB", 1, 0, 1, 1, 1),
        struct.pack("<HHBBB", 1, 65535, 1, 1, 1),
        struct.pack("<HHBBB", 1, 2, 1, 1, 1),
    ],
)
def test_invalid_shower(frame: bytes) -> None:
    """Empty and too small showers are dropped."""
    assert proto.decode_shower_data(frame, 545) is None


def test_shower() -> None:
    """A shower is decoded with its flow and its duration."""
    shower = proto.decode_shower_data(struct.pack("<HHBBB", 7, 40, 76, 25, 200), 500)
    assert shower is not None
    assert shower["id"] == 7
    assert shower["volume"] == 40
    assert shower["temperature"] == 38
    assert shower["flow"] == pytest.approx(24)
    assert shower["duration"] == pytest.approx(40 / 24)
    assert shower["soaping_time"] == 180


def test_shower_without_flow_or_temperature() -> None:
    """Missing measures stay unknown."""
    shower = proto.decode_shower_data(struct.pack("<HHBBB", 7, 40, 255, 0, 0), 500)
    assert shower is not None
    assert shower["temperature"] is None
    assert shower["flow"] is None
    assert shower["duration"] is None


def test_shower_with_unusable_calibration() -> None:
    """No flow can be computed without a calibration."""
    shower = proto.decode_shower_data(struct.pack("<HHBBB", 7, 40, 76, 25, 0), 0)
    assert shower is not None
    assert shower["flow"] is None
    assert shower["duration"] is None
