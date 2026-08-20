"""Config flow for Moen Flo (SSO)."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from collections.abc import Mapping

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MoenFloApi, MoenFloAuthError, MoenFloError
from .const import AUTH_MODE_LEGACY, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER = vol.Schema(
    {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}
)
STEP_REAUTH = vol.Schema({vol.Required(CONF_PASSWORD): str})


async def _validate(hass, username: str, password: str) -> str | None:
    """Return an error key, or None if the credentials work."""
    api = MoenFloApi(async_get_clientsession(hass), username, password)
    try:
        mode = await api.async_validate()
        if mode == AUTH_MODE_LEGACY:
            # Setup completed during an SSO outage. The coordinator raises a repair
            # issue once it is polling, but say so here too: otherwise this looks
            # identical to a normal setup and the entry silently starts on the
            # fallback flow.
            _LOGGER.warning(
                "Set up using the legacy Flo login because Moen SSO sign-in failed. "
                "SSO is retried on every token renewal"
            )
        await api.async_discover_valve()
    except MoenFloAuthError:
        return "invalid_auth"
    except MoenFloError:
        return "cannot_connect"
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Unexpected error validating Moen Flo login")
        return "unknown"
    return None


class MoenFloConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Moen Flo (SSO) config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME]
            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()

            error = await _validate(self.hass, username, user_input[CONF_PASSWORD])
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(title=f"Flo ({username})", data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, object]
    ) -> ConfigFlowResult:
        """Handle re-authentication when the stored password stops working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, object] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        if user_input is not None:
            error = await _validate(
                self.hass, reauth_entry.data[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH,
            errors=errors,
            description_placeholders={
                CONF_USERNAME: reauth_entry.data[CONF_USERNAME]
            },
        )
