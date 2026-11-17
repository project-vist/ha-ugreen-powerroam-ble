"""Bluetooth LE link to a UGREEN PowerRoam.

Holds one persistent connection. Once notifications are on, the unit pushes
its whole status about every 0.6 s unasked. Writes: the 0x16 switch block
(outputs and a few settings) and the one-byte setting frames (light,
operating mode, DC current, alert level), each confirmed by the unit's next
report. Connection handling follows
tanka8/ugreen-powerroam (MIT, see LICENSE) plus its unmerged PR #11 fix.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from typing import Any

from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback

from . import protocol
from .const import (
    BACKOFF_MAX,
    BACKOFF_START,
    CAPACITY_WH,
    FRAME_STALE_AFTER,
    HOLD_AFTER_LAST_FRAME,
    NOTIFY_UUID,
    STATE_DEBOUNCE,
    SWITCH_CONFIRM_WAIT,
    SWITCH_STATE_WAIT,
    WRITE_UUID,
)

_LOGGER = logging.getLogger(__name__)

# Changed payloads per opcode, for mapping unknown bytes or checking units:
# logger → logs → custom_components.powerroam_ble.frames: debug
_FRAME_LOGGER = logging.getLogger(f"{__package__}.frames")

# More than a couple of frames buffered means the stream lost sync.
MAX_BUFFER = 1024


class PowerRoamError(Exception):
    """A write that didn't happen or wasn't confirmed by the unit.

    Carries a translation key (translations/*.json, "exceptions") and its
    placeholders, so the entity can raise a translated HomeAssistantError.
    """

    def __init__(self, key: str, **placeholders: str) -> None:
        super().__init__(key, placeholders)
        self.key = key
        self.placeholders = placeholders


class PowerRoamBle:
    """Owns the connection, the last decoded values and the entity listeners."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        name: str | None,
        capacity_wh: int | None = None,
    ) -> None:
        self._hass = hass
        self.address = address
        self.name = name or address
        self.model = protocol.model_from_name(self.name)
        self.capacity_wh = capacity_wh or CAPACITY_WH.get(self.model or "")
        self.data: dict[str, Any] = {}
        self._listeners: list[Callable[[], None]] = []
        self._client: BleakClientWithServiceCache | None = None
        self._buffer = bytearray()
        self._task: asyncio.Task | None = None
        self._stopped = False
        self._disconnected = asyncio.Event()
        self._seen = asyncio.Event()
        self._cancel_adverts: CALLBACK_TYPE | None = None
        self._notify_handle: asyncio.TimerHandle | None = None
        self._expire_handle: asyncio.TimerHandle | None = None
        self._last_frame_at: float | None = None
        self._link_reported = False
        self._write_lock = asyncio.Lock()
        # Payloads of the opcode a write is waiting on, raw.
        self._watch: dict[int, asyncio.Queue[bytes]] = {}

        # Counters for the diagnostics download, kept across reconnects so a
        # flaky link shows up as a climbing connect_count. Link durations tell
        # a radio problem (random) from a protocol timeout (always the same).
        self.connect_count = 0
        self.link_durations: list[int] = []
        self.frames_received = 0
        self.crc_failures = 0
        self.opcode_counts: dict[int, int] = {}
        # Last payload of every opcode, for mapping the frames not decoded yet.
        self.payloads: dict[int, str] = {}

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    @property
    def last_frame_age(self) -> float | None:
        if self._last_frame_at is None:
            return None
        return time.monotonic() - self._last_frame_at

    @property
    def available(self) -> bool:
        """Data recent enough to show, even across a short link drop."""
        age = self.last_frame_age
        return age is not None and age < HOLD_AFTER_LAST_FRAME

    @property
    def link_up(self) -> bool:
        """Connected and frames flowing right now."""
        age = self.last_frame_age
        return self.connected and age is not None and age < FRAME_STALE_AFTER

    @property
    def rssi(self) -> int | None:
        """RSSI of the last advertisement; the unit stops advertising while connected."""
        info = bluetooth.async_last_service_info(self._hass, self.address, connectable=True)
        return None if info is None else info.rssi

    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)

        def _remove() -> None:
            if cb in self._listeners:
                self._listeners.remove(cb)

        return _remove

    @callback
    def _notify_now(self) -> None:
        if self._notify_handle is not None:
            self._notify_handle.cancel()
            self._notify_handle = None
        for cb in list(self._listeners):
            cb()

    @callback
    def _schedule_notify(self) -> None:
        if self._notify_handle is None:
            self._notify_handle = self._hass.loop.call_later(STATE_DEBOUNCE, self._notify_now)

    async def start(self) -> None:
        self._stopped = False
        self._cancel_adverts = bluetooth.async_register_callback(
            self._hass,
            self._on_advertisement,
            bluetooth.BluetoothCallbackMatcher(address=self.address, connectable=True),
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
        self._task = self._hass.async_create_background_task(
            self._run(), f"powerroam_ble {self.address}"
        )

    async def stop(self) -> None:
        self._stopped = True
        if self._cancel_adverts is not None:
            self._cancel_adverts()
            self._cancel_adverts = None
        for handle in (self._notify_handle, self._expire_handle):
            if handle is not None:
                handle.cancel()
        self._notify_handle = self._expire_handle = None
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._disconnect()

    @callback
    def _on_advertisement(
        self, _info: bluetooth.BluetoothServiceInfoBleak, _change: bluetooth.BluetoothChange
    ) -> None:
        self._seen.set()

    async def _run(self) -> None:
        backoff = BACKOFF_START
        while not self._stopped:
            self._seen.clear()
            try:
                await self._connect_once()
                backoff = BACKOFF_START
                if not self._stopped:
                    await asyncio.sleep(1)
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as err:  # the reconnect loop must survive anything
                _LOGGER.debug("PowerRoam %s: connection failed: %s", self.name, err)
            if self._stopped:
                return
            await asyncio.sleep(BACKOFF_START)
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(backoff - BACKOFF_START):
                    await self._seen.wait()
            backoff = min(backoff * 2, BACKOFF_MAX)

    def _ble_device(self):
        return bluetooth.async_ble_device_from_address(self._hass, self.address, connectable=True)

    async def _connect_once(self) -> None:
        ble_device = self._ble_device()
        if ble_device is None:
            raise BleakError("not visible to any adapter")

        self._disconnected.clear()
        client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            self.name,
            disconnected_callback=self._on_disconnect,
            ble_device_callback=lambda: self._ble_device() or ble_device,
        )
        # No await between establish_connection() returning and this line, so
        # _on_disconnect can't mistake the live client for a stale one.
        self._client = client
        self._buffer.clear()
        self._link_reported = False
        connected_at = time.monotonic()
        try:
            await client.start_notify(NOTIFY_UUID, self._on_notify)
            self.connect_count += 1
            _LOGGER.debug("PowerRoam %s: connected", self.name)
            while not self._disconnected.is_set():
                with contextlib.suppress(TimeoutError):
                    async with asyncio.timeout(FRAME_STALE_AFTER / 3):
                        await self._disconnected.wait()
                since = max(self._last_frame_at or 0.0, connected_at)
                if time.monotonic() - since > FRAME_STALE_AFTER:
                    _LOGGER.debug("PowerRoam %s: no frames, reconnecting", self.name)
                    break
        finally:
            self.link_durations = [
                *self.link_durations[-19:],
                round(time.monotonic() - connected_at),
            ]
            await self._disconnect()

    def _on_disconnect(self, client: BleakClientWithServiceCache) -> None:
        # establish_connection() calls this for every failed attempt before
        # the one that works (tanka8 PR #11); only the held client counts.
        if client is not self._client:
            return
        self._hass.loop.call_soon_threadsafe(self._disconnected.set)

    async def _disconnect(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        # "Connected" goes off now; the values go unavailable only once the
        # hold runs out, and nothing else would write them then.
        self._notify_now()
        age = self.last_frame_age
        if age is not None and age < HOLD_AFTER_LAST_FRAME and not self._stopped:
            if self._expire_handle is not None:
                self._expire_handle.cancel()
            self._expire_handle = self._hass.loop.call_later(
                HOLD_AFTER_LAST_FRAME - age + 1, self._notify_now
            )
        with contextlib.suppress(BleakError, asyncio.CancelledError, OSError):
            await client.disconnect()

    @contextlib.asynccontextmanager
    async def _writing(self, opcode: int):
        """One write at a time, on a live link, watching the opcode it changes."""
        async with self._write_lock:
            client = self._client
            if client is None or not self.link_up:
                raise PowerRoamError("no_link")
            queue: asyncio.Queue[bytes] = asyncio.Queue()
            self._watch[opcode] = queue
            try:
                yield client, queue
            finally:
                del self._watch[opcode]
        self._notify_now()

    async def _write(self, client: BleakClientWithServiceCache, frame: bytes) -> None:
        try:
            await client.write_gatt_char(WRITE_UUID, frame, response=True)
        except BleakError as err:
            raise PowerRoamError("write_failed", error=str(err)) from err

    @staticmethod
    async def _next(
        queue: asyncio.Queue[bytes],
        wait: float,
        decode: Callable[[bytes], Any],
        error: str,
        setting: str,
    ) -> Any:
        """The next reported payload that decodes, or PowerRoamError(error) on timeout."""
        try:
            async with asyncio.timeout(max(wait, 0)):
                while (value := decode(await queue.get())) is None:
                    pass
                return value
        except TimeoutError:
            raise PowerRoamError(error, setting=setting) from None

    async def set_switch(self, field: str, on: bool, label: str) -> None:
        """Change one field of the 0x16 block and wait until the unit reports it.

        0x16 rewrites every setting in the block, so the write is built on the
        next block the unit reports, never on the held one, and the echo is
        checked for anything else that moved.
        """
        if field not in protocol.WRITABLE_SWITCH_FIELDS:
            raise ValueError(field)
        decode = protocol.decode_switch_state
        async with self._writing(protocol.OP_SWITCHES) as (client, queue):
            before = await self._next(queue, SWITCH_STATE_WAIT, decode, "no_report", label)
            if before[field] == on:
                return
            _LOGGER.info("PowerRoam %s: %s %s", self.name, label, "on" if on else "off")
            await self._write(client, protocol.encode_switch_state({**before, field: on}))
            # Blocks already in flight still show the old state; skip those.
            deadline = time.monotonic() + SWITCH_CONFIRM_WAIT
            while True:
                state = await self._next(
                    queue, deadline - time.monotonic(), decode, "not_confirmed", label
                )
                moved = [
                    n
                    for n in protocol.SWITCH_RECV_FIELDS
                    if n != field
                    and n not in protocol.SWITCH_STATUS_FIELDS
                    and state[n] != before[n]
                ]
                if moved:
                    _LOGGER.error(
                        "PowerRoam %s: after the %s write these settings changed too: %s",
                        self.name,
                        label,
                        ", ".join(moved),
                    )
                    raise PowerRoamError("other_settings_changed", settings=", ".join(moved))
                if state[field] == on:
                    return

    async def set_setting(self, opcode: int, option: str, label: str) -> None:
        """Set a one-byte setting (light, mode, …) and wait until the unit reports it."""
        frame = protocol.encode_setting(opcode, option)

        def decode(data: bytes) -> str | None:
            return protocol.decode_setting(opcode, data)

        async with self._writing(opcode) as (client, queue):
            before = await self._next(queue, SWITCH_STATE_WAIT, decode, "no_report", label)
            if before == option:
                return
            _LOGGER.info("PowerRoam %s: %s %s", self.name, label, option)
            await self._write(client, frame)
            deadline = time.monotonic() + SWITCH_CONFIRM_WAIT
            while (
                await self._next(queue, deadline - time.monotonic(), decode, "not_confirmed", label)
                != option
            ):
                pass

    def _on_notify(self, _char: Any, payload: bytearray) -> None:
        self._buffer.extend(payload)
        frames, consumed = protocol.decode_stream(bytes(self._buffer))
        del self._buffer[:consumed]
        if len(self._buffer) > MAX_BUFFER:
            self._buffer.clear()

        changed = False
        got_frame = False
        for frame in frames:
            self.frames_received += 1
            if not frame.crc_ok:
                self.crc_failures += 1
                continue
            self._last_frame_at = time.monotonic()
            got_frame = True
            self.opcode_counts[frame.cmd] = self.opcode_counts.get(frame.cmd, 0) + 1
            hexed = frame.data.hex()
            if self.payloads.get(frame.cmd) != hexed:
                self.payloads[frame.cmd] = hexed
                # Debug logs get pasted into public issues: no serial or MAC.
                _FRAME_LOGGER.debug(
                    "0x%02x %s",
                    frame.cmd,
                    "<private>" if frame.cmd in protocol.PRIVATE_OPCODES else hexed,
                )
            for key, value in protocol.telemetry(frame).items():
                # "in" first: a None (no estimate) must still land as a value.
                if key not in self.data or self.data[key] != value:
                    self.data[key] = value
                    changed = True
            if (
                frame.prefix == protocol.REPLY_PREFIX
                and (queue := self._watch.get(frame.cmd)) is not None
            ):
                queue.put_nowait(frame.data)

        if changed:
            for key, value in protocol.derived(self.data, self.capacity_wh).items():
                self.data[key] = value

        # The first frame of a link is written at once, unchanged values
        # included, so "Connected" and anything that was unavailable catch up.
        if got_frame and not self._link_reported:
            self._link_reported = True
            self._notify_now()
        elif changed:
            self._schedule_notify()
