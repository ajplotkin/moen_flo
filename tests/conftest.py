"""Test fixtures.

`custom_components/moen_flo/__init__.py` imports Home Assistant, which isn't a test
dependency here — the API client itself only needs aiohttp. So the client and its
constants are loaded directly as a standalone package rather than importing the
integration.
"""

import importlib.util
import pathlib
import sys
import types

import pytest

COMPONENT = pathlib.Path(__file__).parent.parent / "custom_components" / "moen_flo"


def _load():
    pkg = types.ModuleType("moen_flo_std")
    pkg.__path__ = [str(COMPONENT)]
    sys.modules["moen_flo_std"] = pkg
    for name in ("const", "api"):
        spec = importlib.util.spec_from_file_location(
            f"moen_flo_std.{name}", COMPONENT / f"{name}.py"
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"moen_flo_std.{name}"] = mod
        spec.loader.exec_module(mod)
    return sys.modules["moen_flo_std.api"], sys.modules["moen_flo_std.const"]


api_mod, const_mod = _load()

USERNAME = "user@example.com"
PASSWORD = "hunter2"
SSO_TOKEN = "sso-access-token"
SSO_TOKEN_2 = "sso-access-token-2"
SSO_REFRESH = "sso-refresh-token"
LEGACY_TOKEN = "legacy.jwt.token"


@pytest.fixture()
def sso_ok():
    """A successful Moen SSO token response."""
    return {
        "token": {
            "access_token": SSO_TOKEN,
            "refresh_token": SSO_REFRESH,
            "token_type": "Bearer",
            "expires_in": 3600,
        }
    }


@pytest.fixture()
def legacy_ok():
    """A successful legacy Flo users/auth response.

    Note the shape: "token" is the JWT STRING, and the expiry is an absolute epoch
    pair rather than a duration.
    """
    import time

    now = round(time.time())
    return {
        "token": LEGACY_TOKEN,
        "tokenPayload": {"user": {"user_id": "u-1"}, "timestamp": now},
        "tokenExpiration": 86400,
    }
