"""Alarm-control-panel façade so Apple Home shows the old Home/Away/Off mode tile.

This carries ONLY the Flo system mode (never leak state), reproducing the original
Homebridge accessory's picker:
    armed_home  -> Flo "home"
    armed_away  -> Flo "away"
    disarmed    -> Flo "sleep"  ("Off" = temporary pause; auto-reverts to Home)
"""

from __future__ import annotations

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MoenFloConfigEntry
from .const import MODE_AWAY, MODE_HOME, MODE_SLEEP
from .entity import MoenFloEntity

MODE_TO_STATE = {
    MODE_HOME: AlarmControlPanelState.ARMED_HOME,
    MODE_AWAY: AlarmControlPanelState.ARMED_AWAY,
    MODE_SLEEP: AlarmControlPanelState.DISARMED,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MoenFloConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([MoenFloModePanel(entry.runtime_data)])


class MoenFloModePanel(MoenFloEntity, AlarmControlPanelEntity):
    """Flo system mode rendered as the HomeKit security-system tile."""

    _attr_name = "Mode"
    _attr_code_arm_required = False
    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_HOME
        | AlarmControlPanelEntityFeature.ARM_AWAY
    )

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "mode_panel")

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        mode = (self._device.get("systemMode") or {}).get("lastKnown")
        return MODE_TO_STATE.get(mode)

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        await self.coordinator.api.async_set_mode(self.coordinator.location_id, MODE_HOME)
        await self.coordinator.async_request_refresh()

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        await self.coordinator.api.async_set_mode(self.coordinator.location_id, MODE_AWAY)
        await self.coordinator.async_request_refresh()

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        # "Off" -> Sleep (temporary; api applies the default 2h / revert-home).
        await self.coordinator.api.async_set_mode(self.coordinator.location_id, MODE_SLEEP)
        await self.coordinator.async_request_refresh()
