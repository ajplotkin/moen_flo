"""Constants for the Moen Flo (SSO) integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "moen_flo"

# Moen SSO (Cognito) auth — the flow the current Moen Smartwater app uses.
# Observed from the app, not documented, so both values can change without notice.
OAUTH_URL = "https://4j1gkf0vji.execute-api.us-east-2.amazonaws.com/prod/v1/oauth2/token"
OAUTH_CLIENT_ID = "6qn9pep31dglq6ed4fvlq6rp5t"

# Legacy Flo login, used only as a fallback when the SSO endpoint above fails.
# OAUTH_URL is a raw API Gateway host and OAUTH_CLIENT_ID is scraped from the app, so
# either can change without notice; this is the second way in when that happens.
LEGACY_AUTH_URL = "https://api.meetflo.com/api/v1/users/auth"

# The SSO attempt of a fallback login gets a shorter timeout than a normal request:
# both legs run while holding the token lock, so a dead SSO endpoint would otherwise
# block every in-flight call for REQUEST_TIMEOUT twice over.
SSO_LOGIN_TIMEOUT = 8

AUTH_MODE_SSO = "sso"
AUTH_MODE_LEGACY = "legacy"

# A repair issue is raised when the integration has fallen back to the legacy login,
# so the switch is visible in Settings > Repairs rather than only in the log. Requires
# this many consecutive legacy polls first: a single SSO blip heals on the next token
# cycle and should not raise and clear an issue each time.
ISSUE_LEGACY_AUTH = "using_legacy_auth"
LEGACY_AUTH_ISSUE_AFTER = 3

# Flo data/control plane. Accepts EITHER auth, but the HEADER FORM DIFFERS and is
# not interchangeable (measured 2026-08-20 on GET /api/v2/users/{id}):
#     SSO access token   -> "Authorization: Bearer <tok>"   200
#     legacy v1 token    -> "Authorization: <tok>"          200
#     legacy v1 as Bearer                                   401
# Writes work on the legacy token too: a close/open cycle over the fallback path was
# accepted and the device reported closed then open (2026-08-20). That is the device's
# reported state, not a physically observed one. This client sends the SSO token.
API_GW = "https://api-gw.meetflo.com/api/v2"

USER_AGENT = "Smartwater-iOS-prod-3.45.0"

SCAN_INTERVAL = timedelta(seconds=30)
REQUEST_TIMEOUT = 20

# Whole-home shutoff valve device models.
FLO_DEVICE_TYPES = {"flo_device_v2", "flo_device_075_v2"}

# Flo system modes (authoritative).
MODE_HOME = "home"
MODE_AWAY = "away"
MODE_SLEEP = "sleep"
SYSTEM_MODES = {MODE_HOME, MODE_AWAY, MODE_SLEEP}
# Sleep is temporary and auto-reverts. HomeKit "Off" maps to sleep with this default.
DEFAULT_SLEEP_MINUTES = 120  # 2h
SLEEP_MINUTE_OPTIONS = {120, 1440, 4320}  # 2h / 24h / 72h
DEFAULT_SLEEP_REVERT = MODE_HOME

# Valve targets.
VALVE_OPEN = "open"
VALVE_CLOSED = "closed"

MANUFACTURER = "Moen"

# Flo alarm ids that actually mean WATER IS LEAKING (from the /api/v2/alarms catalog).
# Only these drive the moisture (leak) sensor — every other critical alarm ("Extended
# Water Use", "Fast Water Flow", "Unusual Activity", "Water System Shutoff", ...) is a
# real problem but is NOT a leak, and drives the generic alert sensor instead. Mapping
# every critical to a leak makes HomeKit announce "Leak detected" for a long shower.
LEAK_ALARM_IDS = {
    100,  # Leak Detected
    101,  # Water System Shutoff - Leak Detected
}

# Leak-natured alarms that Flo raises at *warning* severity. They're real conditions
# worth surfacing (a slow drip is exactly what leak detection exists for), but they are
# not "shut the water off now" events, so they drive the generic alert sensor rather
# than the HomeKit leak alarm.
LEAK_WARNING_ALARM_IDS = {
    28,  # Small Drip Detected
}

# Endpoint for the alarm catalog (id -> display name / severity), fetched once at setup.
ALARMS_PATH = "/alarms"
