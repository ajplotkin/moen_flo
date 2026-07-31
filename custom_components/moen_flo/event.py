"""Event entity for Moen Flo (SSO): fires once per newly-raised alarm.

The binary sensors are *level*-triggered over Flo's pending-alarm queue — they answer
"is something wrong right now?". That queue only drains when alarms are dismissed in the
Flo app, so an outstanding alarm latches them `on` indefinitely. While latched, a brand
new alarm produces no state change at all: no edge for an automation to trigger on.

Observed in the field: four alarms pending since 2026-07-28 meant a real "Water System
Shutoff" on 2026-07-31 raised no HA signal whatsoever, while the Flo app notified
normally (its cloud pushes each occurrence independently of any state).

This entity closes that gap by reporting *occurrences* instead of state.

IMPORTANT — this entity does NOT reach HomeKit. HA's HomeKit bridge has no mapping for
the `event` domain; event entities are bridged only as linked doorbell/motion sensors on
cameras and locks, so a standalone one is silently skipped. Getting an alarm to HomeKit
still requires either an HA automation acting on this entity, or a momentary binary
sensor. This entity is the HA-native signal, not a HomeKit fix.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MoenFloConfigEntry
from .alarms import describe, pending_alarms, severity_of
from .const import LEAK_ALARM_IDS
from .entity import MoenFloEntity

# An event entity declares its types up front, so these are severity buckets rather than
# per-alarm ids: the Flo catalog has dozens of ids and is fetched at runtime, so it can't
# be enumerated statically. The specific id and name ride along in the event attributes.
EVENT_LEAK = "leak"
EVENT_CRITICAL = "critical"
EVENT_WARNING = "warning"
EVENT_INFO = "info"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MoenFloConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([MoenFloAlarmEvent(entry.runtime_data)])


class MoenFloAlarmEvent(MoenFloEntity, EventEntity):
    """Fires on each newly-raised Flo alarm, even while older ones remain pending."""

    _attr_name = "Alarm"
    _attr_event_types = [EVENT_LEAK, EVENT_CRITICAL, EVENT_WARNING, EVENT_INFO]

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "alarm_event")
        # id -> count at the previous poll. `None` means "no baseline yet".
        self._seen: dict[int | None, int] | None = None

    @property
    def available(self) -> bool:
        """Follow the coordinator, not the device's own connectivity.

        Alarms originate from Flo's cloud, which can raise them *about* a device that is
        itself offline. Inheriting the base class's `isConnected` gate would render this
        entity `unavailable` at exactly those moments, so a fired event would be
        invisible until the device reconnected — and would then surface late with a
        stale timestamp.
        """
        return self.coordinator.last_update_success

    def _event_type(self, alarm: dict[str, Any]) -> str:
        """Most specific bucket wins, mirroring the binary sensors: a leak is reported as
        a leak rather than merely as another critical."""
        if alarm.get("id") in LEAK_ALARM_IDS:
            return EVENT_LEAK
        severity = severity_of(alarm, self.coordinator.alarm_catalog)
        if severity == "critical":
            return EVENT_CRITICAL
        if severity == "warning":
            return EVENT_WARNING
        return EVENT_INFO

    def _snapshot(self) -> dict[int | None, int]:
        return {a["id"]: a["count"] for a in pending_alarms(self._device)}

    async def async_added_to_hass(self) -> None:
        """Seed the baseline from data we already have, before the first callback.

        `async_config_entry_first_refresh` has already run by this point, so the pending
        queue is known. Waiting for the first coordinator callback instead would leave a
        poll-interval-wide dead zone after every restart, during which a genuinely new
        alarm would be absorbed into the baseline and never fire.
        """
        if self._seen is None and self.coordinator.data:
            self._seen = self._snapshot()
        await super().async_added_to_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        alarms = pending_alarms(self._device)
        previous = self._seen

        # NOTE: an empty alarm list is treated as "the queue drained", never as "this
        # payload was malformed", and the baseline is always updated.
        #
        # It is tempting to guard against a transient bad payload by keeping the old
        # baseline when `alarmCount` isn't a list, but the two cases are not reliably
        # distinguishable: `pending()` always yields a dict, so if Flo represents an
        # empty queue by *omitting* `alarmCount` rather than sending `[]`, that guard
        # would freeze the baseline on every empty poll — permanently. A later alarm
        # refiring at the same count as the frozen snapshot would then compare equal and
        # never fire, silently, forever. Count-1 alarms are the common case, so that is
        # the likely outcome rather than a corner case.
        #
        # The cost of not guarding is bounded and points the safe way: a malformed poll
        # resets the baseline, so the next good poll replays what's outstanding as new
        # events. Spurious alerts are recoverable; a missed shutoff is not. This matches
        # the bias already documented in alarms.py.
        current = {a["id"]: a["count"] for a in alarms}
        self._seen = current

        if previous is None:
            # No baseline (data was absent at add time). Seed silently rather than
            # replaying the whole backlog as fresh alarms.
            super()._handle_coordinator_update()
            return

        for alarm in alarms:
            count = alarm["count"] or 0
            if count <= 0:
                continue
            before = previous.get(alarm["id"])
            # Fire on ANY change to a still-present alarm, not just a rising count.
            # A falling count is ambiguous: "2 -> 1" is either one dismissal, or a full
            # dismissal followed by a fresh occurrence inside one poll window. Those are
            # indistinguishable from the payload, and that window is exactly when an
            # incident is live and the user is in the app dismissing. Consistent with
            # alarms.py erring toward alerting, a duplicate event is preferred over a
            # missed shutoff. Cost: partially dismissing a queue fires one extra event.
            if before is None or count != before:
                self._trigger_event(
                    self._event_type(alarm),
                    describe(alarm, self.coordinator.alarm_catalog),
                )
                # Written per alarm: an event entity holds only its most recent event, so
                # firing several in one poll without writing between them would collapse
                # them into just the last one.
                self.async_write_ha_state()

        super()._handle_coordinator_update()
