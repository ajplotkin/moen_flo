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


# --------------------------------------------------------------------------- #
# fresh_telemetry -- the guard against publishing a frozen snapshot
#
# The bug this exists for: telemetry.current served a reading 17.7 DAYS old that
# was indistinguishable from a live one. The block only advances while a client
# is subscribed (the coordinator's /presence/me beacon), so age is the ONLY
# evidence of validity.
# --------------------------------------------------------------------------- #

from datetime import datetime, timedelta, timezone  # noqa: E402

NOW = datetime(2026, 9, 8, 16, 0, 0, tzinfo=timezone.utc)


def _dev_at(updated, **fields):
    cur = {"psi": 48.6, "gpm": 0.3}
    cur.update(fields)
    if updated is not None:
        cur["updated"] = updated
    return {"telemetry": {"current": cur}}


def _iso(delta_s):
    return (NOW - timedelta(seconds=delta_s)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_fresh_telemetry_passes_a_recent_reading():
    assert tel.fresh_telemetry(_dev_at(_iso(20)), now=NOW).get("psi") == 48.6


def test_fresh_telemetry_suppresses_the_17_day_fossil():
    """The actual observed failure: 17.7 days old, values that look perfectly valid."""
    assert tel.fresh_telemetry(_dev_at(_iso(17.7 * 86400)), now=NOW) == {}


def test_fresh_telemetry_boundary():
    # Just inside passes, just outside is suppressed -- an implementation using >= or a
    # wrong comparison direction fails one of these.
    assert tel.fresh_telemetry(_dev_at(_iso(179)), now=NOW) != {}
    assert tel.fresh_telemetry(_dev_at(_iso(181)), now=NOW) == {}


def test_fresh_telemetry_fails_closed_without_a_timestamp():
    """No `updated` field = no evidence of freshness. Must NOT pass through."""
    assert tel.fresh_telemetry(_dev_at(None), now=NOW) == {}
    assert tel.fresh_telemetry({}, now=NOW) == {}
    assert tel.fresh_telemetry({"telemetry": {"current": {}}}, now=NOW) == {}


def test_fresh_telemetry_fails_closed_on_unparsable_timestamp():
    for bad in ("not-a-date", "", 12345, None, "2026-13-45T99:99:99Z"):
        assert tel.fresh_telemetry(_dev_at(bad), now=NOW) == {}


def test_fresh_telemetry_rejects_a_far_future_timestamp():
    """Clock skew the wrong way is not freshness either."""
    future = (NOW + timedelta(seconds=4000)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert tel.fresh_telemetry(_dev_at(future), now=NOW) == {}


def test_telemetry_age_handles_offset_and_naive_forms():
    assert tel.telemetry_age_s(_dev_at("2026-09-08T15:59:00+00:00"), now=NOW) == 60.0
    # Naive stamps are assumed UTC rather than crashing on the subtraction.
    assert tel.telemetry_age_s(_dev_at("2026-09-08T15:59:00"), now=NOW) == 60.0
    assert tel.telemetry_age_s(_dev_at(None), now=NOW) is None
