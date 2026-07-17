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
from .const import LEAK_ALARM_IDS, LEAK_WARNING_ALARM_IDS
from .entity import MoenFloEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MoenFloConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            MoenFloLeakSensor(coordinator),
            MoenFloAlertSensor(coordinator),
            MoenFloConnectivitySensor(coordinator),
        ]
    )


def _pending(device: dict[str, Any]) -> dict[str, Any]:
    return (device.get("notifications") or {}).get("pending") or {}


def _as_int(value: Any, default: int | None = None) -> int | None:
    """Coerce an id/count to int. The API sends ints, but a string would otherwise
    silently break `id in LEAK_ALARM_IDS` — an unobservable permanent false negative."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _pending_alarms(device: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalized pending alarms: [{"id": int|None, "severity": str|None, "count": int}]."""
    raw = _pending(device).get("alarmCount")
    if not isinstance(raw, list):
        return []
    alarms: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        alarms.append(
            {
                "id": _as_int(entry.get("id")),
                "severity": entry.get("severity"),
                # An entry present in the pending list is itself the signal; default to 1
                # rather than 0 so an unexpected shape errs toward alerting.
                "count": _as_int(entry.get("count"), 1) or 0,
            }
        )
    return alarms


class _MoenFloAlarmSensor(MoenFloEntity, BinarySensorEntity):
    """Shared alarm parsing + attributes."""

    @property
    def _alarms(self) -> list[dict[str, Any]]:
        return _pending_alarms(self._device)

    def _severity(self, alarm: dict[str, Any]) -> str | None:
        """Per-entry severity, falling back to the catalog so both is_on and the
        attributes agree on what 'critical' means."""
        catalog = self.coordinator.alarm_catalog.get(alarm.get("id")) or {}
        return alarm.get("severity") or catalog.get("severity")

    def _describe(self, alarm: dict[str, Any]) -> dict[str, Any]:
        catalog = self.coordinator.alarm_catalog.get(alarm.get("id")) or {}
        return {
            "id": alarm.get("id"),
            "name": catalog.get("name"),
            "severity": self._severity(alarm),
            "count": alarm.get("count"),
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Every pending alarm, including info-level ones that trip neither sensor.
        NOTE: attributes don't notify — they're for inspection/automations only."""
        return {"pending_alarms": [self._describe(a) for a in self._alarms]}


class MoenFloLeakSensor(_MoenFloAlarmSensor):
    """On only when Flo reports an actual leak (alarm 100/101)."""

    _attr_name = "Leak"
    _attr_device_class = BinarySensorDeviceClass.MOISTURE

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "leak")

    @property
    def is_on(self) -> bool:
        return any(
            a["id"] in LEAK_ALARM_IDS and a["count"] > 0 for a in self._alarms
        )


class MoenFloAlertSensor(_MoenFloAlarmSensor):
    """On for pending non-leak critical alarms and leak-natured warnings.

    The old Homebridge plugin's generic "triggered" equivalent. Deliberately NOT exposed
    to HomeKit: HA's bridge has no mapping for `problem` and would render it as an
    Occupancy sensor.
    """

    _attr_name = "Water alert"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "alert")

    @property
    def is_on(self) -> bool:
        alarms = self._alarms
        for alarm in alarms:
            if alarm["count"] <= 0:
                continue
            if alarm["id"] in LEAK_ALARM_IDS:
                continue  # the leak sensor owns these
            if self._severity(alarm) == "critical" or alarm["id"] in LEAK_WARNING_ALARM_IDS:
                return True
        # Backstop: if the aggregate says something critical is pending but the detailed
        # list didn't parse into anything, still surface "something is wrong" rather than
        # going silent. (Leaks intentionally get no such fallback — it can't tell a leak
        # from a long shower, which is the bug this whole split exists to fix.)
        if not any(self._severity(a) == "critical" for a in alarms):
            return (_as_int(_pending(self._device).get("criticalCount"), 0) or 0) > 0
        return False


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
