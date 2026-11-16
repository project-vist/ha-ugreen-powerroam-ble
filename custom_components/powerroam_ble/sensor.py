"""Sensors for the UGREEN PowerRoam integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PowerRoamConfigEntry
from .entity import PowerRoamEntity

# Pushed by the link; only the RSSI sensor polls, and it reads a cache.
PARALLEL_UPDATES = 0
SCAN_INTERVAL = timedelta(seconds=60)

DIAGNOSTIC = EntityCategory.DIAGNOSTIC


def _sensor(key: str, **kwargs: Any) -> SensorEntityDescription:
    return SensorEntityDescription(key=key, translation_key=key, **kwargs)


def _power(key: str) -> SensorEntityDescription:
    return _sensor(
        key,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    )


def _temperature(key: str) -> SensorEntityDescription:
    return _sensor(
        key,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=DIAGNOSTIC,
    )


def _duration(key: str) -> SensorEntityDescription:
    # Minutes on the wire; None (unknown) when the unit has no estimate.
    return _sensor(
        key,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
    )


def _millivolts(key: str, **kwargs: Any) -> SensorEntityDescription:
    return SensorEntityDescription(
        key=key,
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=DIAGNOSTIC,
        **kwargs,
    )


SENSORS: tuple[SensorEntityDescription, ...] = (
    _sensor(
        "battery",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    _power("input_power"),
    _power("output_power"),
    _power("ac_output_power"),
    _power("usb_output_power"),
    _power("dc_output_power"),
    _duration("charge_time"),
    _duration("discharge_time"),
    _sensor(
        "battery_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=1,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # Worked out by protocol.derived(); need the model's capacity (GS1200 only).
    _sensor(
        "mode",
        device_class=SensorDeviceClass.ENUM,
        options=["charging", "bypass", "discharging", "idle"],
    ),
    _power("battery_power"),
    _sensor(
        "energy_remaining",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # Diagnostics.
    _sensor(
        "battery_health",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=DIAGNOSTIC,
    ),
    # One byte on the wire, so no state class: a wrap at 256 would read as a reset.
    _sensor("battery_cycles", entity_category=DIAGNOSTIC),
    _sensor(
        "capacity_remaining",
        native_unit_of_measurement="Ah",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=DIAGNOSTIC,
    ),
    _temperature("battery_temp_1"),
    _temperature("battery_temp_2"),
    _temperature("inverter_temp_1"),
    _temperature("inverter_temp_2"),
    # From the 0x16 block; never written (60 Hz can harm devices).
    _sensor(
        "ac_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        entity_category=DIAGNOSTIC,
    ),
    _millivolts("cell_spread", translation_key="cell_spread"),
    *(
        _millivolts(
            f"cell_voltage_{n}",
            translation_key="cell_voltage",
            translation_placeholders={"cell": str(n)},
            entity_registry_enabled_default=False,
        )
        for n in range(1, 8)
    ),
    _sensor("fault_raw", entity_category=DIAGNOSTIC, entity_registry_enabled_default=False),
)

RSSI = _sensor(
    "rssi",
    native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    device_class=SensorDeviceClass.SIGNAL_STRENGTH,
    state_class=SensorStateClass.MEASUREMENT,
    entity_category=DIAGNOSTIC,
    entity_registry_enabled_default=False,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerRoamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    device = entry.runtime_data
    async_add_entities(
        [
            *(PowerRoamSensor(device, description) for description in SENSORS),
            PowerRoamRssiSensor(device, RSSI),
        ]
    )


class PowerRoamSensor(PowerRoamEntity, SensorEntity):
    @property
    def native_value(self) -> int | float | str | None:
        return self._device.data.get(self.entity_description.key)


class PowerRoamRssiSensor(PowerRoamEntity, SensorEntity):
    """From the last advertisement, so it lags while the link is up."""

    _attr_should_poll = True

    @property
    def native_value(self) -> int | None:
        return self._device.rssi

    @property
    def available(self) -> bool:
        return self._device.rssi is not None
