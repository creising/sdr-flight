# SDR Flight Tracker — Design

**Date:** 2026-10-04
**Status:** Approved design (pre-implementation)
**Author:** Chris Reising (with Claude)

## 1. Purpose & Intent

A personal flight-radar web app. A NooElec RTL-SDR receives ADS-B on 1090 MHz;
on top of the decoded aircraft data we build three experiences:

1. **Live map** of planes currently overhead — the centerpiece.
2. **Rule-based alerts** pushed to the user's Apple devices (overhead pass, low
   pass, rare/interesting aircraft).
3. **Logging + stats dashboard**, including **history playback** of past
   flights on the map.

Success looks like: open the installed PWA on an iPhone/iPad/Mac over Tailscale,
see planes overhead live on a map; get a native push when something matches a
rule; browse stats of what's been seen; and scrub back through time to replay a
past pass.

This is a single-box hobby project for the user's own use — not a multi-user or
public service. Scope is deliberately bounded to one receiver and one owner.

## 2. Constraints & Key Decisions

- **Dev/deploy split (the dominant architectural driver).** Development happens
  on an Apple-Silicon Mac with **no SDR attached**. Deployment is to an older
  Intel Mac running **Ubuntu Server (x86_64)** with the NooElec SDR connected.
  The app must therefore run fully on recorded/synthetic data during
  development; only the data source differs between dev and prod.
- **Receive-only, legal.** The NooElec (NESDR / RTL-SDR) is a receive-only
  device. We only listen on 1090 MHz ADS-B. No transmitting.
- **Decoder is reused, not rebuilt.** `dump1090` handles RF→aircraft decoding.
  We never touch raw radio samples.
- **Stack:** Python backend (**FastAPI**) + lightweight vanilla HTML/JS/CSS
  frontend with no build step. Mature JS libraries loaded directly.
- **Serving:** the app binds `127.0.0.1` only; **`tailscale serve`** fronts it
  with HTTPS over the user's tailnet. Never directly exposed to the internet.
- **Notifications:** installable **PWA + Web Push (VAPID)**. On iOS 16.4+/macOS
  Safari, an added-to-Home-Screen PWA receives native notifications (Safari
  bridges Web Push to APNs). No Apple Developer account, no native app.
- **Storage:** **SQLite** (WAL mode) via SQLAlchemy. One box, hobby scale.
- **Process management:** **systemd** units, start on boot, restart on failure.
- **Offline-capable:** aircraft enrichment (hex → type/registration) uses a
  bundled offline table so the app works with no internet access.

## 3. Architecture Overview

```
┌─────────────┐   USB    ┌────────────┐  aircraft.json   ┌──────────────────┐   WSS/HTTPS   ┌──────────────┐
│ NooElec SDR │ ───────▶ │  dump1090  │ ───(poll ~1Hz)──▶│  flighttrack app │ ◀───────────▶ │ tailscale    │
│  (1090 MHz) │          │  (decoder) │                  │   (FastAPI)      │               │  serve (TLS) │
└─────────────┘          └────────────┘                  └────────┬─────────┘               └──────┬───────┘
                                                                   │                                 │
                                                          SQLite ◀─┤                           Apple devices
                                                        Web Push ◀─┘                        (PWA: map + push)
```

Two long-running processes on the Ubuntu box: `dump1090` (ships `aircraft.json`,
refreshed ~1 Hz) and our `flighttrack` FastAPI app that consumes it. The app
owns the map, alerts, logging, stats, and history playback.

### 3.1 Data-source abstraction (enables hardware-free dev)

```python
class AircraftSource(Protocol):
    async def poll(self) -> list[RawAircraft]: ...
```

Implementations, chosen by config (`source: dump1090 | replay | synthetic`):

- **`Dump1090Source`** — production. Reads dump1090's `aircraft.json` (via HTTP
  URL or file path).
- **`ReplaySource`** — development. Plays back a recorded `aircraft.json`
  capture on a loop at real-ish cadence.
- **`SyntheticSource`** — development/testing. Generates a few fake aircraft
  flying deterministic scripted paths over the configured receiver location —
  used to exercise geometry and alerts without waiting for a real pass, and as
  an integration-test driver.

Everything downstream (geometry, map, alerts, logging, history) is identical
regardless of source. A `flighttrack capture` helper saves a few minutes of real
`aircraft.json` from the Ubuntu box so the user can develop against genuine
local traffic on the Mac.

## 4. Backend Internals

### 4.1 Ingest & live state
An async task polls the active source ~1 Hz and maintains an **in-memory dict of
current aircraft keyed by ICAO hex**. For each aircraft with a position it
computes geometry relative to `receiver.{lat,lon,alt_m}`:

- **distance** (great-circle),
- **bearing** from the receiver,
- **elevation angle** (apparent height in the sky).

"Directly overhead" is defined by a high elevation angle combined with small
ground distance — not a naive radius. Aircraft not heard for N seconds are
dropped from the live set and their contact session is closed.

### 4.2 Alert engine
Rules are evaluated each tick against **state transitions**, not raw state, so
one event yields one alert (not one per second). Each rule carries a
cooldown/dedupe per aircraft, with a persisted "last alerted" guard so a restart
does not re-spam. Starting rule types (configured in YAML):

- **Overhead** — elevation angle ≥ X° (and/or within Y distance).
- **Low pass** — altitude ≤ X ft within Y distance.
- **Rare/interesting** — aircraft type/category/tail in a watchlist.
- **Closest-ever / farthest-ever** — optional "record broken" pings.

A match produces a `Notification` fanned out to Web Push subscribers and also to
any open map (in-UI banner + sound).

### 4.3 Logging
Every contact gets a **session** row; while in view the app periodically
snapshots track points. Snapshot interval and retention are configurable.

