"""Shared fixtures and helpers."""

from __future__ import annotations

import pytest
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from habluetooth import BluetoothServiceInfoBleak

from custom_components.powerroam_ble import protocol

from .frames import CHARGING

# A made-up address; the tests never use a real unit's.
ADDRESS = "AA:BB:CC:DD:EE:FF"
NAME = "ugreen gs1200"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the integration from custom_components/."""


def service_info(name: str = NAME, address: str = ADDRESS) -> BluetoothServiceInfoBleak:
    """An advertisement as Home Assistant's Bluetooth stack reports it."""
    return BluetoothServiceInfoBleak(
        name=name,
        address=address,
        rssi=-70,
        manufacturer_data={},
        service_data={},
        service_uuids=[],
        source="local",
        device=BLEDevice(address, name, None),
        advertisement=AdvertisementData(
            local_name=name,
            manufacturer_data={},
            service_data={},
            service_uuids=[],
            tx_power=None,
            rssi=-70,
            platform_data=(),
        ),
        connectable=True,
        time=0,
        tx_power=None,
    )


def reply(cmd: int, data: bytes) -> bytes:
    """A frame as the unit sends it (C0 A1 prefix)."""
    body = protocol.REPLY_PREFIX + bytes([cmd]) + len(data).to_bytes(2, "little") + data
    return protocol.HEADER + body + protocol.crc16_modbus(body).to_bytes(2, "little")


def stream(payloads: dict[int, str] = CHARGING) -> bytes:
    """Every payload of a capture as one notification, padded like the unit pads."""
    return b"".join(reply(cmd, bytes.fromhex(hexed)) for cmd, hexed in payloads.items()) + bytes(8)
