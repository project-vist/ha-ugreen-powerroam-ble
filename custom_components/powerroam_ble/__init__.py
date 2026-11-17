"""UGREEN PowerRoam over Bluetooth LE.

Protocol and connection handling derived from tanka8/ugreen-powerroam (MIT,
see LICENSE). No cloud and no account. Writes: the outputs and a few settings
in the 0x16 block, and the one-byte setting frames (light, operating mode,
DC charging current, low battery alert level).
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME, Platform
from homeassistant.core import HomeAssistant

from .ble import PowerRoamBle
from .const import CONF_CAPACITY_WH

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SELECT, Platform.SENSOR, Platform.SWITCH]

type PowerRoamConfigEntry = ConfigEntry[PowerRoamBle]


async def async_setup_entry(hass: HomeAssistant, entry: PowerRoamConfigEntry) -> bool:
    # No ConfigEntryNotReady when the unit isn't visible: the link waits for
    # its next advertisement, and the entities stay unavailable until then.
    device = PowerRoamBle(
        hass,
        entry.data[CONF_ADDRESS],
        entry.data.get(CONF_NAME),
        entry.options.get(CONF_CAPACITY_WH),
    )
    entry.runtime_data = device
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await device.start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PowerRoamConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.stop()
    return unload_ok
