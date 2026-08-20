"""Tests for the legacy-auth repair issue.

The repair issue is the only thing that makes a fallback to the legacy login visible
to the user, so its lifecycle is worth pinning down.
"""

import types

import pytest

from conftest import const_mod, load_coordinator

coord_mod, ISSUES = load_coordinator()
KEY = (const_mod.DOMAIN, const_mod.ISSUE_LEGACY_AUTH)


def _coordinator(mode):
    """A coordinator with just enough shape to exercise _check_auth_mode."""
    c = object.__new__(coord_mod.MoenFloCoordinator)
    c._legacy_polls = 0
    c.hass = object()
    c.api = types.SimpleNamespace(auth_mode=mode)
    return c


@pytest.fixture(autouse=True)
def _clear_issues():
    ISSUES.clear()
    yield
    ISSUES.clear()


def test_issue_is_debounced():
    """A single legacy poll must not raise the issue; the third must."""
    c = _coordinator(const_mod.AUTH_MODE_LEGACY)
    for _ in range(const_mod.LEGACY_AUTH_ISSUE_AFTER - 1):
        c._check_auth_mode()
        assert KEY not in ISSUES
    c._check_auth_mode()
    assert KEY in ISSUES
    assert ISSUES[KEY]["translation_key"] == const_mod.ISSUE_LEGACY_AUTH
    assert ISSUES[KEY]["is_fixable"] is False


def test_issue_clears_when_sso_returns():
    c = _coordinator(const_mod.AUTH_MODE_LEGACY)
    for _ in range(const_mod.LEGACY_AUTH_ISSUE_AFTER):
        c._check_auth_mode()
    assert KEY in ISSUES

    c.api.auth_mode = const_mod.AUTH_MODE_SSO
    c._check_auth_mode()
    assert KEY not in ISSUES
    assert c._legacy_polls == 0


def test_a_reloaded_coordinator_clears_a_stale_issue():
    """Regression: the delete was gated on this instance having counted legacy polls.

    _legacy_polls is per-instance, so after a config-entry reload — which is exactly
    what the reauth flow does — a fresh coordinator running happily on SSO would never
    clear an issue raised by the previous instance, and it stuck until HA restarted.
    """
    old = _coordinator(const_mod.AUTH_MODE_LEGACY)
    for _ in range(const_mod.LEGACY_AUTH_ISSUE_AFTER):
        old._check_auth_mode()
    assert KEY in ISSUES

    fresh = _coordinator(const_mod.AUTH_MODE_SSO)   # reload: counter starts at 0
    fresh._check_auth_mode()
    assert KEY not in ISSUES


def test_transient_legacy_poll_does_not_flap():
    """One legacy poll between healthy ones must not raise anything."""
    c = _coordinator(const_mod.AUTH_MODE_SSO)
    c._check_auth_mode()
    c.api.auth_mode = const_mod.AUTH_MODE_LEGACY
    c._check_auth_mode()
    c.api.auth_mode = const_mod.AUTH_MODE_SSO
    c._check_auth_mode()
    assert KEY not in ISSUES
    assert c._legacy_polls == 0
