"""Telemetry helpers.

Deliberately free of Home Assistant imports so the logic can be unit-tested standalone,
the same way `api` and `const` are (see tests/conftest.py).
"""

from __future__ import annotations

from typing import Any

# Water in a domestic supply line cannot reach boiling at atmospheric pressure, so any
# reading at or above this is a sentinel rather than a measurement. Used instead of
# hard-coding one vendor placeholder, which would only cover the value we happen to
# have seen.
IMPLAUSIBLE_WATER_TEMP_F = 212.0


def telemetry(device: dict[str, Any]) -> dict[str, Any]:
    """The device's current telemetry block, or an empty dict."""
    return ((device.get("telemetry") or {}).get("current") or {})


def water_temp_f(device: dict[str, Any]) -> float | None:
    """Water temperature in F, or None when the device is not really measuring it.

    Some Flo shutoff valves have no water-temperature sensor and, instead of omitting
    the field, report a constant placeholder. On the unit this was written against that
    placeholder is 225 F: the recorder held 70 rows across nine days with exactly two
    distinct values, 225 and "unavailable", while flow logged 19 distinct values and
    pressure 18 over the same window. So the device reports live data but never a
    temperature.

    Returning None makes the entity unavailable, which is honest, instead of publishing
    a fixed number that looks like a reading and silently poisons history and any
    automation keyed on it.
    """
    # No `is None` guard: float(None) raises TypeError, which the except already
    # covers. A separate check looks load-bearing but is dead -- mutation-tested.
    try:
        temp = float(telemetry(device).get("tempF"))
    except (TypeError, ValueError):
        return None
    if temp >= IMPLAUSIBLE_WATER_TEMP_F:
        return None
    return temp

# Instantaneous telemetry (`telemetry.current`) is only produced while a client is actively
# watching the device -- opening the Moen app starts it and it stops roughly four minutes
# after the app closes. Measured 2026-09-08: it ran 01:20-01:24 while the app was open, then
# froze at 01:23:58 and did not move again. Polling the API does NOT wake it, and neither
# does water flowing: the recorder held a single frozen psi/gpm pair for TEN DAYS while water
# was used every night, and the value on the wire was 17.7 days old.
#
# So the hourly aggregates from /water/metrics are the only continuously-updating source of
# pressure and flow. They are averages rather than instantaneous readings -- the API rejects
# every interval finer than 1h ("Invalid property values") -- but they are real and they keep
# updating with nothing watching, which the instantaneous pair does not.
def latest_metric(payload: dict[str, Any] | None, key: str) -> float | None:
    """Newest non-null value for `key` from a /water/metrics payload, or None.

    The newest bucket is the current, partially-elapsed hour, which is what makes this
    usable as a live-ish reading. Buckets are returned in order in practice, but this
    picks by timestamp rather than trusting position -- and skips buckets whose value is
    null, which happens for the current hour before the first sample lands in it.
    """
    items = (payload or {}).get("items") or []
    best_time: str | None = None
    best_value: float | None = None
    for item in items:
        if not isinstance(item, dict):
            continue
        value = item.get(key)
        if not isinstance(value, (int, float)):
            continue
        when = item.get("time")
        if not isinstance(when, str):
            continue
        # ISO-8601 with a fixed offset sorts correctly as text within one timezone, which
        # is all these are -- the API echoes a single `tz` for the whole response.
        if best_time is None or when > best_time:
            best_time, best_value = when, float(value)
    return best_value
