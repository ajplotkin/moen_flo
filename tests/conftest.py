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


def load_coordinator():
    """Load coordinator.py with Home Assistant stubbed out.

    The repair-issue logic is the whole visibility mechanism for the legacy fallback,
    so it needs tests — but pulling in Home Assistant just to exercise a counter and
    two registry calls is not worth it. Only the handful of names coordinator.py
    imports are stubbed; the module's own code runs unmodified.
    """
    import sys
    import types

    issues = {}

    def _mk(name, **attrs):
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
        return m

    class _Sev:
        WARNING = "warning"

    def _create(hass, domain, issue_id, **kw):
        issues[(domain, issue_id)] = kw

    def _delete(hass, domain, issue_id):
        issues.pop((domain, issue_id), None)

    ir = _mk("homeassistant.helpers.issue_registry",
             async_create_issue=_create, async_delete_issue=_delete, IssueSeverity=_Sev)

    class _DUC:
        # coordinator.py subscripts this (DataUpdateCoordinator[dict[str, Any]]),
        # so the stub has to accept it.
        def __init__(self, *a, **kw):
            pass

        def __class_getitem__(cls, _item):
            return cls

    _mk("homeassistant", helpers=None)
    _mk("homeassistant.config_entries", ConfigEntry=object)
    _mk("homeassistant.core", HomeAssistant=object)
    _mk("homeassistant.exceptions", ConfigEntryAuthFailed=type("ConfigEntryAuthFailed", (Exception,), {}))
    _mk("homeassistant.helpers", issue_registry=ir)
    _mk("homeassistant.helpers.update_coordinator", DataUpdateCoordinator=_DUC,
        UpdateFailed=type("UpdateFailed", (Exception,), {}))
    _mk("homeassistant.util", dt=types.SimpleNamespace(now=lambda: None, as_utc=lambda x: x, utcnow=lambda: None))

    import importlib.util
    spec = importlib.util.spec_from_file_location("moen_flo_std.coordinator", COMPONENT / "coordinator.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["moen_flo_std.coordinator"] = mod
    spec.loader.exec_module(mod)
    return mod, issues
