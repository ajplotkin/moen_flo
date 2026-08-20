# Moen Flo (SSO) — Home Assistant integration

Native Home Assistant integration for the **Moen / Flo whole-home water shutoff
valve**, authenticating the way the current Moen app does (Moen SSO / Cognito).

## Why this exists

Moen migrated Flo accounts to the **Smart Water Network** identity, and the current Moen
app authenticates against Moen SSO (Cognito). This integration does the same: it logs in
with your Moen email + password against `oauth2/token` and uses the Cognito token for all
Flo calls.

> **Corrected 2026-08-20.** This section previously said `api-gw.meetflo.com` **rejects**
> the legacy `api/v1/users/auth` token with a `401`, and that the built-in Home Assistant
> `flo` integration therefore fails for migrated accounts. **That is not true today.**
> Re-tested on 2026-08-20 against a migrated account: `POST /api/v1/users/auth` returns
> 200 and its token is accepted by `api-gw` — 200 on `GET /api/v2/users/{id}` and
> `GET /api/v2/devices/{id}`. Whether something changed at Moen or the credential state
> differed when this was first written, I can't say. If the stock `flo` integration fails
> for you, see [home-assistant/core#171600](https://github.com/home-assistant/core/issues/171600) —
> the reports there mostly resolve to a locked account or a password reset after migration.

So this integration is not a workaround for a broken endpoint. It uses SSO because that is
what the current app uses and the flow most likely to outlive v1.

The valve is controlled through the Flo v2 data plane, which is very much alive:
`POST /api/v2/devices/<id> {"valve":{"target":"open"|"closed"}}`.

## Features

Creates one device (**Basement Flo**, or your device's nickname) with:

| Entity | Type | Notes |
|---|---|---|
| Valve | `valve` | Open / close the shutoff valve |
| Mode | `alarm_control_panel` | Home → armed_home, Away → armed_away, **Off → Sleep** (temporary 2h pause, auto-reverts) |
| Leak | `binary_sensor` (moisture) | On **only** for real leak alarms (Flo ids 100/101) → HomeKit LeakSensor |
| Water alert | `binary_sensor` (problem) | Other pending critical alarms (Extended Water Use, Fast Flow, Unusual Activity, Shutoff…) plus leak-natured warnings (Small Drip). Not bridged to HomeKit — HA renders unknown classes as Occupancy. |
| Connectivity | `binary_sensor` | Device online/offline |
| Water flow | `sensor` | gal/min |
| Water pressure | `sensor` | psi |
| Water temperature | `sensor` | °F (diagnostic; reads oddly at zero flow) |
| Wi-Fi signal | `sensor` | dBm (diagnostic, disabled by default) |
| Water used today | `sensor` | gallons |
| Alarm | `event` | Fires once per **newly raised** alarm — types `leak` / `critical` / `warning` / `info`, with the alarm id, name and severity in the payload. See below. |

Cloud-polled every 30s. Token auto-refreshes; a changed password triggers HA's reauth flow.

### Why there's an `event` entity as well as the binary sensors

The binary sensors are *level*-triggered over Flo's pending-alarm queue: they answer "is
something wrong right now?". That queue only drains when alarms are dismissed in the Flo
app, so an outstanding alarm latches them `on` indefinitely — and while latched, a brand
new alarm produces **no state change at all**, so nothing notifies.

This is not hypothetical. With four alarms pending since 2026-07-28, a real "Water System
Shutoff" on 2026-07-31 raised no Home Assistant signal whatsoever (the valve closed and
reopened, confirmed in history) while the Flo app notified normally — its cloud pushes
each occurrence independently of any state.

The `event` entity reports *occurrences* instead, firing whenever an alarm appears that
wasn't there before or whose count changes, regardless of what else is outstanding.

**It does not reach HomeKit.** Home Assistant's HomeKit bridge has no mapping for the
`event` domain — event entities are bridged only as linked doorbell/motion sensors on
cameras and locks, so a standalone one is silently skipped. Use it for HA automations; a
HomeKit announcement still needs an automation or a momentary binary sensor.

Known limitation: because this is polled every 30s, an alarm that clears and re-fires at
the *identical* count inside one polling window is indistinguishable from no change.

## Install

### HACS (custom repository)
1. HACS → ⋮ → **Custom repositories** → add `https://github.com/ajplotkin/moen_flo`, category **Integration**.
2. Install **Moen Flo (SSO)**, restart Home Assistant.

### Manual
Copy `custom_components/moen_flo/` into your HA `config/custom_components/` and restart.

## Configure

**Settings → Devices & Services → Add Integration → “Moen Flo (SSO)”** → your Moen
account **email + password**.

If your account is protected by an email one-time code, login may return a challenge
instead of a token — open an issue and we'll add the OTP step.

## HomeKit / Apple Home

Expose the entities via HA's HomeKit bridge as usual. Note that HA maps each entity to
its own accessory, so the valve and the mode picker appear as **two tiles** (the old
Homebridge plugin bundled them into one — HA's bridge can't). If you only want a simple
toggle, expose just the valve.

## Safety

This is an **unofficial** integration. Do **not** rely on it as your only leak
protection — the Moen app's own alerts and the Flo hardware's automatic shutoff are the
real safeguards, independent of Home Assistant.

## Credits

Built on findings from the community integrations
[`bachya/aioflo`](https://github.com/bachya/aioflo),
[`alexbbt/ha-moen-smart-water`](https://github.com/alexbbt/ha-moen-smart-water),
[`mattatcha/moen-smart-water-hass`](https://github.com/mattatcha/moen-smart-water-hass),
and [`patrickjcash/ha-moen-flo`](https://github.com/patrickjcash/ha-moen-flo).

## License

MIT
