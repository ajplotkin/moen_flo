"""Sensors for Moen Flo (SSO): flow, pressure, temperature, wifi, daily usage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MoenFloConfigEntry
from .entity import MoenFloEntity


@dataclass(frozen=True, kw_only=True)
class MoenFloSensorDescription(SensorEntityDescription):
    """A sensor described by how to pull its value from coordinator data."""

    value_fn: Callable[[dict[str, Any], dict[str, Any]], Any]


from .telemetry import latest_metric as _latest_metric  # noqa: E402
from .telemetry import water_temp_f as _water_temp_f  # noqa: E402


SENSORS: tuple[MoenFloSensorDescription, ...] = (
    MoenFloSensorDescription(
        key="flow",
        name="Water flow",
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        native_unit_of_measurement=UnitOfVolumeFlowRate.GALLONS_PER_MINUTE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        # Hourly average from /water/metrics, NOT telemetry.current.gpm. The instantaneous
        # field only updates while someone has the Moen app open -- it sat frozen at one
        # value for ten days while water was used nightly. This is an average, but it is
        # real and it keeps updating unattended. See telemetry.latest_metric.
        value_fn=lambda dev, data: _latest_metric(data.get("metrics"), "averageGpm"),
    ),
    MoenFloSensorDescription(
        key="pressure",
        name="Water pressure",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.PSI,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        # Hourly average -- same reasoning as Water flow above.
        value_fn=lambda dev, data: _latest_metric(data.get("metrics"), "averagePsi"),
    ),
    MoenFloSensorDescription(
        key="temperature",
        name="Water temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # Not a raw passthrough: valves with no temperature sensor report a constant
        # placeholder (225 F on the unit this was written against) rather than omitting
        # the field. See telemetry.water_temp_f -- readings at or above boiling are
        # returned as None so the entity goes unavailable instead of publishing a fake
        # number. The old comment here said it "reads oddly at zero-flow"; that was
        # wrong -- it read 225 while flow was 2.16 gal/min.
        value_fn=lambda dev, data: _water_temp_f(dev),
    ),
    MoenFloSensorDescription(
        key="wifi",
        name="Wi-Fi signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda dev, data: (dev.get("connectivity") or {}).get("rssi"),
    ),
    MoenFloSensorDescription(
        key="consumption_today",
        name="Water used today",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=lambda dev, data: data.get("consumption_today"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MoenFloConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(MoenFloSensor(coordinator, desc) for desc in SENSORS)


class MoenFloSensor(MoenFloEntity, SensorEntity):
    """A single Flo telemetry/usage sensor."""

    entity_description: MoenFloSensorDescription

    def __init__(self, coordinator, description: MoenFloSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self._device, self.coordinator.data or {})
