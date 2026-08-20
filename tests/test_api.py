"""Tests for the Moen Flo API client, focused on the legacy-auth fallback."""

import json
import time

import aiohttp
import pytest

from conftest import (
    LEGACY_TOKEN,
    PASSWORD,
    SSO_TOKEN,
    SSO_TOKEN_2,
    USERNAME,
    api_mod,
    const_mod,
)

MoenFloApi = api_mod.MoenFloApi
MoenFloAuthError = api_mod.MoenFloAuthError
MoenFloError = api_mod.MoenFloError

SSO_HOST = "4j1gkf0vji.execute-api.us-east-2.amazonaws.com"
SSO_PATH = "/prod/v1/oauth2/token"
LEGACY_HOST = "api.meetflo.com"
LEGACY_PATH = "/api/v1/users/auth"
GW = "api-gw.meetflo.com"


def _ok(aresponses, payload):
    return aresponses.Response(text=json.dumps(payload), status=200)


@pytest.mark.asyncio
async def test_sso_login_sends_bearer(aresponses, sso_ok):
    """The normal path: SSO succeeds and its token is sent as a bearer token."""
    aresponses.add(SSO_HOST, SSO_PATH, "post", _ok(aresponses, sso_ok))

    async def handler(request):
        assert request.headers["Authorization"] == f"Bearer {SSO_TOKEN}"
        return _ok(aresponses, {"id": "d1"})

    aresponses.add(GW, "/api/v2/devices/d1", "get", handler)

    async with aiohttp.ClientSession() as session:
        api = MoenFloApi(session, USERNAME, PASSWORD)
        assert await api._api("GET", "/devices/d1")
        assert api.auth_mode == const_mod.AUTH_MODE_SSO


@pytest.mark.asyncio
async def test_falls_back_to_legacy_and_sends_the_token_raw(
    aresponses, legacy_ok
):
    """SSO failing must fall back, and the legacy token must NOT be a bearer token.

    Measured against api-gw on 2026-08-20: the legacy token returns 200 sent raw and
    401 sent as `Bearer <tok>`, so sending the wrong form 401s every call.
    """
    aresponses.add(SSO_HOST, SSO_PATH, "post", aresponses.Response(text=None, status=503))
    aresponses.add(LEGACY_HOST, LEGACY_PATH, "post", _ok(aresponses, legacy_ok))

    async def handler(request):
        assert request.headers["Authorization"] == LEGACY_TOKEN
        assert not request.headers["Authorization"].startswith("Bearer")
        return _ok(aresponses, {"id": "d1"})

    aresponses.add(GW, "/api/v2/devices/d1", "get", handler)

    async with aiohttp.ClientSession() as session:
        api = MoenFloApi(session, USERNAME, PASSWORD)
        assert await api._api("GET", "/devices/d1")
        assert api.auth_mode == const_mod.AUTH_MODE_LEGACY


@pytest.mark.asyncio
async def test_legacy_expiry_is_converted_from_epoch(aresponses, legacy_ok):
    """The legacy expiry is an absolute epoch; _expires_at is monotonic.

    Storing the epoch directly would make the token look valid for decades, so it
    would never be refreshed. 86400s from now must land ~a day out, not ~56 years.
    """
    aresponses.add(SSO_HOST, SSO_PATH, "post", aresponses.Response(text=None, status=503))
    aresponses.add(LEGACY_HOST, LEGACY_PATH, "post", _ok(aresponses, legacy_ok))

    async with aiohttp.ClientSession() as session:
        api = MoenFloApi(session, USERNAME, PASSWORD)
        await api._login()
        remaining = api._expires_at - time.monotonic()
        assert 86000 < remaining < 86400, remaining


@pytest.mark.asyncio
async def test_legacy_token_string_shape_does_not_crash(aresponses, legacy_ok):
    """The legacy response's "token" is a STRING, not an object.

    The SSO path does data["token"]["access_token"]; applied to the legacy shape that
    raises AttributeError rather than an auth error.
    """
    assert isinstance(legacy_ok["token"], str)
    aresponses.add(SSO_HOST, SSO_PATH, "post", aresponses.Response(text=None, status=503))
    aresponses.add(LEGACY_HOST, LEGACY_PATH, "post", _ok(aresponses, legacy_ok))

    async with aiohttp.ClientSession() as session:
        api = MoenFloApi(session, USERNAME, PASSWORD)
        await api._login()
        assert api._access_token == LEGACY_TOKEN


