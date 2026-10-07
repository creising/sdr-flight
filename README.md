# Overhead — SDR Flight Tracker

A self-hosted, real-time **ADS-B flight tracker**. Plug a cheap RTL-SDR dongle into
a Raspberry Pi or Linux box, point it at the sky, and watch the aircraft overhead on
a live "glass-cockpit" map — with range rings, altitude-coded markers, trails,
airline/route lookups, airframe photos, and a stats/history view.

It's a thin, focused app that sits **on top of [dump1090](https://github.com/flightaware/dump1090)**:
dump1090 does the radio decoding, and Overhead turns its output into a live map, a
contact log, and daily stats.

> No hardware? It ships with a **synthetic** data source, so you can run the whole UI
> on your laptop with fake traffic orbiting your location — no SDR required.

Built with FastAPI + a dependency-free vanilla-JS Leaflet frontend (no build step).
All Python tooling uses [uv](https://docs.astral.sh/uv/).

---

## Table of contents

- [How it works](#how-it-works)
- [Data sources](#data-sources)
- [External APIs & enrichment](#external-apis--enrichment)
- [Quick start (no hardware)](#quick-start-no-hardware)
- [Full deployment (SDR + dump1090)](#full-deployment-sdr--dump1090)
- [Configuration reference](#configuration-reference)
- [Environment variables](#environment-variables)
- [HTTP & WebSocket API](#http--websocket-api)
- [Testing](#testing)
- [Project layout](#project-layout)
- [License](#license)

---

## How it works

```
   1090 MHz                                                   browser
   ADS-B RF        ┌───────────┐   aircraft.json   ┌──────────────┐   WebSocket   ┌─────────┐
  ((( ✈ )))  ───▶  │  RTL-SDR  │ ─▶ dump1090   ─────▶│  Overhead    │ ──/ws/live──▶ │ Leaflet │
                   │  dongle   │   (decoder)   poll  │  (FastAPI)   │               │  map/UI │
                   └───────────┘   ~1 Hz        1 Hz └──────┬───────┘               └─────────┘
                                                           │  snapshots
                                                           ▼
                                                   ┌───────────────┐   stats /
                                                   │ SQLite store  │   history
                                                   └───────────────┘
```

1. An **RTL-SDR** dongle receives the 1090 MHz ADS-B signals that aircraft broadcast.
2. **dump1090** decodes them and continuously writes an `aircraft.json` snapshot
   (position, altitude, callsign, speed, squawk, signal strength, …) roughly once a second.
3. **Overhead polls `aircraft.json`** (either over HTTP from dump1090's web server, or by
   reading the file directly on the same box), computes each aircraft's range / bearing /
   elevation relative to *your* receiver, ages out stale contacts, and **broadcasts the live
   state to connected browsers over a WebSocket** (`/ws/live`).
4. In parallel it **records periodic snapshots to SQLite** so the `/stats` page can show
   contacts-per-hour, top airlines, and a scrubbable history timeline.
5. On demand, it **enriches** a selected aircraft with route/airline info, a local FAA
   registry lookup, and an airframe photo (see [External APIs](#external-apis--enrichment)).

The integration point with dump1090 is deliberately just its `aircraft.json` — the same
file the FlightAware / tar1090 / SkyAware map stack consumes — so Overhead works with
`dump1090`, `dump1090-fa`, `dump1090-mutability`, or `readsb` without modification.

---

## Data sources

Set `source:` in `config.yaml` (or `FLIGHTTRACK_SOURCE` in the environment):

| `source`    | What it does                                                                 | Needs hardware? |
|-------------|------------------------------------------------------------------------------|-----------------|
| `synthetic` | Generates fake aircraft orbiting your receiver. Great for dev/demo. **Default.** | No           |
| `replay`    | Replays a captured `aircraft.json` JSONL file at its recorded cadence.        | No              |
| `dump1090`  | Live traffic from a real SDR via dump1090's `aircraft.json`.                  | **Yes**         |

For `dump1090`, the `dump1090.url` can be:

- an **HTTP URL** — e.g. `http://127.0.0.1:8080/data/aircraft.json` (dump1090's web server), or
- a **local file path** — e.g. `/run/dump1090-fa/aircraft.json` (read directly, no web
  server needed; ideal for a single-box deploy). A `file://` URL works too.

---

## External APIs & enrichment

All enrichment is **optional** and **degrades gracefully** — aircraft still track, get
positioned, and log without any of it. Each is independent:

| Source | Provides | Key required? | Cost | Notes |
|--------|----------|---------------|------|-------|
| **[FlightAware AeroAPI](https://www.flightaware.com/aeroapi/)** | Live route: origin/destination airports, airline, aircraft type, registration — looked up by callsign | **Yes** — `FLIGHTAWARE_API_KEY` | Paid (metered; has a free monthly credit allotment) | Without a key, route lookups are simply disabled. Results are cached in SQLite (6 h for known routes, 15 min otherwise). |
| **[FAA Releasable Aircraft Database](https://www.faa.gov/licenses_certificates/aircraft_certification/aircraft_registry/releasable_aircraft_download)** | Offline hex → make / model / year / N-number | No | Free | US registrations only. Downloaded once and built into a local SQLite file via `scripts/import_faa.py` (~317k aircraft). Instant, offline lookups. |
| **[planespotters.net](https://www.planespotters.net/photo/api)** | Airframe photo (thumbnail + credit) by ICAO hex | No (but a UA is) | Free (attribution required) | Set `PLANESPOTTERS_UA` to a descriptive User-Agent **that includes a contact URL or email** — generic/contactless UAs get 403'd. Off by default-ish; coverage is spotty for GA/regional traffic. Photos cached 30 days. |

> **In short:** the only paid/keyed dependency is FlightAware AeroAPI for route lookups.
> Everything else (live tracking, map, stats, FAA metadata, photos) needs no paid key.

---

## Quick start (no hardware)

Runs the full UI on your laptop with synthetic traffic.

```bash
# 1. Create a venv (uv fetches CPython if you don't have it)
uv venv --python 3.12 .venv

# 2. Install the app + dev extras
uv pip install -e ".[dev]"

# 3. Create your config and set your receiver location
cp config.example.yaml config.yaml      # edit receiver: lat/lon/alt_m
#   source: synthetic  is the default

# 4. Run it
uv run flighttrack                       # serves http://127.0.0.1:8000
```

Open **http://127.0.0.1:8000** — synthetic planes orbit your location. The stats page
is at **/stats**.

### Optional: "visible from here" indicator

Aircraft that are above your **local terrain skyline** (not just a flat horizon) can be
highlighted with a glowing halo on the map and a `VISIBLE` badge in the list. Build a
one-time terrain horizon profile for your receiver, then point `config.yaml` at it:

```bash
uv run python scripts/build_horizon.py     # reads receiver lat/lon from config.yaml,
                                            # downloads SRTM tiles, writes data/horizon.json
# then in config.yaml:
#   horizon:
#     path: data/horizon.json
```

The profile is specific to your receiver location — **regenerate it whenever you change the
receiver coordinates**. Without a profile the feature is simply off.

---

## Full deployment (SDR + dump1090)

This is the "run it for real on your own box" path. Target is a Linux machine
(Raspberry Pi OS / Debian / Ubuntu) with an SDR dongle.

### 1. Hardware

- An **RTL-SDR** dongle (any RTL2832U-based receiver; an R820T/R860 tuner is typical).
- A **1090 MHz antenna** (even the stock whip works; a tuned 1090 MHz antenna + LNA/filter
  greatly improves range).

### 2. Install and run dump1090

Use **[dump1090-fa](https://github.com/flightaware/dump1090)** (FlightAware's fork) or any
compatible build. Typical steps:

```bash
# Blacklist the kernel DVB-T driver so it doesn't grab the dongle
echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/blacklist-rtlsdr.conf
sudo reboot

# Install dump1090-fa (from the FlightAware apt repo or built from source), then run it
# with your receiver's coordinates. It will write aircraft.json ~1 Hz, e.g.:
#   file:  /run/dump1090-fa/aircraft.json
#   http:  http://<host>:8080/data/aircraft.json
```

Confirm it's decoding real aircraft before wiring up Overhead (check the SkyAware map at
`http://<host>:8080`, or `cat /run/dump1090-fa/aircraft.json`).

### 3. Install Overhead

```bash
git clone https://github.com/creising/sdr-flight.git
cd sdr-flight
uv venv --python 3.12 .venv
uv pip install -e .

cp config.example.yaml config.yaml
```

Edit `config.yaml`:

```yaml
source: dump1090
receiver:
  lat: 40.0150          # YOUR antenna location — used for all geometry + map center
  lon: -105.2705
  alt_m: 1624
dump1090:
  url: /run/dump1090-fa/aircraft.json   # local file (same box) — or an http:// URL
host: 0.0.0.0           # bind on all interfaces so you can reach it from other devices
port: 8000
```

### 4. (Optional) Build the FAA registry for aircraft metadata

```bash
uv run python scripts/import_faa.py data/faa.db   # downloads + builds ~317k-row SQLite
```

Re-run periodically (the FAA refreshes roughly weekly) — a cron job or systemd timer works.

### 5. (Optional) Enrichment keys

Put secrets in a `.env` file (gitignored) and load them into the process environment
(see [Environment variables](#environment-variables)):

```bash
FLIGHTAWARE_API_KEY=your-aeroapi-key
PLANESPOTTERS_UA=overhead/1.0 (https://example.com; you@example.com)
```

### 6. Run under systemd

Create a service so it starts on boot and restarts on failure:

```ini
# /etc/systemd/system/flighttrack.service
[Unit]
Description=Overhead flight tracker
After=network-online.target dump1090-fa.service
Wants=network-online.target

[Service]
User=youruser
WorkingDirectory=/home/youruser/sdr-flight
EnvironmentFile=/home/youruser/sdr-flight/.env     # loads FLIGHTAWARE_API_KEY etc.
ExecStart=/home/youruser/sdr-flight/.venv/bin/flighttrack
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now flighttrack
journalctl -u flighttrack -f
```

### 7. Remote access

`host: 0.0.0.0` makes it reachable on your LAN at `http://<box-ip>:8000`.

**The app has no built-in authentication and the map reveals your receiver's location**,
so think before exposing it to the public internet. Good options:

- **LAN only** — leave it on your local network.
- **[Tailscale](https://tailscale.com/)** — `tailscale serve 8000` gives a private HTTPS URL
  reachable only by *your* devices (no auth needed, nothing public).
- **Public** — `tailscale funnel 8000`, or a reverse proxy (Caddy/nginx) with TLS. If you go
  public, **add authentication first** (a reverse-proxy basic-auth is the simplest), since
  the UI exposes live traffic, raw ADS-B data, and your approximate location.

---

## Configuration reference

`config.yaml` (copy from `config.example.yaml`). Every key can also be set via environment
variables prefixed with `FLIGHTTRACK_`, using `__` for nesting (e.g.
`FLIGHTTRACK_DUMP1090__URL`).

| Key | Default | Description |
|-----|---------|-------------|
| `source` | `synthetic` | `synthetic` \| `replay` \| `dump1090` |
| `receiver.lat` / `.lon` | *(required)* | Your antenna's coordinates — map center & all geometry |
| `receiver.alt_m` | `0.0` | Antenna altitude in meters (improves elevation angles) |
| `synthetic.num_aircraft` | `4` | Fake aircraft count (synthetic source) |
| `synthetic.seed` | `1` | RNG seed for reproducible synthetic traffic |
| `replay.path` | — | Path to a captured `aircraft.json` JSONL file (replay source) |
| `replay.loop` | `true` | Loop the capture when it ends |
| `dump1090.url` | `http://127.0.0.1:8080/data/aircraft.json` | HTTP URL, file path, or `file://` to dump1090's `aircraft.json` |
| `db.path` | `data/flighttrack.db` | SQLite file for contacts/stats/history |
| `logging.snapshot_interval_s` | `15.0` | Seconds between stored track points per aircraft |
| `logging.retention_days` | `30` | Prune stored positions older than this (contacts kept) |
| `faa_db_path` | `data/faa.db` | Offline FAA registry built by `scripts/import_faa.py` |
| `poll_interval_s` | `1.0` | How often to poll the source |
| `stale_timeout_s` | `30.0` | Drop an aircraft this long after its last update |
| `host` | `127.0.0.1` | Bind address (`0.0.0.0` to expose on the LAN) |
| `port` | `8000` | HTTP port |

---

## Environment variables

The app reads secrets from the **process environment** (it does not auto-load `.env`;
use your shell, a `systemd` `EnvironmentFile=`, or `export` them).

| Variable | Purpose |
|----------|---------|
| `FLIGHTTRACK_CONFIG` | Path to the config file (default `config.yaml`) |
| `FLIGHTAWARE_API_KEY` | FlightAware AeroAPI key — enables route/airline lookups |
| `PLANESPOTTERS_UA` | Descriptive User-Agent (with contact URL/email) — enables airframe photos |
| `FLIGHTTRACK_*` | Override any config key (e.g. `FLIGHTTRACK_SOURCE=dump1090`, `FLIGHTTRACK_HOST=0.0.0.0`) |

---

## HTTP & WebSocket API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Live map UI |
| `GET` | `/stats` | Stats & history page |
| `WS`  | `/ws/live` | Live aircraft state, pushed ~1 Hz |
| `GET` | `/healthz` | Health check (`{status, source}`) |
| `GET` | `/api/config` | Receiver location for the map |
| `GET` | `/api/aircraft/{hex}` | Raw dump1090 record for one aircraft |
| `GET` | `/api/flight/{callsign}?hex={hex}` | Enriched route + FAA metadata + photo |
| `GET` | `/api/history?from={ts}&to={ts}` | Stored track points in a time range |
| `GET` | `/api/stats/summary` | Totals / summary tiles |
| `GET` | `/api/stats/per-hour` | Contacts per hour (last 24 h) |
| `GET` | `/api/stats/airlines` | Top airlines |
| `GET` | `/api/stats/buckets?from={ts}&to={ts}&n={n}` | Contacts bucketed over a range |

---

## Testing

```bash
uv run pytest                       # fast unit/integration suite (e2e excluded by default)
uv run playwright install chromium  # once, for the browser smoke tests
uv run pytest -m e2e                # browser smoke tests (run in their own process)
```

The browser smoke tests run separately: sync-Playwright and `pytest-asyncio` can't share one
process (running-event-loop conflict), so `pytest` excludes `e2e` by default.

This repo includes a **gitleaks** pre-commit hook. After cloning:

```bash
uv sync --extra dev
uv run pre-commit install
```

---

## Project layout

```
src/flighttrack/
  config.py            # YAML + env settings (pydantic-settings)
  models.py            # RawAircraft, AircraftView
  geometry.py          # distance / bearing / elevation from the receiver
  tracker.py           # live in-memory state + stale aging
  sources/             # synthetic | replay | dump1090 (+ factory)
  enrichment.py        # FlightAware AeroAPI + planespotters photo lookups
  faa.py               # offline FAA registry DB (build + lookup)
  store.py             # SQLite: contacts, snapshots, stats, flight cache
  recorder.py          # periodic snapshotting from the ingest loop
  app.py               # FastAPI app, ingest loop, REST + /ws/live WebSocket
  server.py            # `flighttrack` entry point (uvicorn)
  static/              # Leaflet map UI — ES modules, no build step
scripts/
  import_faa.py        # download + build the FAA registry SQLite
docs/                  # design specs, phase plans, enhancements backlog
tests/                 # unit, integration, and e2e browser smoke tests
```

---

## License

Released under the **[GNU General Public License v2.0](LICENSE)** (GPL-2.0-only).
