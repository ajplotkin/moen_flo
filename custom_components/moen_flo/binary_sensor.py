"""Binary sensors for Moen Flo (SSO): leak/critical alert + connectivity."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MoenFloConfigEntry
from .entity import MoenFloEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MoenFloConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [MoenFloAlertSensor(coordinator), MoenFloConnectivitySensor(coordinator)]
    )


def _pending(device: dict[str, Any]) -> dict[str, Any]:
    return ((device.get("notifications") or {}).get("pending") or {})


class MoenFloAlertSensor(MoenFloEntity, BinarySensorEntity):
    """On when the Flo has a pending CRITICAL alert (leak/shutoff-worthy).

    Uses the moisture device class so Apple Home surfaces it as a leak warning.
    Warning-level counts are exposed as attributes (not the on/off trigger).
    """

    _attr_name = "Water alert"
    _attr_device_class = BinarySensorDeviceClass.MOISTURE

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "alert")

    @property
    def is_on(self) -> bool:
        return _pending(self._device).get("criticalCount", 0) > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        p = _pending(self._device)
        return {
            "critical_count": p.get("criticalCount", 0),
            "warning_count": p.get("warningCount", 0),
            "info_count": p.get("infoCount", 0),
        }


class MoenFloConnectivitySensor(MoenFloEntity, BinarySensorEntity):
    """Device online/offline."""

    _attr_name = "Connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "connectivity")

    # This sensor must report even when the device is offline.
    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        return bool(self._device.get("isConnected"))
