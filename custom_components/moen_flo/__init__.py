"""The Moen Flo (SSO) integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MoenFloApi
from .const import DOMAIN
from .coordinator import MoenFloCoordinator

PLATFORMS: list[Platform] = [
    Platform.VALVE,
    Platform.ALARM_CONTROL_PANEL,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
]

type MoenFloConfigEntry = ConfigEntry[MoenFloCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: MoenFloConfigEntry) -> bool:
    """Set up Moen Flo (SSO) from a config entry."""
    session = async_get_clientsession(hass)
    api = MoenFloApi(session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    coordinator = MoenFloCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MoenFloConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
