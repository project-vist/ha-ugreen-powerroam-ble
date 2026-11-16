"""A stand-in for a PowerRoam on the other end of the GATT link."""

from __future__ import annotations

import asyncio
import contextlib

from custom_components.powerroam_ble import protocol
from custom_components.powerroam_ble.ble import PowerRoamBle

from .conftest import reply
from .frames import IDLE


class FakeUnit:
    """Pushes its 0x16 block and setting frames every 50 ms, applies writes like the unit.

    Plays the BleakClient role: write_gatt_char, is_connected, disconnect.
    behaviour: "ok", "silent" (never applies a write) or "moves" (a write also
    flips the child lock, as a buggy layout would).
    """

    def __init__(self, device: PowerRoamBle, behaviour: str = "ok") -> None:
        self.device = device
        self.behaviour = behaviour
        self.block = bytearray.fromhex(IDLE[0x16])
        self.settings = {op: bytes.fromhex(IDLE[op])[0] for op in protocol.BYTE_SETTINGS}
        self.writes: list[tuple[int, bytes]] = []
        self.is_connected = True
        self._task: asyncio.Task | None = None

    async def write_gatt_char(self, _uuid: str, frame: bytes, response: bool) -> None:
        frames, _ = protocol.decode_stream(bytes(frame))
        assert len(frames) == 1 and frames[0].crc_ok and frames[0].prefix == protocol.CMD_PREFIX
        cmd, data = frames[0].cmd, frames[0].data
        self.writes.append((cmd, data))
        if self.behaviour == "silent":
            return
        await asyncio.sleep(0.12)  # frames already in flight still show the old state
        if cmd == protocol.OP_SWITCHES:
            assert len(data) == 11
            # Re-insert the reported-only low_battery_warning at index 1.
            self.block = bytearray(data[:1] + self.block[1:2] + data[1:])
            if self.behaviour == "moves":
                self.block[protocol.SWITCH_RECV_FIELDS.index("locking")] ^= 1
        else:
            assert len(data) == 1
            self.settings[cmd] = data[0]

    async def disconnect(self) -> None:
        self.is_connected = False

    def push(self) -> None:
        payload = reply(protocol.OP_SWITCHES, bytes(self.block)) + b"".join(
            reply(op, bytes([value])) for op, value in self.settings.items()
        )
        self.device._on_notify(None, bytearray(payload))

    async def _run(self) -> None:
        while True:
            self.push()
            await asyncio.sleep(0.05)

    async def __aenter__(self) -> FakeUnit:
        self.device._client = self  # type: ignore[assignment]
        self._task = asyncio.create_task(self._run())
        await asyncio.sleep(0.12)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        assert self._task is not None
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        await self.device.stop()
