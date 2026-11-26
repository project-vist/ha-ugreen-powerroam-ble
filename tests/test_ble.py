"""Writes: build on a fresh state, change one thing, wait for the unit to confirm."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from bleak.exc import BleakError
from homeassistant.core import HomeAssistant

from custom_components.powerroam_ble import ble, protocol
from custom_components.powerroam_ble.ble import PowerRoamBle, PowerRoamError

from .conftest import ADDRESS, NAME, reply
from .fake_unit import FakeUnit

SETTING_KEYS = (
    "ac_output",
    "dc_output",
    "usb_output",
    "quiet_mode",
    "u_turbo",
    "battery_care",
    "child_lock",
    "key_beep",
    "standby",
    "ac_frequency",
    "low_battery_warning",
)


@pytest.fixture(autouse=True)
def short_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ble, "SWITCH_STATE_WAIT", 1.0)
    monkeypatch.setattr(ble, "SWITCH_CONFIRM_WAIT", 1.0)


@pytest.fixture
def device(hass: HomeAssistant) -> PowerRoamBle:
    return PowerRoamBle(hass, ADDRESS, NAME)


@pytest.mark.parametrize(
    ("field", "key"),
    [
        ("ac", "ac_output"),
        ("dc", "dc_output"),
        ("usb", "usb_output"),
        ("low_noise", "quiet_mode"),
        ("ac_uturbo", "u_turbo"),
        ("battery_health", "battery_care"),
        ("locking", "child_lock"),
        ("key_voice", "key_beep"),  # inverted on the wire
    ],
)
async def test_switch_changes_only_its_field(device: PowerRoamBle, field: str, key: str) -> None:
    async with FakeUnit(device) as unit:
        before = {k: device.data[k] for k in SETTING_KEYS}
        await device.set_switch(field, not before[key], key)
        unit.push()
        after = {k: device.data[k] for k in SETTING_KEYS}
        assert after == {**before, key: not before[key]}
        assert len(unit.writes) == 1


async def test_same_value_sends_nothing(device: PowerRoamBle) -> None:
    async with FakeUnit(device) as unit:
        await device.set_switch("locking", device.data["child_lock"], "lock")
        assert unit.writes == []


@pytest.mark.parametrize(
    ("opcode", "options"),
    [
        (protocol.OP_LIGHT, ("low", "high", "strobe", "sos", "off")),
        (protocol.OP_WORK_MODE, ("always_on", "eco", "standard")),
        (protocol.OP_DC_CHARGE, ("4", "6", "8")),
        (protocol.OP_LOW_ALERT, ("20", "5", "10")),
    ],
)
async def test_settings_cycle(device: PowerRoamBle, opcode: int, options: tuple[str, ...]) -> None:
    key = protocol.BYTE_SETTINGS[opcode][0]
    async with FakeUnit(device) as unit:
        for option in options:
            await device.set_setting(opcode, option, key)
            unit.push()
            assert device.data[key] == option
        assert [cmd for cmd, _ in unit.writes] == [opcode] * len(options)


REFUSED = ["standby", "ac_frequency_hz", "warning_voice", "low_battery_warning"]


@pytest.mark.parametrize("field", REFUSED)
async def test_refused_fields_send_nothing(device: PowerRoamBle, field: str) -> None:
    async with FakeUnit(device) as unit:
        with pytest.raises(ValueError):
            await device.set_switch(field, True, field)
        assert unit.writes == []


async def test_unconfirmed_write_fails_without_retry(device: PowerRoamBle) -> None:
    async with FakeUnit(device, "silent") as unit:
        with pytest.raises(PowerRoamError) as err:
            await device.set_switch("locking", True, "Child safety lock")
        assert err.value.key == "not_confirmed"
        assert err.value.placeholders == {"setting": "Child safety lock"}
        assert len(unit.writes) == 1


async def test_unconfirmed_setting_fails(device: PowerRoamBle) -> None:
    async with FakeUnit(device, "silent"):
        with pytest.raises(PowerRoamError) as err:
            await device.set_setting(protocol.OP_WORK_MODE, "always_on", "Operating mode")
        assert err.value.key == "not_confirmed"


async def test_another_setting_moving_fails(device: PowerRoamBle) -> None:
    async with FakeUnit(device, "moves"):
        with pytest.raises(PowerRoamError) as err:
            await device.set_switch("ac_uturbo", False, "U-Turbo")
        assert err.value.key == "other_settings_changed"
        assert err.value.placeholders == {"settings": "locking"}


async def test_low_battery_warning_flipping_mid_write_is_not_an_error(device: PowerRoamBle) -> None:
    async with FakeUnit(device) as unit:
        original = unit.write_gatt_char

        async def write_and_warn(uuid: str, frame: bytes, response: bool) -> None:
            await original(uuid, frame, response)
            unit.block[protocol.SWITCH_RECV_FIELDS.index("low_battery_warning")] = 1

        unit.write_gatt_char = write_and_warn  # type: ignore[method-assign]
        await device.set_switch("usb", False, "USB output")
        unit.push()
        assert device.data["usb_output"] is False


async def test_no_link_fails_at_once(device: PowerRoamBle) -> None:
    with pytest.raises(PowerRoamError) as err:
        await device.set_switch("usb", False, "USB output")
    assert err.value.key == "no_link"


async def test_private_frames_stay_out_of_debug_logs(
    device: PowerRoamBle, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("DEBUG", logger="custom_components.powerroam_ble.frames")
    serial = b"G12XX0000000000" * 2
    device._on_notify(None, bytearray(reply(0x05, serial) + reply(0x13, b"\x00")))
    assert serial.hex() not in caplog.text
    assert "0x05 <private>" in caplog.text
    assert "0x13 00" in caplog.text
    await device.stop()


@pytest.mark.parametrize(
    ("name", "option", "capacity"),
    [
        ("ugreen gs2200", None, 2048),
        (NAME, None, 1024),
        ("ugreen gs9", None, None),
        ("ugreen gs9", 1500, 1500),
        (NAME, 1100, 1100),
    ],
)
def test_capacity_from_the_model_or_the_option(
    hass: HomeAssistant, name: str, option: int | None, capacity: int | None
) -> None:
    assert PowerRoamBle(hass, ADDRESS, name, option).capacity_wh == capacity


async def test_failed_connects_are_kept_for_diagnostics(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    device = PowerRoamBle(hass, ADDRESS, NAME)
    with (
        patch.object(device, "_ble_device", return_value=object()),
        patch.object(ble, "establish_connection", side_effect=BleakError(f"{ADDRESS} gone")),
        patch.object(ble, "BACKOFF_START", 0),
        patch.object(ble, "BACKOFF_MAX", 0),
    ):
        task = hass.async_create_background_task(device._run(), "test")
        for _ in range(50):
            await asyncio.sleep(0)
            if device.connect_attempts >= 3:
                break
        device._stopped = True
        task.cancel()
    assert device.connect_attempts >= 3
    assert device.last_error == "BleakError: <address> gone"
    assert "connection failed" in caplog.text