@pytest.mark.asyncio
async def test_bad_credentials_report_the_sso_auth_error(aresponses):
    """When both fail and SSO failed on credentials, raise the auth error.

    Raising the legacy leg's error instead could surface a network failure for a bad
    password, which the config flow turns into "cannot connect".
    """
    aresponses.add(SSO_HOST, SSO_PATH, "post", aresponses.Response(text="nope", status=401))
    aresponses.add(LEGACY_HOST, LEGACY_PATH, "post",
                   aresponses.Response(text="boom", status=500))

    async with aiohttp.ClientSession() as session:
        api = MoenFloApi(session, USERNAME, PASSWORD)
        with pytest.raises(MoenFloAuthError):
            await api._login()


@pytest.mark.asyncio
async def test_otp_challenge_falls_back(aresponses, legacy_ok):
    """A 200 carrying no access token is an SSO obstacle; fall back rather than fail."""
    aresponses.add(SSO_HOST, SSO_PATH, "post",
                   _ok(aresponses, {"token": {"challenge": "OTP"}}))
    aresponses.add(LEGACY_HOST, LEGACY_PATH, "post", _ok(aresponses, legacy_ok))

    async with aiohttp.ClientSession() as session:
        api = MoenFloApi(session, USERNAME, PASSWORD)
        await api._login()
        assert api.auth_mode == const_mod.AUTH_MODE_LEGACY


@pytest.mark.asyncio
async def test_legacy_mode_retries_sso_on_renewal(aresponses, legacy_ok, sso_ok):
    """Legacy mode has no refresh token, and re-login must try SSO first.

    That is what lets a transient SSO outage heal instead of pinning the integration
    to the fallback until a restart.
    """
    aresponses.add(SSO_HOST, SSO_PATH, "post", aresponses.Response(text=None, status=503))
    aresponses.add(LEGACY_HOST, LEGACY_PATH, "post", _ok(aresponses, legacy_ok))
    # SSO is healthy again on renewal:
    aresponses.add(SSO_HOST, SSO_PATH, "post", _ok(aresponses, sso_ok))

    async with aiohttp.ClientSession() as session:
        api = MoenFloApi(session, USERNAME, PASSWORD)
        await api._login()
        assert api.auth_mode == const_mod.AUTH_MODE_LEGACY
        api._expires_at = 0  # force renewal
        await api._ensure_token()
        assert api.auth_mode == const_mod.AUTH_MODE_SSO
        assert api._access_token == SSO_TOKEN


@pytest.mark.asyncio
async def test_401_refresh_uses_token_and_mode(aresponses, sso_ok):
    """A 401 refreshes once and retries with the new token."""
    aresponses.add(SSO_HOST, SSO_PATH, "post", _ok(aresponses, sso_ok))
    aresponses.add(GW, "/api/v2/devices/d1", "get", aresponses.Response(text=None, status=401))
    aresponses.add(SSO_HOST, SSO_PATH, "post",
                   _ok(aresponses, {"token": {"access_token": SSO_TOKEN_2, "expires_in": 3600}}))

    async def retried(request):
        assert request.headers["Authorization"] == f"Bearer {SSO_TOKEN_2}"
        return _ok(aresponses, {"id": "d1"})

    aresponses.add(GW, "/api/v2/devices/d1", "get", retried)

    async with aiohttp.ClientSession() as session:
        api = MoenFloApi(session, USERNAME, PASSWORD)
        assert await api._api("GET", "/devices/d1")


@pytest.mark.asyncio
async def test_async_validate_reports_the_mode(aresponses, legacy_ok):
    """Setup completed during an SSO outage must be distinguishable from a normal one."""
    aresponses.add(SSO_HOST, SSO_PATH, "post", aresponses.Response(text=None, status=503))
    aresponses.add(LEGACY_HOST, LEGACY_PATH, "post", _ok(aresponses, legacy_ok))

    async with aiohttp.ClientSession() as session:
        api = MoenFloApi(session, USERNAME, PASSWORD)
        assert await api.async_validate() == const_mod.AUTH_MODE_LEGACY


