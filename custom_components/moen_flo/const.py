"""Constants for the Moen Flo (SSO) integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "moen_flo"

# Moen SSO (Cognito) auth — the token that api-gw.meetflo.com/v2 accepts.
OAUTH_URL = "https://4j1gkf0vji.execute-api.us-east-2.amazonaws.com/prod/v1/oauth2/token"
OAUTH_CLIENT_ID = "6qn9pep31dglq6ed4fvlq6rp5t"

# Legacy Flo data/control plane (still live; now Moen-SSO-authed).
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
