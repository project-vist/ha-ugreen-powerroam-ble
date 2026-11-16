"""Diagnostics download: link and decoder counters, no address or serial."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import PowerRoamConfigEntry
from .protocol import KNOWN_OPCODES, PRIVATE_OPCODES


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PowerRoamConfigEntry
) -> dict[str, Any]:
    device = entry.runtime_data
    age = device.last_frame_age
    return {
        "connected": device.connected,
        "link_up": device.link_up,
        "available": device.available,
        "connect_count": device.connect_count,
        "link_durations_s": device.link_durations,
        "frames_received": device.frames_received,
        "crc_failures": device.crc_failures,
        "last_frame_age_s": None if age is None else round(age, 1),
        "frames_by_opcode": {
            f"0x{cmd:02x}": count for cmd, count in sorted(device.opcode_counts.items())
        },
        "unknown_opcodes": sorted(
            f"0x{cmd:02x}" for cmd in device.payloads if cmd not in KNOWN_OPCODES
        ),
        "payloads": {
            f"0x{cmd:02x}": "<private>" if cmd in PRIVATE_OPCODES else payload
            for cmd, payload in sorted(device.payloads.items())
        },
        "data": device.data,
    }
