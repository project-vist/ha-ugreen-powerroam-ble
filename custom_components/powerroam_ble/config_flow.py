"""Config flow: Bluetooth discovery by name, or a pick list of visible units.

Options: the battery capacity, for models the integration doesn't know.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_ADDRESS, CONF_NAME, UnitOfEnergy
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import CAPACITY_WH, CONF_CAPACITY_WH, DOMAIN, FALLBACK_NAME_PREFIX, NAME_PREFIX
from .protocol import model_from_name


class PowerRoamConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PowerRoamOptionsFlow:
        return PowerRoamOptionsFlow()

    def __init__(self) -> None:
        self._address: str | None = None
        self._name: str | None = None
        self._discovered: dict[str, str] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._address = discovery_info.address
        self._name = discovery_info.name or discovery_info.address
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            self._set_confirm_only()
            return self.async_show_form(
                step_id="bluetooth_confirm",
                description_placeholders={"name": self._name or self._address},
            )
        return self._create_entry()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._address = user_input[CONF_ADDRESS]
            self._name = self._discovered.get(self._address, self._address)
            await self.async_set_unique_id(self._address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self._create_entry()

        current = self._async_current_ids(include_ignore=False)
        visible = {
            info.address: info.name
            for info in async_discovered_service_info(self.hass, connectable=True)
            if info.name
            and info.name.lower().startswith(FALLBACK_NAME_PREFIX)
            and info.address not in current
        }
        self._discovered = {
            address: name
            for address, name in visible.items()
            if name.lower().startswith(NAME_PREFIX)
        } or visible
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            address: f"{name} ({address})"
                            for address, name in self._discovered.items()
                        }
                    )
                }
            ),
        )

    def _create_entry(self) -> ConfigFlowResult:
        return self.async_create_entry(
            title=self._name or self._address,
            data={CONF_ADDRESS: self._address, CONF_NAME: self._name},
        )


class PowerRoamOptionsFlow(OptionsFlowWithReload):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        model = model_from_name(self.config_entry.data.get(CONF_NAME))
        capacity = self.config_entry.options.get(CONF_CAPACITY_WH) or CAPACITY_WH.get(model or "")
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_CAPACITY_WH, description={"suggested_value": capacity}
                    ): vol.All(
                        NumberSelector(
                            NumberSelectorConfig(
                                min=100,
                                max=20000,
                                step=1,
                                mode=NumberSelectorMode.BOX,
                                unit_of_measurement=UnitOfEnergy.WATT_HOUR,
                            )
                        ),
                        vol.Coerce(int),
                    )
                }
            ),
            description_placeholders={"model": model or "?"},
        )
