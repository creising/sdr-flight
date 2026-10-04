# Flight Tracker (Phase 1)

Personal ADS-B flight tracker. Phase 1 is the live map running on **synthetic
data** — no SDR required. Later phases add logging/stats and history playback
(Phase 2), SDR deployment via systemd + Tailscale serve (Phase 3), then alerts
+ Web Push (Phase 4).

This project uses [uv](https://docs.astral.sh/uv/) for all Python tooling.

## Run it (Mac, no hardware)

```bash
uv venv --python 3.12 .venv       # once; uv fetches CPython if needed
uv pip install -e ".[dev]"
cp config.example.yaml config.yaml   # edit `receiver:` to your lat/lon
uv run flighttrack                   # serves http://127.0.0.1:8000
```

Open http://127.0.0.1:8000 — synthetic planes orbit your location.

## Test

```bash
uv run pytest                       # fast unit/integration suite (e2e excluded by default)
uv run playwright install chromium  # once, for the browser smoke test
uv run pytest -m e2e                # browser smoke test (runs in its own process)
```

The browser smoke test must run separately: sync-Playwright and pytest-asyncio
cannot share one process, so `pytest` excludes `e2e` by default.

## Data sources

Set `source:` in `config.yaml`:
- `synthetic` — fake traffic (default, dev).
- `replay` — play back a captured `aircraft.json` JSONL file (`replay.path`).
- `dump1090` — live SDR via dump1090's `aircraft.json` (production, Phase 3).

## Project layout

```
src/flighttrack/
  config.py            # YAML + env settings (pydantic-settings)
  models.py            # RawAircraft, AircraftView
  geometry.py          # distance / bearing / elevation from the receiver
  tracker.py           # live in-memory state + stale aging
  sources/             # synthetic | replay | dump1090 (+ factory)
  app.py               # FastAPI app, ingest loop, /ws/live WebSocket
  server.py            # `flighttrack` entry point (uvicorn)
  static/              # Leaflet map UI (no build step)
docs/superpowers/      # spec + phase plans
```