### 4.4 Enrichment
ICAO hex → aircraft type / registration via a **bundled offline lookup table**,
so enrichment and the rare-aircraft rules work without internet.

### 4.5 API surface (FastAPI)
- `GET /` → PWA map. `GET /stats` → stats page.
- `GET /manifest.webmanifest`, `GET /sw.js` → PWA assets.
- `WS /ws/live` → streams current aircraft state to the map.
- `GET /api/config` → receiver location + map defaults for the frontend.
- `GET /api/push/vapid-public-key`, `POST /api/push/subscribe` → Web Push.
- `GET /api/stats/...` → dashboard queries.
- `GET /api/history?from=…&to=…` → contacts + track points for playback.
- `GET /healthz`.

## 5. Data Model (SQLite, SQLAlchemy, WAL)

```
contacts            one row per continuous appearance of an aircraft
  id, icao, callsign, first_seen, last_seen,
  max_alt, min_alt, closest_km, closest_elevation_deg,
  aircraft_type, category, registration

positions           periodic track points (trails, low-pass review, playback)
  id, contact_id, ts, lat, lon, alt, speed, track, rssi

alerts              audit of fired alerts
  id, contact_id, rule, ts, payload

push_subscriptions  endpoint, keys, created_at, last_ok
```

Retention: a nightly prune removes `positions` older than the configured window
(default 30 days); `contacts` and `alerts` are kept longer. Denser position
snapshots make smoother playback but a larger DB — this is a tunable config
value.

## 6. Frontend & PWA

Vanilla JS + mature libraries, **no build step**; served as static files by
FastAPI. Dark theme by default (it's a radar), light available; map and charts
legible in both.

### 6.1 Live map (`/`) — centerpiece
- **Leaflet** + OpenStreetMap tiles, centered on the receiver with a
  "you are here" marker and optional range rings.
- SVG plane markers **rotated to heading**, color-coded by altitude; click for a
  popup (callsign, type, alt, speed, distance, elevation angle). Fading trails.
- Live updates over `WS /ws/live`, falling back to polling if the socket drops.
- A list of current contacts sorted by closeness; a top banner + sound when an
  alert fires while the page is open.

### 6.2 History playback ("play past flights")
- Shares the map rendering with live mode.
- **Time picker + timeline scrubber** with play/pause and speed (1×/5×/20×).
- Driven by `GET /api/history`; the frontend steps through time frames and
  interpolates between track points for smooth motion.
- Click a historical track for flight details; "replay this flight" is reachable
  from the stats page and the alerts feed.
- Distinct from the dev-only `ReplaySource` (which feeds the backend); this
  replays logged DB history to the user.

### 6.3 Stats (`/stats`)
- Tiles: planes seen today / all-time, closest-ever pass, farthest contact,
  highest/lowest, busiest hour.
- Simple charts (contacts per hour/day, top airlines, top aircraft types) and a
  recent-alerts feed. Built following the dataviz skill for light/dark legibility.

### 6.4 PWA bits (what makes Apple push work)
- `manifest.webmanifest` (name, icons, standalone display) → **Add to Home
  Screen** on iPhone/iPad, Dock on Mac.
- A **service worker** handling `push` → native notification, and
  `notificationclick` → open the map focused on that aircraft.
- First visit requests permission and registers the Web Push subscription.
  **On iOS this only works after the app is added to the Home Screen** — the UI
  guides the user through that.

## 7. Configuration

One `config.yaml` plus a `.env` for secrets:

- `source: dump1090 | replay | synthetic` and its settings (aircraft.json
  URL/path, replay file).
- `receiver: {lat, lon, alt_m}` — required for all geometry and map centering.
- `alerts:` rule list (overhead angle, low-pass thresholds, watchlists,
  cooldowns) and channels (web push / in-UI).
- `logging:` snapshot interval, retention days.
- `web_push:` VAPID public/private keys + contact email (in `.env`).

## 8. Deployment (Ubuntu box)

- `docs/DEPLOY.md` + a small `deploy.sh`/Makefile.
- Install `dump1090` (apt/prebuilt) feeding the SDR; create a Python venv;
  install the app; drop two **systemd** units (`dump1090`, `flighttrack`) that
  start on boot and restart on failure.
- `tailscale serve https / http://127.0.0.1:8000` exposes the app over the
  tailnet with HTTPS. App binds `127.0.0.1` only.
- `flighttrack capture` grabs a few minutes of real `aircraft.json` for use as a
  `ReplaySource` file during dev.
- A quick "is dump1090 actually seeing planes?" verification step.

## 9. Testing Strategy

- **TDD throughout.** Pure logic carries most of the risk and needs no hardware:
  - geometry (distance/bearing/elevation),
  - alert-rule transitions & cooldowns,
  - contact-session tracking,
  - history windowing/interpolation.
- **`SyntheticSource` as integration driver:** scripted planes fly a known path
  → assert the overhead alert fires exactly once, a contact row is written, and
  the history endpoint returns the track.
- **Frontend smoke test:** map loads, WebSocket renders a marker, service worker
  registers.
- **Hardware-only check (user):** real RF reception on the Ubuntu box, covered
  by a `DEPLOY.md` checklist. This is the one thing that cannot be verified on
  the dev Mac.

## 10. Explicit Non-Goals (YAGNI)

- No transmitting / RF output of any kind.
- No multi-user accounts, auth UI, or public internet exposure (Tailscale is the
  access boundary).
- No reimplementation of ADS-B decoding in Python.
- No MLAT / multi-receiver fusion.
- No feeding public aggregator networks (FlightAware/ADS-B Exchange) in v1 — can
  be added later.
- Alert rules start file-configured; a rule-editing UI is a later nicety.
