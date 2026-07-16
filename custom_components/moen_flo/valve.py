"""Valve platform for Moen Flo (SSO)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.valve import (
    ValveDeviceClass,
    ValveEntity,
    ValveEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MoenFloConfigEntry
from .const import VALVE_CLOSED, VALVE_OPEN
from .entity import MoenFloEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MoenFloConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([MoenFloValve(entry.runtime_data)])


class MoenFloValve(MoenFloEntity, ValveEntity):
    """The whole-home shutoff valve."""

    _attr_device_class = ValveDeviceClass.WATER
    _attr_supported_features = ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE
    _attr_reports_position = False
    _attr_name = None  # use the device name for the primary valve

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "valve")

    @property
    def is_closed(self) -> bool | None:
        last = (self._device.get("valve") or {}).get("lastKnown")
        if last is None:
            return None
        return last == VALVE_CLOSED

    async def async_open_valve(self, **kwargs: Any) -> None:
        await self.coordinator.api.async_set_valve(self.coordinator.device_id, VALVE_OPEN)
        await self.coordinator.async_request_refresh()

    async def async_close_valve(self, **kwargs: Any) -> None:
        await self.coordinator.api.async_set_valve(self.coordinator.device_id, VALVE_CLOSED)
        await self.coordinator.async_request_refresh()
