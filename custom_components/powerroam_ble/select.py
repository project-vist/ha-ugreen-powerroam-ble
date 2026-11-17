"""The UGREEN PowerRoam's one-byte settings as lists: light, mode, DC current, alert level."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PowerRoamConfigEntry
from .ble import PowerRoamError
from .entity import PowerRoamEntity, translated_error
from .protocol import BYTE_SETTINGS, OP_DC_CHARGE, OP_LIGHT, OP_LOW_ALERT, OP_WORK_MODE

# Writes are serialised by the link's own lock.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class PowerRoamSelectDescription(SelectEntityDescription):
    opcode: int


def _select(
    opcode: int, category: EntityCategory | None = EntityCategory.CONFIG
) -> PowerRoamSelectDescription:
    key, options = BYTE_SETTINGS[opcode]
    return PowerRoamSelectDescription(
        key=key,
        translation_key=key,
        options=list(options.values()),
        opcode=opcode,
        entity_category=category,
    )


SELECTS: tuple[PowerRoamSelectDescription, ...] = (
    _select(OP_LIGHT, category=None),
    _select(OP_WORK_MODE),
    _select(OP_DC_CHARGE),
    _select(OP_LOW_ALERT),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerRoamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    device = entry.runtime_data
    async_add_entities(PowerRoamSelect(device, description) for description in SELECTS)


class PowerRoamSelect(PowerRoamEntity, SelectEntity):
    entity_description: PowerRoamSelectDescription

    @property
    def current_option(self) -> str | None:
        return self._device.data.get(self.entity_description.key)

    async def async_select_option(self, option: str) -> None:
        try:
            await self._device.set_setting(self.entity_description.opcode, option, str(self.name))
        except PowerRoamError as err:
            raise translated_error(err) from err
