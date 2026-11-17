"""Base entity shared by the sensor, binary_sensor, select and switch platforms."""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription

from .ble import PowerRoamBle, PowerRoamError
from .const import DOMAIN


class PowerRoamEntity(Entity):
    """Pushed by the link; unavailable until its key has a live value.

    Names and icons come from translations/*.json and icons.json by the
    description's translation_key.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, device: PowerRoamBle, description: EntityDescription) -> None:
        self.entity_description = description
        self._device = device
        self._attr_unique_id = f"{device.address}_{description.key}"
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, device.address)},
            identifiers={(DOMAIN, device.address)},
            name=f"UGREEN PowerRoam {device.model}" if device.model else "UGREEN PowerRoam",
            manufacturer="UGREEN",
            model=device.model,
        )

    @property
    def available(self) -> bool:
        return self._device.available and self.entity_description.key in self._device.data

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._device.add_listener(self.async_write_ha_state))


def translated_error(err: PowerRoamError) -> HomeAssistantError:
    """The link's error as a HomeAssistantError in the user's language."""
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=err.key,
        translation_placeholders=err.placeholders,
    )
