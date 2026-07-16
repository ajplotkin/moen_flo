"""Async client for the Flo shutoff valve over Moen SSO auth.

api-gw.meetflo.com/v2 now requires the Moen Cognito access token (client
6qn9pep31dglq6ed4fvlq6rp5t), NOT the legacy Flo v1 users/auth token. This client
logs in via oauth2/token, refreshes on expiry/401, and drives the valve + mode.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import aiohttp

from .const import (
    API_GW,
    DEFAULT_SLEEP_MINUTES,
    DEFAULT_SLEEP_REVERT,
    FLO_DEVICE_TYPES,
    MODE_SLEEP,
    OAUTH_CLIENT_ID,
    OAUTH_URL,
    REQUEST_TIMEOUT,
    SLEEP_MINUTE_OPTIONS,
    SYSTEM_MODES,
    USER_AGENT,
    VALVE_CLOSED,
    VALVE_OPEN,
)

_LOGGER = logging.getLogger(__name__)


class MoenFloError(Exception):
    """Generic Moen/Flo API error."""


class MoenFloAuthError(MoenFloError):
    """Authentication failed (bad credentials)."""


class MoenFloApi:
    """Minimal async client: Moen SSO auth + api-gw valve/mode control."""

    def __init__(
        self, session: aiohttp.ClientSession, username: str, password: str
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0.0
        self._token_lock = asyncio.Lock()

    # ---- auth ------------------------------------------------------------- #
    async def _login(self) -> None:
        """Full password login against Moen oauth2/token."""
        data = await self._raw_post(
            OAUTH_URL,
            {
                "username": self._username,
                "password": self._password,
                "client_id": OAUTH_CLIENT_ID,
            },
            auth=False,
        )
        self._store_token(data)

    async def _refresh(self) -> None:
        """Refresh via refresh_token; fall back to full login."""
        if not self._refresh_token:
            await self._login()
            return
        try:
            data = await self._raw_post(
                OAUTH_URL,
                {
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                    "client_id": OAUTH_CLIENT_ID,
                },
                auth=False,
            )
            self._store_token(data)
        except MoenFloAuthError:
            await self._login()

    def _store_token(self, data: dict[str, Any]) -> None:
        token = data.get("token", data)
        access = token.get("access_token")
        if not access:
            raise MoenFloAuthError(
                "Login returned no access token (possible OTP challenge)."
            )
        self._access_token = access
        # refresh token may be absent on a refresh-grant response; keep the old one
        self._refresh_token = token.get("refresh_token", self._refresh_token)
        self._expires_at = time.monotonic() + int(token.get("expires_in", 3600)) - 60

    async def _ensure_token(self) -> None:
        if self._access_token is not None and time.monotonic() < self._expires_at:
            return
        async with self._token_lock:
            # re-check inside the lock in case another task just refreshed
            if self._access_token is not None and time.monotonic() < self._expires_at:
                return
            if self._access_token is None:
                await self._login()
            else:
                await self._refresh()

    async def _force_refresh(self, stale_token: str | None) -> None:
        """Refresh after a 401, skipping if another task already rotated the token."""
        async with self._token_lock:
            if self._access_token != stale_token:
                return
            await self._refresh()

    async def async_validate(self) -> None:
        """Used by the config flow: confirm credentials work."""
        await self._login()

    # ---- HTTP ------------------------------------------------------------- #
    async def _raw_post(self, url: str, body: dict, *, auth: bool) -> dict[str, Any]:
        headers = {"Content-Type": "application/json;charset=UTF-8", "User-Agent": USER_AGENT}
        if auth:
            headers["Authorization"] = f"Bearer {self._access_token}"
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                resp = await self._session.post(url, json=body, headers=headers)
                if resp.status in (401, 403):
                    raise MoenFloAuthError(f"{resp.status}: {await resp.text()}")
                if resp.status >= 400:
                    raise MoenFloError(f"{resp.status}: {await resp.text()}")
                try:
                    return await resp.json(content_type=None)
                except ValueError as err:
                    raise MoenFloError(f"Non-JSON auth response: {err}") from err
        except (TimeoutError, aiohttp.ClientError) as err:
            raise MoenFloError(f"Connection error: {err}") from err

    async def _api(self, method: str, path: str, json_body: dict | None = None) -> Any:
        """Call api-gw with a valid token; refresh once on 401 and retry."""
        await self._ensure_token()
        url = f"{API_GW}{path}"
        for attempt in (1, 2):
            used_token = self._access_token
            headers = {
                "Authorization": f"Bearer {used_token}",
                "User-Agent": USER_AGENT,
                "Content-Type": "application/json",
            }
            # Read the full response inside the timeout; decide (incl. refresh) outside it.
            try:
                async with asyncio.timeout(REQUEST_TIMEOUT):
                    resp = await self._session.request(
                        method, url, json=json_body, headers=headers
                    )
                    status = resp.status
                    raw = await resp.read()
                    content_type = resp.content_type
            except (TimeoutError, aiohttp.ClientError) as err:
                raise MoenFloError(f"Connection error on {path}: {err}") from err

            if status in (401, 403) and attempt == 1:
                await self._force_refresh(used_token)
                continue
            text = raw.decode(errors="replace")
            if status in (401, 403):
                raise MoenFloAuthError(f"{status}: {text}")
            if status >= 400:
                raise MoenFloError(f"{status} from {path}: {text}")
            # Success — tolerate empty / non-JSON bodies (some writes return either).
            if not raw:
                return {}
            try:
                return json.loads(text)
            except ValueError:
                return {}
        raise MoenFloError(f"Unreachable retry loop for {path}")

    # ---- discovery / reads ----------------------------------------------- #
    async def async_discover_valve(self) -> dict[str, Any]:
        """Return the first whole-home valve device object (incl. location id)."""
        user = await self._api("GET", "/users/me?expand=locations")
        for loc in user.get("locations", []):
            loc_id = loc.get("id") if isinstance(loc, dict) else loc
            full = await self._api("GET", f"/locations/{loc_id}?expand=devices")
            for dev in full.get("devices", []):
                dev_id = dev.get("id") if isinstance(dev, dict) else dev
                d = dev if isinstance(dev, dict) and dev.get("deviceType") else \
                    await self._api("GET", f"/devices/{dev_id}")
                if d.get("deviceType") in FLO_DEVICE_TYPES or "valve" in d:
                    d["_location_id"] = loc_id
                    return d
        raise MoenFloError("No whole-home Flo valve found on this account.")

    async def async_get_device(self, device_id: str) -> dict[str, Any]:
        return await self._api("GET", f"/devices/{device_id}")

    async def async_get_today_consumption(
        self, mac_address: str, start_iso: str, end_iso: str, tz: str
    ) -> float | None:
        """Total gallons used so far today. Best-effort (verified endpoint shape)."""
        path = (
            f"/water/consumption?startDate={start_iso}&endDate={end_iso}"
            f"&macAddress={mac_address}&interval=1h&tz={tz}"
        )
        try:
            data = await self._api("GET", path)
        except MoenFloError:
            return None
        agg = data.get("aggregations", {})
        total = agg.get("sumTotalGallonsConsumed")
        if total is None:
            items = data.get("items", [])
            total = sum(i.get("gallonsConsumed", 0) for i in items) or None
        return round(total, 1) if isinstance(total, (int, float)) else None

    # ---- writes ----------------------------------------------------------- #
    async def async_set_valve(self, device_id: str, target: str) -> None:
        if target not in (VALVE_OPEN, VALVE_CLOSED):
            raise MoenFloError(f"invalid valve target {target!r}")
        await self._api("POST", f"/devices/{device_id}", {"valve": {"target": target}})

    async def async_set_mode(
        self,
        location_id: str,
        mode: str,
        revert_minutes: int = DEFAULT_SLEEP_MINUTES,
        revert_mode: str = DEFAULT_SLEEP_REVERT,
    ) -> None:
        if mode not in SYSTEM_MODES:
            raise MoenFloError(f"invalid mode {mode!r}")
        body: dict[str, Any] = {"target": mode}
        if mode == MODE_SLEEP:
            if revert_minutes not in SLEEP_MINUTE_OPTIONS:
                revert_minutes = DEFAULT_SLEEP_MINUTES
            body["revertMinutes"] = revert_minutes
            body["revertMode"] = revert_mode
        await self._api("POST", f"/locations/{location_id}/systemMode", body)
