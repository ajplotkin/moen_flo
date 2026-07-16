"""DataUpdateCoordinator for Moen Flo (SSO)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import MoenFloApi, MoenFloAuthError, MoenFloError
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class MoenFloCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the Flo device state (valve, mode, telemetry, alerts, usage)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: MoenFloApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
            config_entry=entry,
        )
        self.entry = entry
        self.api = api
        self.device_id: str | None = None
        self.location_id: str | None = None
        self.mac_address: str | None = None
        self._static: dict[str, Any] = {}

    async def _async_setup(self) -> None:
        """One-time discovery of the valve device."""
        device = await self.api.async_discover_valve()
        self.device_id = device["id"]
        self.location_id = device.get("_location_id")
        self.mac_address = device.get("macAddress")
        self._static = {
            "nickname": device.get("nickname", "Flo"),
            "deviceModel": device.get("deviceModel"),
            "serialNumber": device.get("serialNumber"),
            "fwVersion": device.get("fwVersion"),
        }

    async def _async_update_data(self) -> dict[str, Any]:
        if self.device_id is None:
            await self._async_setup()
        try:
            device = await self.api.async_get_device(self.device_id)
        except MoenFloAuthError as err:
            # Stored password no longer works -> prompt the user to re-auth.
            raise ConfigEntryAuthFailed(str(err)) from err
        except MoenFloError as err:
            raise UpdateFailed(str(err)) from err

        consumption = None
        if self.mac_address:
            now_local = dt_util.now()
            start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            start_utc = dt_util.as_utc(start_local)
            end_utc = dt_util.utcnow()
            tzinfo = now_local.tzinfo
            tz_name = getattr(tzinfo, "key", None) or str(tzinfo)
            consumption = await self.api.async_get_today_consumption(
                self.mac_address,
                start_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                end_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                tz_name,
            )

        return {
            "device": device,
            "consumption_today": consumption,
            "static": {**self._static, "deviceModel": device.get("deviceModel", self._static.get("deviceModel")),
                       "fwVersion": device.get("fwVersion", self._static.get("fwVersion"))},
        }
