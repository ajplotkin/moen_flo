"""Constants for the Moen Flo (SSO) integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "moen_flo"

# Moen SSO (Cognito) auth — the flow the current Moen Smartwater app uses.
# Observed from the app, not documented, so both values can change without notice.
OAUTH_URL = "https://4j1gkf0vji.execute-api.us-east-2.amazonaws.com/prod/v1/oauth2/token"
OAUTH_CLIENT_ID = "6qn9pep31dglq6ed4fvlq6rp5t"

# Flo data/control plane. GETs accept EITHER auth, but the HEADER FORM DIFFERS and
# is not interchangeable (measured 2026-08-20 on GET /api/v2/users/{id}):
#     SSO access token   -> "Authorization: Bearer <tok>"   200
#     legacy v1 token    -> "Authorization: <tok>"          200
#     legacy v1 as Bearer                                   401
# Writes were NOT tested with a legacy token. This client sends the SSO one.
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
