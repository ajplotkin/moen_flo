"""Water-temperature plausibility filter.

A Flo valve with no temperature sensor does not omit `tempF` -- it reports a constant
placeholder. On the unit this was written against the recorder held 70 rows over nine
days with exactly two distinct values, 225 and "unavailable", while flow logged 19
distinct values and pressure 18 across the same window. The device is alive; it simply
never measures temperature.

These tests exist to stop the filter regressing to the raw passthrough it replaced. A
naive `telemetry(device).get("tempF")` fails the first two cases.
"""

import pytest

from conftest import load_telemetry

tel = load_telemetry()


def _dev(temp):
    return {"telemetry": {"current": {"tempF": temp}}}


@pytest.mark.parametrize("value", [225, 225.0, "225", 212, 212.0, 400])
def test_placeholder_and_above_boiling_are_suppressed(value):
    """At or above boiling is not reachable in a supply line -- treat as no reading."""
    assert tel.water_temp_f(_dev(value)) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [(68, 68.0), (54.5, 54.5), ("70", 70.0), (211.9, 211.9), (0, 0.0), (-4, -4.0)],
)
def test_real_readings_pass_through_as_float(value, expected):
    """Anything physically possible is returned unchanged, coerced to float."""
    assert tel.water_temp_f(_dev(value)) == pytest.approx(expected)


@pytest.mark.parametrize(
    "device",
    [
        {},                                        # no telemetry at all
        {"telemetry": None},                       # explicit null
        {"telemetry": {}},                         # no current block
        {"telemetry": {"current": None}},          # null current
        {"telemetry": {"current": {}}},            # no tempF key
        {"telemetry": {"current": {"tempF": None}}},
        {"telemetry": {"current": {"tempF": "n/a"}}},   # unparseable
        {"telemetry": {"current": {"tempF": ""}}},
    ],
)
def test_missing_or_unparseable_is_none_not_a_crash(device):
    assert tel.water_temp_f(device) is None


def test_boundary_is_inclusive():
    """Exactly 212 is suppressed; a hair under is kept. Pins >= rather than >."""
    assert tel.water_temp_f(_dev(tel.IMPLAUSIBLE_WATER_TEMP_F)) is None
    assert tel.water_temp_f(_dev(tel.IMPLAUSIBLE_WATER_TEMP_F - 0.1)) is not None


def test_telemetry_helper_still_returns_the_current_block():
    """Other sensors (flow, pressure) depend on this and must be unaffected."""
    assert tel.telemetry(_dev(68)) == {"tempF": 68}
    assert tel.telemetry({}) == {}


# --------------------------------------------------------------------------- #
# latest_metric -- /water/metrics hourly buckets
#
# These exist because the instantaneous psi/gpm fields are unusable: measured
# 2026-09-08, telemetry.current only advances while the Moen app is open and
# froze four minutes after it closed, having previously served a value 17.7 days
# old while water was used nightly.
# --------------------------------------------------------------------------- #

def _payload(*items):
    return {"items": list(items)}


def test_latest_metric_picks_the_newest_bucket():
    # Deliberately NOT in chronological order: a first-element or last-element
    # implementation passes an ordered fixture without ever comparing timestamps.
    p = _payload(
        {"time": "2026-09-08T01:00:00-04:00", "averagePsi": 40.0},
        {"time": "2026-09-08T03:00:00-04:00", "averagePsi": 48.7},
        {"time": "2026-09-08T02:00:00-04:00", "averagePsi": 44.4},
    )
    assert tel.latest_metric(p, "averagePsi") == 48.7


def test_latest_metric_skips_null_current_hour():
    # Just after the hour the newest bucket exists but has no sample yet; falling
    # back to the previous hour is the whole point.
    p = _payload(
        {"time": "2026-09-08T02:00:00-04:00", "averagePsi": 44.4},
        {"time": "2026-09-08T03:00:00-04:00", "averagePsi": None},
    )
    assert tel.latest_metric(p, "averagePsi") == 44.4


def test_latest_metric_reads_the_requested_key_only():
    p = _payload({"time": "2026-09-08T03:00:00-04:00", "averagePsi": 48.7, "averageGpm": 0.166})
    assert tel.latest_metric(p, "averageGpm") == 0.166


def test_latest_metric_empty_and_missing():
    assert tel.latest_metric(None, "averagePsi") is None
    assert tel.latest_metric({}, "averagePsi") is None
    assert tel.latest_metric(_payload(), "averagePsi") is None
    assert tel.latest_metric(_payload({"time": "x"}), "averagePsi") is None


def test_latest_metric_ignores_malformed_rows():
    p = _payload(
        "not a dict",
        {"averagePsi": 99.0},                                    # no time
        {"time": 12345, "averagePsi": 98.0},                     # non-str time
        {"time": "2026-09-08T01:00:00-04:00", "averagePsi": "48.7"},  # string value
        {"time": "2026-09-08T02:00:00-04:00", "averagePsi": 44.4},
    )
    assert tel.latest_metric(p, "averagePsi") == 44.4


def test_latest_metric_returns_float_for_int_input():
    p = _payload({"time": "2026-09-08T03:00:00-04:00", "averagePsi": 48})
    v = tel.latest_metric(p, "averagePsi")
    assert v == 48.0 and isinstance(v, float)