@pytest.mark.asyncio
async def test_non_auth_sso_failure_on_refresh_falls_back(aresponses, sso_ok, legacy_ok):
    """A 5xx/timeout on the SSO refresh must fall back, not propagate.

    Regression test: _refresh originally caught only MoenFloAuthError, so a running
    instance hitting a 503 (or DNS failure, or timeout) on renewal raised every poll,
    never reached _login, and therefore never reached the legacy endpoint — leaving
    the valve unavailable until Home Assistant restarted. That is exactly the outage
    class the fallback exists for.
    """
    aresponses.add(SSO_HOST, SSO_PATH, "post", _ok(aresponses, sso_ok))
    # Renewal: the refresh grant AND the full SSO login both fail non-authly.
    aresponses.add(SSO_HOST, SSO_PATH, "post", aresponses.Response(text="down", status=503))
    aresponses.add(SSO_HOST, SSO_PATH, "post", aresponses.Response(text="down", status=503))
    aresponses.add(LEGACY_HOST, LEGACY_PATH, "post", _ok(aresponses, legacy_ok))

    async with aiohttp.ClientSession() as session:
        api = MoenFloApi(session, USERNAME, PASSWORD)
        await api._login()
        assert api.auth_mode == const_mod.AUTH_MODE_SSO
        api._expires_at = 0
        await api._ensure_token()
        assert api.auth_mode == const_mod.AUTH_MODE_LEGACY
        assert api._access_token == LEGACY_TOKEN


@pytest.mark.asyncio
async def test_sso_login_uses_the_shorter_timeout(aresponses, sso_ok):
    """The SSO leg of a login uses SSO_LOGIN_TIMEOUT, not REQUEST_TIMEOUT.

    Both legs run holding the token lock, so a dead SSO endpoint would otherwise
    block every in-flight call for the full request timeout twice over.
    """
    seen = {}
    real_timeout = api_mod.asyncio.timeout

    def spy(delay):
        seen.setdefault("first", delay)
        return real_timeout(delay)

    aresponses.add(SSO_HOST, SSO_PATH, "post", _ok(aresponses, sso_ok))
    api_mod.asyncio.timeout = spy
    try:
        async with aiohttp.ClientSession() as session:
            api = MoenFloApi(session, USERNAME, PASSWORD)
            await api._login()
    finally:
        api_mod.asyncio.timeout = real_timeout

    assert seen["first"] == const_mod.SSO_LOGIN_TIMEOUT
    assert seen["first"] != const_mod.REQUEST_TIMEOUT


@pytest.mark.asyncio
async def test_short_legacy_expiry_is_floored(aresponses):
    """A nonsense/short legacy expiry must not produce an already-expired token."""
    aresponses.add(SSO_HOST, SSO_PATH, "post", aresponses.Response(text=None, status=503))
    aresponses.add(LEGACY_HOST, LEGACY_PATH, "post", _ok(aresponses, {
        "token": LEGACY_TOKEN,
        "tokenPayload": {"user": {"user_id": "u-1"}, "timestamp": round(time.time()) - 100},
        "tokenExpiration": 1,
    }))

    async with aiohttp.ClientSession() as session:
        api = MoenFloApi(session, USERNAME, PASSWORD)
        await api._login()
        # Floor (120) minus margin (60) => at least 60s of validity, never negative.
        assert api._expires_at - time.monotonic() >= 55


@pytest.mark.asyncio
async def test_sso_expiry_carries_the_margin(aresponses):
    """The SSO expiry is held back so a request in flight cannot race it."""
    aresponses.add(SSO_HOST, SSO_PATH, "post", _ok(aresponses, {
        "token": {"access_token": SSO_TOKEN, "expires_in": 3600}
    }))
    async with aiohttp.ClientSession() as session:
        api = MoenFloApi(session, USERNAME, PASSWORD)
        await api._login()
        remaining = api._expires_at - time.monotonic()
        assert 3400 < remaining < 3600 - 30, remaining


@pytest.mark.asyncio
async def test_sso_token_without_expires_in_gets_a_usable_default(aresponses):
    """A response omitting expires_in must not store an already-expired token."""
    aresponses.add(SSO_HOST, SSO_PATH, "post",
                   _ok(aresponses, {"token": {"access_token": SSO_TOKEN}}))
    async with aiohttp.ClientSession() as session:
        api = MoenFloApi(session, USERNAME, PASSWORD)
        await api._login()
        assert api._expires_at - time.monotonic() > 600


@pytest.mark.asyncio
async def test_force_refresh_skips_when_another_task_rotated(aresponses, sso_ok):
    """A 401 handler must not re-refresh a token someone else already replaced."""
    aresponses.add(SSO_HOST, SSO_PATH, "post", _ok(aresponses, sso_ok))
    async with aiohttp.ClientSession() as session:
        api = MoenFloApi(session, USERNAME, PASSWORD)
        await api._login()
        # Pretend another task rotated the token while we held a stale snapshot.
        stale = ("some-older-token", const_mod.AUTH_MODE_SSO)
        await api._force_refresh(stale)   # no HTTP registered: must not call out
        assert api._access_token == SSO_TOKEN
