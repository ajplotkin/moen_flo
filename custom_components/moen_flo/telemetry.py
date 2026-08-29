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
