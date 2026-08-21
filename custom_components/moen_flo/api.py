"""Async client for the Flo shutoff valve over Moen SSO auth.

This client logs in via Moen's Cognito oauth2/token endpoint (client
6qn9pep31dglq6ed4fvlq6rp5t), refreshes on expiry/401, and drives the valve + mode.
That is the auth the current Moen Smartwater app uses.

⚠ It is NOT true that api-gw.meetflo.com/v2 requires the Cognito token. That was
written here on 2026-07-16 and re-tested on 2026-08-20: the legacy Flo v1
users/auth token is still accepted by api-gw — 200 on /api/v2/users/{id} and
/api/v2/devices/{id}. Whether Moen changed something or the credential state
differed in July is unknown. SSO is used here because it is the current app's
flow and is the one likely to outlive v1, not because v1 is broken.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import aiohttp

from .const import (
    ALARMS_PATH,
    API_GW,
    AUTH_MODE_LEGACY,
    AUTH_MODE_SSO,
    DEFAULT_SLEEP_MINUTES,
    DEFAULT_SLEEP_REVERT,
    FLO_DEVICE_TYPES,
    LEGACY_AUTH_URL,
    MODE_SLEEP,
    OAUTH_CLIENT_ID,
    OAUTH_URL,
    REQUEST_TIMEOUT,
    SLEEP_MINUTE_OPTIONS,
    SSO_LOGIN_TIMEOUT,
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
        # Which flow produced _access_token. It decides the Authorization header form
        # and is therefore only meaningful TOGETHER with the token -- see _api().
        self._auth_mode: str = AUTH_MODE_SSO
        self._expires_at: float = 0.0
        self._token_lock = asyncio.Lock()

    # ---- auth ------------------------------------------------------------- #
    async def _login(self) -> None:
        """Log in, preferring Moen SSO and falling back to the legacy Flo flow.

        SSO is tried first on every login, including while already running in legacy
        mode, so a transient SSO outage heals itself on the next token cycle rather
        than pinning the integration to the legacy flow until a restart.
        """
        try:
            data = await self._raw_post(
                OAUTH_URL,
                {
                    "username": self._username,
                    "password": self._password,
                    "client_id": OAUTH_CLIENT_ID,
                },
                timeout=SSO_LOGIN_TIMEOUT,
            )
            # Inside the try on purpose: a 200 carrying no access token (an OTP
            # challenge) is an SSO-side obstacle like any other, so it falls back
            # rather than failing setup. The repair issue is what stops that being
            # a silent downgrade.
            self._store_token(data)
        except (MoenFloAuthError, MoenFloError) as sso_err:
            _LOGGER.warning(
                "Moen SSO login failed (%s); trying the legacy Flo login. The SSO "
                "endpoint and client id are undocumented and can change without notice",
                sso_err,
            )
            try:
                await self._legacy_login()
            except (MoenFloAuthError, MoenFloError) as legacy_err:
                # Both failed. If SSO failed on credentials, that is the useful error:
                # raising the legacy one could report a network problem for a bad
                # password, which the config flow turns into "cannot connect".
                if isinstance(sso_err, MoenFloAuthError):
                    raise sso_err
                raise legacy_err from sso_err
            _LOGGER.warning(
                "Authenticated with the legacy Flo login instead of Moen SSO"
            )

    async def _legacy_login(self) -> None:
        """Password login against the legacy Flo v1 endpoint."""
        data = await self._raw_post(
            LEGACY_AUTH_URL,
            {"username": self._username, "password": self._password},
        )
        self._store_legacy_token(data)

    async def _refresh(self) -> None:
        """Refresh via refresh_token; fall back to full login.

        The legacy flow issues no refresh token, so legacy mode always re-logs in --
        which is also what gives SSO a chance to come back (see _login).
        """
        if self._auth_mode == AUTH_MODE_LEGACY or not self._refresh_token:
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
            )
            self._store_token(data)
        except (MoenFloAuthError, MoenFloError):
            # MoenFloError as well as MoenFloAuthError: a refresh that fails with a
            # 5xx, a timeout or a DNS failure is exactly the SSO outage this fallback
            # exists for. Catching only the auth flavour meant a running instance
            # propagated the error every poll, never reached _login (and therefore
            # never reached the legacy endpoint), and left the valve unavailable until
            # Home Assistant restarted.
            await self._login()

    def _store_token(self, data: dict[str, Any]) -> None:
        token = data.get("token", data)
        access = token.get("access_token")
        if not access:
            raise MoenFloAuthError(
                "Login returned no access token (possible OTP challenge)."
            )
        # Token and mode are written together; nothing may observe one without the
        # other, because the mode decides the header form.
        self._access_token = access
        self._auth_mode = AUTH_MODE_SSO
        # refresh token may be absent on a refresh-grant response; keep the old one
        self._refresh_token = token.get("refresh_token", self._refresh_token)
        self._expires_at = time.monotonic() + int(token.get("expires_in", 3600)) - 60

    def _store_legacy_token(self, data: dict[str, Any]) -> None:
        """Record a legacy Flo token.

        The legacy response is shaped differently from the SSO one in two ways that
        both bite: "token" is the JWT STRING rather than an object (so the SSO path's
        data["token"]["access_token"] raises AttributeError on it), and the expiry is
        an ABSOLUTE epoch pair. _expires_at is monotonic-based, so the epoch has to be
        converted to a duration first -- writing the epoch straight in would make the
        token look valid for decades and it would never be refreshed.
        """
        token = data.get("token")
        if not isinstance(token, str) or not token:
            raise MoenFloAuthError("Legacy login returned no token.")

        payload = data.get("tokenPayload") or {}
        issued = payload.get("timestamp")
        lifetime = data.get("tokenExpiration")
        if isinstance(issued, (int, float)) and isinstance(lifetime, (int, float)):
            remaining = (float(issued) + float(lifetime)) - time.time()
        else:
            remaining = 3600.0
        # Never trust the server into the past, and always keep the 60s margin.
        remaining = max(remaining, 120.0)

        self._access_token = token
        self._auth_mode = AUTH_MODE_LEGACY
        self._refresh_token = None
        self._expires_at = time.monotonic() + remaining - 60

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

    async def _force_refresh(self, stale: tuple[str | None, str]) -> None:
        """Refresh after a 401, skipping if another task already rotated the token.

        The comparison is on (token, mode) rather than the token alone: a fallback can
        change the header form, and a caller that read the pair before that happened
        must not suppress the refresh just because the token string still matches.
        """
        async with self._token_lock:
            if (self._access_token, self._auth_mode) != stale:
                return
            await self._refresh()

    def _auth_header(self) -> str:
        """Authorization value for the current mode.

        The two token types are NOT interchangeable here. Measured 2026-08-20 against
        GET api-gw /api/v2/users/{id}: the SSO access token must be sent as
        "Bearer <tok>" (200), while the legacy token must be sent raw (200) and gets a
        401 if sent as a Bearer. Getting this wrong 401s every call, which the
        coordinator turns into a reauth prompt that then "succeeds" and loops.
        """
        if self._auth_mode == AUTH_MODE_LEGACY:
            return self._access_token or ""
        return f"Bearer {self._access_token}"

    @property
    def auth_mode(self) -> str:
        """Which flow produced the current token."""
        return self._auth_mode

    async def async_validate(self) -> str:
        """Used by the config flow: confirm credentials work.

        Returns the auth mode that succeeded, so a setup completed during an SSO
        outage does not silently look identical to a normal one.
        """
        await self._login()
        return self._auth_mode

    # ---- HTTP ------------------------------------------------------------- #
    async def _raw_post(
        self, url: str, body: dict, *, timeout: int | None = None
    ) -> dict[str, Any]:
        """POST to an auth endpoint. Never sends an Authorization header.

        Only the SSO and legacy token endpoints go through here, and neither takes
        one -- the SSO endpoint 401s on a stale bearer. Authenticated calls go via
        _api(), which sets the header per auth mode.
        """
        headers = {"Content-Type": "application/json;charset=UTF-8", "User-Agent": USER_AGENT}
        try:
            async with asyncio.timeout(timeout or REQUEST_TIMEOUT):
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
            # Read token and mode in ONE statement. There is no await between them,
            # so asyncio cannot interleave a fallback that changes the header form
            # and leave us sending an SSO token raw (or a legacy token as a Bearer).
            used = (self._access_token, self._auth_mode)
            headers = {
                "Authorization": self._auth_header(),
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
                await self._force_refresh(used)
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

    async def async_get_alarm_catalog(self) -> dict[int, dict[str, Any]]:
        """Fetch the static alarm catalog: {id: {"name": ..., "severity": ...}}.

        Lets us report *which* alarm is pending by name rather than a bare id, and
        distinguish real leaks from other critical alarms. Best-effort: an empty map
        just means attributes fall back to ids.
        """
        catalog: dict[int, dict[str, Any]] = {}
        try:
            data = await self._api("GET", ALARMS_PATH)
            items = data.get("items") if isinstance(data, dict) else data
            for alarm in items or []:
                if not isinstance(alarm, dict):
                    continue
                try:
                    alarm_id = int(alarm["id"])
                except (KeyError, TypeError, ValueError):
                    continue  # skip an unparseable entry, keep the rest
                catalog[alarm_id] = {
                    "name": alarm.get("displayName") or alarm.get("name"),
                    "severity": alarm.get("severity"),
                }
        except Exception:  # noqa: BLE001 - cosmetic lookup must never break setup
            _LOGGER.debug("Could not fetch alarm catalog; continuing without names")
            return {}
        return catalog

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
