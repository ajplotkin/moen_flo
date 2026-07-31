"""Binary sensors for Moen Flo (SSO): leak, generic alert, and connectivity.

Flo raises many *critical* alarms that are not leaks ("Extended Water Use", "Fast Water
Flow", "Unusual Activity", "Water System Shutoff", ...). Mapping all of them to a
moisture sensor makes HomeKit announce "Leak detected" for a long shower, which trains
you to ignore the one alert that matters. So:

  * leak   (moisture) -> only alarms that actually mean water is leaking (100/101)
  * alert  (problem)  -> other pending critical alarms, plus leak-natured warnings
                         (e.g. "Small Drip Detected"). Equivalent to the old Homebridge
                         plugin's generic "triggered".

Both sensors err toward firing when a payload has an unexpected shape: a missed leak is
far worse than a spurious one.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MoenFloConfigEntry
from .alarms import as_int, describe, pending, pending_alarms, severity_of
from .const import LEAK_ALARM_IDS
from .entity import MoenFloEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MoenFloConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            MoenFloShutoffSensor(coordinator),
            MoenFloLeakSensor(coordinator),
            MoenFloAlertSensor(coordinator),
            MoenFloConnectivitySensor(coordinator),
        ]
    )


class _MoenFloAlarmSensor(MoenFloEntity, BinarySensorEntity):
    """Shared alarm parsing + attributes."""

    @property
    def _alarms(self) -> list[dict[str, Any]]:
        return pending_alarms(self._device)

    def _severity(self, alarm: dict[str, Any]) -> str | None:
        return severity_of(alarm, self.coordinator.alarm_catalog)

    def _describe(self, alarm: dict[str, Any]) -> dict[str, Any]:
        return describe(alarm, self.coordinator.alarm_catalog)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Every pending alarm, including info-level ones that trip neither sensor.
        NOTE: attributes don't notify — they're for inspection/automations only."""
        return {"pending_alarms": [self._describe(a) for a in self._alarms]}


class MoenFloShutoffSensor(_MoenFloAlarmSensor):
    """On when Flo has ANY pending critical alarm — leak, shutoff, unusual activity.

    Uses device_class OPENING so HomeKit renders it as a contact sensor. The notification
    reads "Water Shutoff: Open" (= a shutoff condition is active) rather than the
    misleading "Leak Detected" a moisture sensor would produce for non-leak shutoffs.
    """

    _attr_name = "Water Shutoff"
    _attr_device_class = BinarySensorDeviceClass.OPENING

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "leak")

    @property
    def is_on(self) -> bool:
        if any(self._severity(a) == "critical" and a["count"] > 0 for a in self._alarms):
            return True
        return (as_int(pending(self._device).get("criticalCount"), 0) or 0) > 0


class MoenFloLeakSensor(_MoenFloAlarmSensor):
    """On only for actual leak alarms (100/101). HomeKit says "Leak Detected" — accurate."""

    _attr_name = "Leak"
    _attr_device_class = BinarySensorDeviceClass.MOISTURE

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "actual_leak")

    @property
    def is_on(self) -> bool:
        return any(
            a["id"] in LEAK_ALARM_IDS and a["count"] > 0 for a in self._alarms
        )


class MoenFloAlertSensor(_MoenFloAlarmSensor):
    """On for any pending warning-level alarm (e.g. Small Drip, Low Water Pressure).

    HA-only (device_class problem → HomeKit can't render it usefully). Critical alarms
    are handled by the moisture sensor above, which reaches HomeKit.
    """

    _attr_name = "Warning"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "alert")

    @property
    def is_on(self) -> bool:
        return any(
            self._severity(a) == "warning" and a["count"] > 0 for a in self._alarms
        )


class MoenFloConnectivitySensor(MoenFloEntity, BinarySensorEntity):
    """Device online/offline."""

    _attr_name = "Connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "connectivity")

    # Must report even when the device itself is offline.
    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        return bool(self._device.get("isConnected"))
