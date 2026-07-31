"""Shared parsing for Flo's pending-alarm payload.

Extracted so the binary sensors (which report *state* — "is something wrong right now?")
and the event entity (which reports *occurrences* — "a new alarm was just raised") agree
on exactly what an alarm is, what its severity is, and how it's described. If those two
views disagreed the divergence would be silent, and one of them would be wrong at the
moment it mattered most.
"""

from __future__ import annotations

from typing import Any


def as_int(value: Any, default: int | None = None) -> int | None:
    """Coerce an id/count to int. The API sends ints, but a string would otherwise
    silently break `id in LEAK_ALARM_IDS` — an unobservable permanent false negative."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def pending(device: dict[str, Any]) -> dict[str, Any]:
    return (device.get("notifications") or {}).get("pending") or {}


def pending_alarms(device: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalized pending alarms: [{"id": int|None, "severity": str|None, "count": int}]."""
    raw = pending(device).get("alarmCount")
    if not isinstance(raw, list):
        return []
    alarms: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        alarms.append(
            {
                "id": as_int(entry.get("id")),
                "severity": entry.get("severity"),
                # An entry present in the pending list is itself the signal; default to 1
                # rather than 0 so an unexpected shape errs toward alerting.
                "count": as_int(entry.get("count"), 1) or 0,
            }
        )
    return alarms


def severity_of(
    alarm: dict[str, Any], catalog: dict[int, dict[str, Any]]
) -> str | None:
    """Per-entry severity, falling back to the catalog so every consumer agrees on what
    'critical' means."""
    entry = catalog.get(alarm.get("id")) or {}
    return alarm.get("severity") or entry.get("severity")


def describe(
    alarm: dict[str, Any], catalog: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    """Human-readable form of an alarm, used for both attributes and event payloads."""
    entry = catalog.get(alarm.get("id")) or {}
    return {
        "id": alarm.get("id"),
        "name": entry.get("name"),
        "severity": severity_of(alarm, catalog),
        "count": alarm.get("count"),
    }
