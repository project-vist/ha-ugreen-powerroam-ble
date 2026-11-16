"""Setting the unit up: from a Bluetooth discovery, or picked from a list."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_USER
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerroam_ble.const import DOMAIN

from .conftest import ADDRESS, NAME, service_info

pytestmark = pytest.mark.usefixtures("mock_bluetooth")

DISCOVERED = "custom_components.powerroam_ble.config_flow.async_discovered_service_info"
SETUP = "custom_components.powerroam_ble.async_setup_entry"


async def test_bluetooth_discovery_creates_the_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"

    with patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == NAME
    assert result["data"] == {CONF_ADDRESS: ADDRESS, CONF_NAME: NAME}
    assert result["result"].unique_id == ADDRESS


async def test_bluetooth_discovery_of_a_configured_unit_aborts(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info()
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_step_lists_only_power_stations(hass: HomeAssistant) -> None:
    other = service_info("UGREEN HiTune X6", "11:22:33:44:55:66")
    with patch(DISCOVERED, return_value=[service_info(), other]):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    choices = result["data_schema"].schema[CONF_ADDRESS].container
    assert list(choices) == [ADDRESS]

    with patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ADDRESS}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_ADDRESS: ADDRESS, CONF_NAME: NAME}


async def test_user_step_without_units_aborts(hass: HomeAssistant) -> None:
    with patch(DISCOVERED, return_value=[service_info("UGREEN HiTune X6")]):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"
