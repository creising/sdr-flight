# Flight Tracker — Phase 1: Live Map on Synthetic Data — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A runnable FastAPI app that ingests aircraft from a pluggable source (synthetic by default), computes each plane's geometry relative to the receiver, and streams it over a WebSocket to a Leaflet map you open in a browser — all working on a Mac with no SDR.

**Architecture:** A small Python package `flighttrack`. Config (pydantic-settings over YAML + `.env`) selects an `AircraftSource` implementation. A background ingest loop polls the source ~1 Hz, feeds a `Tracker` that holds live in-memory state and computes distance/bearing/elevation from the receiver location, ages out stale aircraft, and broadcasts a JSON snapshot to connected WebSocket clients. The frontend is static HTML/JS (Leaflet via CDN, no build step) that renders markers from those snapshots.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, pydantic v2 + pydantic-settings, PyYAML, httpx (dump1090 fetch + tests), pytest + pytest-asyncio, Leaflet (CDN), Playwright (one marked e2e smoke test).

**Spec:** `docs/superpowers/specs/2026-10-04-sdr-flight-tracker-design.md`

## Global Constraints

- Python **3.11+** (uses `tomllib`, modern typing).
- The HTTP server binds **`127.0.0.1` only** — never `0.0.0.0`. Tailscale serve is the access boundary (Phase 4).
- Frontend has **no build step**: Leaflet loaded from CDN, our own code is plain `.js`/`.css`/`.html` served statically.
- Default data source is **`synthetic`**. `replay` and `dump1090` sources are implemented and wired, but the SDR path is only exercised in production.
- All receiver-relative geometry uses `receiver.{lat, lon, alt_m}` from config; there is **no hardcoded location**. Missing receiver config is a fatal startup error with a clear message.
- Altitudes from ADS-B are in **feet**; convert to meters for geometry. Distances reported to the frontend in **km**.
- **No transmitting** — receive/replay/synthetic only.

## Review Focus

- **Aircraft with no position** (lat/lon absent — very common in real ADS-B, and the synthetic source must emit some): geometry must be skipped without crashing; such aircraft are excluded from the map snapshot. *(Test in Task 2 and Task 5.)*
- **Source unreachable / malformed** (dump1090 down or serving junk): a poll failure must be logged and swallowed so the ingest loop keeps running. *(Test in Task 4 and Task 6.)*
- **Stale aircraft aging**: an aircraft not heard for `stale_timeout_s` must drop out of the live snapshot. *(Test in Task 5.)*
- **WebSocket client disconnect mid-broadcast**: a dead socket must be dropped from the broadcast set without killing the ingest loop or other clients. *(Test in Task 6.)*
- **Missing/invalid receiver config at startup**: must fail fast with an actionable error, not serve a broken app. *(Test in Task 1.)*

---

### Task 1: Project scaffold & configuration

**Files:**
- Create: `pyproject.toml`
- Create: `src/flighttrack/__init__.py`
- Create: `src/flighttrack/config.py`
- Create: `config.example.yaml`
- Create: `.env.example`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `Receiver` (pydantic model): `lat: float`, `lon: float`, `alt_m: float = 0.0`
  - `SyntheticConfig`: `num_aircraft: int = 4`, `seed: int = 1`
  - `ReplayConfig`: `path: str`, `loop: bool = True`
  - `Dump1090Config`: `url: str = "http://127.0.0.1:8080/data/aircraft.json"`
  - `Settings` (pydantic-settings `BaseSettings`): `source: Literal["synthetic","replay","dump1090"] = "synthetic"`, `receiver: Receiver`, `synthetic: SyntheticConfig = SyntheticConfig()`, `replay: ReplayConfig | None = None`, `dump1090: Dump1090Config = Dump1090Config()`, `poll_interval_s: float = 1.0`, `stale_timeout_s: float = 30.0`, `host: str = "127.0.0.1"`, `port: int = 8000`
  - `load_settings(config_path: str | None = None) -> Settings` — loads YAML (path arg, else `$FLIGHTTRACK_CONFIG`, else `./config.yaml`), returns a validated `Settings`. Raises `SystemExit` with a clear message if the file is missing or `receiver` is absent/invalid.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "flighttrack"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "pyyaml>=6.0",
    "httpx>=0.27",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "playwright>=1.44",
    "pytest-playwright>=0.5",
]

[project.scripts]
flighttrack = "flighttrack.server:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
flighttrack = ["static/*", "data/*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = ["e2e: browser smoke tests (require `playwright install chromium`)"]
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_config.py
import textwrap
import pytest
from flighttrack.config import load_settings

def test_loads_yaml_with_receiver(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent("""
        source: synthetic
        receiver:
          lat: 40.0
          lon: -105.0
          alt_m: 1600
        poll_interval_s: 0.5
    """))
    s = load_settings(str(cfg))
    assert s.source == "synthetic"
    assert s.receiver.lat == 40.0
    assert s.receiver.alt_m == 1600
    assert s.poll_interval_s == 0.5
    assert s.host == "127.0.0.1"  # default

def test_missing_file_exits_with_message(tmp_path, capsys):
    with pytest.raises(SystemExit):
        load_settings(str(tmp_path / "nope.yaml"))

def test_missing_receiver_exits(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("source: synthetic\n")
    with pytest.raises(SystemExit):
        load_settings(str(cfg))
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pip install -e ".[dev]" && pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: flighttrack.config`.

- [ ] **Step 4: Write `src/flighttrack/config.py`**

```python
from __future__ import annotations
import os
import sys
from typing import Literal
import yaml
from pydantic import BaseModel, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Receiver(BaseModel):
    lat: float
    lon: float
    alt_m: float = 0.0


class SyntheticConfig(BaseModel):
    num_aircraft: int = 4
    seed: int = 1


class ReplayConfig(BaseModel):
    path: str
    loop: bool = True


class Dump1090Config(BaseModel):
    url: str = "http://127.0.0.1:8080/data/aircraft.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FLIGHTTRACK_", env_nested_delimiter="__")

    source: Literal["synthetic", "replay", "dump1090"] = "synthetic"
    receiver: Receiver
    synthetic: SyntheticConfig = SyntheticConfig()
    replay: ReplayConfig | None = None
    dump1090: Dump1090Config = Dump1090Config()
    poll_interval_s: float = 1.0
    stale_timeout_s: float = 30.0
    host: str = "127.0.0.1"
    port: int = 8000


def load_settings(config_path: str | None = None) -> Settings:
    path = config_path or os.environ.get("FLIGHTTRACK_CONFIG") or "config.yaml"
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        sys.exit(
            f"Config file not found: {path}\n"
            f"Copy config.example.yaml to config.yaml and set your receiver location."
        )
    try:
        return Settings(**data)
    except ValidationError as e:
        sys.exit(f"Invalid config in {path}:\n{e}")
```

- [ ] **Step 5: Write `src/flighttrack/__init__.py`, `tests/__init__.py`, `tests/conftest.py`**

```python
# src/flighttrack/__init__.py
__version__ = "0.1.0"
```

```python
# tests/__init__.py
```

```python
# tests/conftest.py
import pytest
from flighttrack.config import Settings, Receiver

@pytest.fixture
def settings() -> Settings:
    return Settings(source="synthetic", receiver=Receiver(lat=40.0, lon=-105.0, alt_m=1600.0))
```

- [ ] **Step 6: Write `config.example.yaml` and `.env.example`**

```yaml
# config.example.yaml  — copy to config.yaml and edit
source: synthetic          # synthetic | replay | dump1090

receiver:                  # YOUR antenna location (used for all geometry + map center)
  lat: 40.0150
  lon: -105.2705
  alt_m: 1624

synthetic:
  num_aircraft: 4
  seed: 1

# replay:                  # used when source: replay
#   path: captures/sample-aircraft.jsonl
#   loop: true

dump1090:                  # used when source: dump1090 (the Ubuntu box)
  url: http://127.0.0.1:8080/data/aircraft.json

poll_interval_s: 1.0
stale_timeout_s: 30.0
host: 127.0.0.1
port: 8000
```

```bash
# .env.example  — copy to .env (secrets land here in later phases)
# FLIGHTTRACK_CONFIG=config.yaml
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS (3 tests).

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml src/flighttrack/__init__.py src/flighttrack/config.py \
        config.example.yaml .env.example tests/__init__.py tests/conftest.py tests/test_config.py
git commit -m "feat: project scaffold and config loading"
```

---

### Task 2: Domain models & geometry

**Files:**
- Create: `src/flighttrack/models.py`
- Create: `src/flighttrack/geometry.py`
- Test: `tests/test_geometry.py`

**Interfaces:**
- Consumes: `Receiver` from `flighttrack.config`.
- Produces:
  - `RawAircraft` (dataclass): `icao: str`, `callsign: str | None`, `lat: float | None`, `lon: float | None`, `alt_ft: float | None`, `ground_speed_kt: float | None`, `track_deg: float | None`, `seen_s: float`, `rssi: float | None`. (`seen_s` = seconds since last message, from the decoder.)
  - `AircraftView` (dataclass): all `RawAircraft` fields **plus** `distance_km: float | None`, `bearing_deg: float | None`, `elevation_deg: float | None`.
  - `geometry.haversine_km(lat1, lon1, lat2, lon2) -> float`
  - `geometry.initial_bearing_deg(lat1, lon1, lat2, lon2) -> float` (0–360, from point 1 to point 2)
  - `geometry.elevation_deg(ground_distance_km: float, observer_alt_m: float, target_alt_m: float) -> float`
  - `geometry.enrich(raw: RawAircraft, receiver: Receiver) -> AircraftView` — fills geometry when `raw` has lat/lon/alt, leaves those fields `None` otherwise.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_geometry.py
import math
import pytest
from flighttrack.config import Receiver
from flighttrack.models import RawAircraft
from flighttrack import geometry as g

def test_haversine_known_distance():
    # ~1 degree of latitude ≈ 111 km
    d = g.haversine_km(40.0, -105.0, 41.0, -105.0)
    assert d == pytest.approx(111.2, abs=1.0)

def test_bearing_due_north():
    b = g.initial_bearing_deg(40.0, -105.0, 41.0, -105.0)
    assert b == pytest.approx(0.0, abs=0.5)

def test_bearing_due_east():
    b = g.initial_bearing_deg(40.0, -105.0, 40.0, -104.0)
    assert b == pytest.approx(90.0, abs=0.5)

def test_elevation_directly_overhead_is_90():
    # zero ground distance, aircraft above -> straight up
    assert g.elevation_deg(0.0, 1600.0, 11000.0) == pytest.approx(90.0, abs=0.1)

def test_elevation_far_and_low_is_small():
    # 100 km away, 10 km up -> shallow angle
    e = g.elevation_deg(100.0, 0.0, 10000.0)
    assert 0 < e < 10

def test_enrich_fills_geometry():
    rx = Receiver(lat=40.0, lon=-105.0, alt_m=1600.0)
    raw = RawAircraft(icao="abc123", callsign="UAL1", lat=41.0, lon=-105.0,
                      alt_ft=36089.0, ground_speed_kt=450, track_deg=180, seen_s=0.5, rssi=-10.0)
    v = g.enrich(raw, rx)
    assert v.distance_km == pytest.approx(111.2, abs=1.0)
    assert v.bearing_deg == pytest.approx(0.0, abs=0.5)
    assert v.elevation_deg is not None and v.elevation_deg > 0

def test_enrich_without_position_leaves_geometry_none():
    rx = Receiver(lat=40.0, lon=-105.0, alt_m=1600.0)
    raw = RawAircraft(icao="abc123", callsign=None, lat=None, lon=None,
                      alt_ft=None, ground_speed_kt=None, track_deg=None, seen_s=2.0, rssi=None)
    v = g.enrich(raw, rx)
    assert v.distance_km is None and v.bearing_deg is None and v.elevation_deg is None
    assert v.icao == "abc123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_geometry.py -v`
Expected: FAIL — `ModuleNotFoundError: flighttrack.models`.

- [ ] **Step 3: Write `src/flighttrack/models.py`**

```python
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class RawAircraft:
    icao: str
    callsign: str | None
    lat: float | None
    lon: float | None
    alt_ft: float | None
    ground_speed_kt: float | None
    track_deg: float | None
    seen_s: float
    rssi: float | None


@dataclass
class AircraftView:
    icao: str
    callsign: str | None
    lat: float | None
    lon: float | None
    alt_ft: float | None
    ground_speed_kt: float | None
    track_deg: float | None
    seen_s: float
    rssi: float | None
    distance_km: float | None = None
    bearing_deg: float | None = None
    elevation_deg: float | None = None
```

- [ ] **Step 4: Write `src/flighttrack/geometry.py`**

```python
from __future__ import annotations
import math
from flighttrack.config import Receiver
from flighttrack.models import RawAircraft, AircraftView

_EARTH_KM = 6371.0088
_FT_TO_M = 0.3048


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * _EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def elevation_deg(ground_distance_km: float, observer_alt_m: float, target_alt_m: float) -> float:
    dh = target_alt_m - observer_alt_m
    d_m = ground_distance_km * 1000.0
    if d_m == 0.0:
        return 90.0 if dh > 0 else (-90.0 if dh < 0 else 0.0)
    return math.degrees(math.atan2(dh, d_m))


def enrich(raw: RawAircraft, receiver: Receiver) -> AircraftView:
    v = AircraftView(**raw.__dict__)
    if raw.lat is None or raw.lon is None:
        return v
    v.distance_km = haversine_km(receiver.lat, receiver.lon, raw.lat, raw.lon)
    v.bearing_deg = initial_bearing_deg(receiver.lat, receiver.lon, raw.lat, raw.lon)
    if raw.alt_ft is not None:
        v.elevation_deg = elevation_deg(v.distance_km, receiver.alt_m, raw.alt_ft * _FT_TO_M)
    return v
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_geometry.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add src/flighttrack/models.py src/flighttrack/geometry.py tests/test_geometry.py
git commit -m "feat: aircraft models and receiver-relative geometry"
```

---

### Task 3: Source protocol & SyntheticSource

**Files:**
- Create: `src/flighttrack/sources/__init__.py`
- Create: `src/flighttrack/sources/base.py`
- Create: `src/flighttrack/sources/synthetic.py`
- Test: `tests/test_synthetic.py`

**Interfaces:**
- Consumes: `RawAircraft` from `flighttrack.models`; `Receiver`, `SyntheticConfig` from `flighttrack.config`.
- Produces:
  - `base.AircraftSource` (Protocol): `async def poll(self) -> list[RawAircraft]`
  - `synthetic.SyntheticSource(receiver: Receiver, config: SyntheticConfig, clock=time.monotonic)` — generates `num_aircraft` deterministic planes (seeded) that move each call, orbiting/transiting near `receiver`. At least one generated plane has `lat=lon=None` (position-less, to exercise that path). Advancing time between polls changes positions.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_synthetic.py
import pytest
from flighttrack.config import Receiver, SyntheticConfig
from flighttrack.sources.synthetic import SyntheticSource

@pytest.fixture
def rx():
    return Receiver(lat=40.0, lon=-105.0, alt_m=1600.0)

async def test_poll_returns_configured_count(rx):
    clock = {"t": 0.0}
    src = SyntheticSource(rx, SyntheticConfig(num_aircraft=4, seed=1), clock=lambda: clock["t"])
    planes = await src.poll()
    assert len(planes) == 4
    assert all(p.icao for p in planes)

async def test_positions_change_over_time(rx):
    clock = {"t": 0.0}
    src = SyntheticSource(rx, SyntheticConfig(num_aircraft=3, seed=1), clock=lambda: clock["t"])
    first = {p.icao: (p.lat, p.lon) for p in await src.poll() if p.lat is not None}
    clock["t"] = 30.0
    second = {p.icao: (p.lat, p.lon) for p in await src.poll() if p.lat is not None}
    moved = [k for k in first if first[k] != second.get(k)]
    assert moved, "at least one positioned aircraft should have moved"

async def test_includes_a_positionless_aircraft(rx):
    clock = {"t": 0.0}
    src = SyntheticSource(rx, SyntheticConfig(num_aircraft=4, seed=1), clock=lambda: clock["t"])
    planes = await src.poll()
    assert any(p.lat is None and p.lon is None for p in planes)

async def test_deterministic_for_same_seed(rx):
    a = SyntheticSource(rx, SyntheticConfig(num_aircraft=4, seed=7), clock=lambda: 0.0)
    b = SyntheticSource(rx, SyntheticConfig(num_aircraft=4, seed=7), clock=lambda: 0.0)
    assert [p.icao for p in await a.poll()] == [p.icao for p in await b.poll()]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_synthetic.py -v`
Expected: FAIL — `ModuleNotFoundError: flighttrack.sources`.

- [ ] **Step 3: Write `src/flighttrack/sources/__init__.py` and `base.py`**

```python
# src/flighttrack/sources/__init__.py
```

```python
# src/flighttrack/sources/base.py
from __future__ import annotations
from typing import Protocol
from flighttrack.models import RawAircraft


class AircraftSource(Protocol):
    async def poll(self) -> list[RawAircraft]: ...
```

- [ ] **Step 4: Write `src/flighttrack/sources/synthetic.py`**

```python
from __future__ import annotations
import math
import random
import time
from typing import Callable
from flighttrack.config import Receiver, SyntheticConfig
from flighttrack.models import RawAircraft

_AIRLINES = ["UAL", "DAL", "AAL", "SWA", "FFT", "JBU"]


class SyntheticSource:
    """Deterministic fake traffic orbiting the receiver, for hardware-free dev."""

    def __init__(self, receiver: Receiver, config: SyntheticConfig,
                 clock: Callable[[], float] = time.monotonic):
        self.rx = receiver
        self.cfg = config
        self._clock = clock
        rng = random.Random(config.seed)
        self._planes = []
        for i in range(config.num_aircraft):
            self._planes.append({
                "icao": f"{rng.randint(0, 0xFFFFFF):06x}",
                "callsign": f"{rng.choice(_AIRLINES)}{rng.randint(100, 999)}",
                "radius_km": rng.uniform(5.0, 60.0),
                "angular_speed": rng.uniform(0.01, 0.05) * rng.choice([-1, 1]),  # rad/s
                "phase": rng.uniform(0, 2 * math.pi),
                "alt_ft": rng.choice([8000, 12000, 20000, 33000, 38000]),
                "gs": rng.uniform(250, 500),
                "positionless": i == 0,  # first plane never reports a position
            })

    async def poll(self) -> list[RawAircraft]:
        t = self._clock()
        out: list[RawAircraft] = []
        for p in self._planes:
            if p["positionless"]:
                out.append(RawAircraft(
                    icao=p["icao"], callsign=p["callsign"], lat=None, lon=None,
                    alt_ft=None, ground_speed_kt=None, track_deg=None, seen_s=0.0, rssi=-20.0))
                continue
            ang = p["phase"] + p["angular_speed"] * t
            dlat = (p["radius_km"] / 111.0) * math.sin(ang)
            dlon = (p["radius_km"] / (111.0 * math.cos(math.radians(self.rx.lat)))) * math.cos(ang)
            track = (math.degrees(ang) + 90.0) % 360.0
            out.append(RawAircraft(
                icao=p["icao"], callsign=p["callsign"],
                lat=self.rx.lat + dlat, lon=self.rx.lon + dlon,
                alt_ft=float(p["alt_ft"]), ground_speed_kt=float(p["gs"]),
                track_deg=track, seen_s=0.0, rssi=-15.0))
        return out
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_synthetic.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add src/flighttrack/sources/__init__.py src/flighttrack/sources/base.py \
        src/flighttrack/sources/synthetic.py tests/test_synthetic.py
git commit -m "feat: AircraftSource protocol and deterministic synthetic source"
```

---

### Task 4: Dump1090Source, ReplaySource & source factory

**Files:**
- Create: `src/flighttrack/sources/dump1090.py`
- Create: `src/flighttrack/sources/replay.py`
- Create: `src/flighttrack/sources/factory.py`
- Create: `tests/fixtures/aircraft_sample.json`
- Test: `tests/test_sources.py`

**Interfaces:**
- Consumes: `Settings`, `Receiver` from config; `RawAircraft`; `AircraftSource`; `SyntheticSource`.
- Produces:
  - `dump1090.parse_aircraft_json(doc: dict) -> list[RawAircraft]` — maps dump1090-fa `aircraft.json` records (`hex`, `flight`, `lat`, `lon`, `alt_baro`, `gs`, `track`, `seen`, `rssi`) to `RawAircraft`; skips records without `hex`; tolerates missing optional fields; treats `alt_baro == "ground"` as `None`.
  - `dump1090.Dump1090Source(url: str, client: httpx.AsyncClient | None = None)` with `async poll()`. On any HTTP/parse error, logs a warning and returns `[]` (never raises).
  - `replay.ReplaySource(path: str, loop: bool, clock=time.monotonic)` with `async poll()` — reads a JSONL capture (one `aircraft.json`-shaped frame per line) and returns the frame matching elapsed time, looping if configured.
  - `factory.build_source(settings: Settings) -> AircraftSource` — returns the configured source; raises `ValueError` if `replay` selected without `replay` config.

- [ ] **Step 1: Write the fixture**

```json
// tests/fixtures/aircraft_sample.json
{
  "now": 1712000000.0,
  "aircraft": [
    {"hex": "a1b2c3", "flight": "UAL123 ", "lat": 40.1, "lon": -105.1, "alt_baro": 35000, "gs": 450.0, "track": 270.0, "seen": 0.3, "rssi": -12.1},
    {"hex": "d4e5f6", "flight": "N750QS ", "alt_baro": "ground", "seen": 1.2, "rssi": -22.0},
    {"hex": "112233", "lat": 40.3, "lon": -105.4, "alt_baro": 12000, "seen": 0.9}
  ]
}
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_sources.py
import json
import pathlib
import httpx
import pytest
from flighttrack.config import Settings, Receiver, ReplayConfig, Dump1090Config
from flighttrack.sources import dump1090, replay
from flighttrack.sources.factory import build_source
from flighttrack.sources.synthetic import SyntheticSource

FIX = pathlib.Path(__file__).parent / "fixtures" / "aircraft_sample.json"

def test_parse_maps_and_cleans_fields():
    doc = json.loads(FIX.read_text())
    planes = dump1090.parse_aircraft_json(doc)
    assert len(planes) == 3
    ual = next(p for p in planes if p.icao == "a1b2c3")
    assert ual.callsign == "UAL123"           # trimmed
    assert ual.alt_ft == 35000 and ual.lat == 40.1
    ground = next(p for p in planes if p.icao == "d4e5f6")
    assert ground.alt_ft is None               # "ground" -> None
    assert ground.lat is None                  # no position
    minimal = next(p for p in planes if p.icao == "112233")
    assert minimal.callsign is None and minimal.ground_speed_kt is None

def test_parse_skips_records_without_hex():
    planes = dump1090.parse_aircraft_json({"aircraft": [{"flight": "X"}, {"hex": "aa"}]})
    assert [p.icao for p in planes] == ["aa"]

async def test_dump1090_source_swallows_errors():
    transport = httpx.MockTransport(lambda req: httpx.Response(500))
    client = httpx.AsyncClient(transport=transport)
    src = dump1090.Dump1090Source("http://x/data/aircraft.json", client=client)
    assert await src.poll() == []              # no raise
    await client.aclose()

async def test_dump1090_source_parses_ok():
    body = FIX.read_text()
    transport = httpx.MockTransport(lambda req: httpx.Response(200, text=body))
    client = httpx.AsyncClient(transport=transport)
    src = dump1090.Dump1090Source("http://x/data/aircraft.json", client=client)
    planes = await src.poll()
    assert len(planes) == 3
    await client.aclose()

async def test_replay_reads_frames(tmp_path):
    cap = tmp_path / "cap.jsonl"
    f0 = {"now": 0.0, "aircraft": [{"hex": "aa", "lat": 1.0, "lon": 2.0, "alt_baro": 5000, "seen": 0}]}
    f1 = {"now": 1.0, "aircraft": [{"hex": "aa", "lat": 1.1, "lon": 2.0, "alt_baro": 5000, "seen": 0}]}
    cap.write_text(json.dumps(f0) + "\n" + json.dumps(f1) + "\n")
    clock = {"t": 0.0}
    src = replay.ReplaySource(str(cap), loop=True, clock=lambda: clock["t"])
    p0 = await src.poll()
    assert p0[0].lat == 1.0
    clock["t"] = 1.0
    p1 = await src.poll()
    assert p1[0].lat == 1.1

def test_factory_requires_replay_config():
    s = Settings(source="replay", receiver=Receiver(lat=0, lon=0), replay=None)
    with pytest.raises(ValueError):
        build_source(s)

def test_factory_builds_synthetic():
    s = Settings(source="synthetic", receiver=Receiver(lat=0, lon=0))
    assert isinstance(build_source(s), SyntheticSource)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_sources.py -v`
Expected: FAIL — `ModuleNotFoundError: flighttrack.sources.dump1090`.

- [ ] **Step 4: Write `src/flighttrack/sources/dump1090.py`**

```python
from __future__ import annotations
import logging
import httpx
from flighttrack.models import RawAircraft

log = logging.getLogger(__name__)


def parse_aircraft_json(doc: dict) -> list[RawAircraft]:
    out: list[RawAircraft] = []
    for a in doc.get("aircraft", []):
        hexid = a.get("hex")
        if not hexid:
            continue
        alt = a.get("alt_baro")
        if alt == "ground" or not isinstance(alt, (int, float)):
            alt = None
        flight = a.get("flight")
        out.append(RawAircraft(
            icao=hexid,
            callsign=flight.strip() if isinstance(flight, str) and flight.strip() else None,
            lat=a.get("lat"), lon=a.get("lon"),
            alt_ft=float(alt) if alt is not None else None,
            ground_speed_kt=a.get("gs"), track_deg=a.get("track"),
            seen_s=float(a.get("seen", 0.0)), rssi=a.get("rssi")))
    return out


class Dump1090Source:
    def __init__(self, url: str, client: httpx.AsyncClient | None = None):
        self.url = url
        self._client = client or httpx.AsyncClient(timeout=3.0)

    async def poll(self) -> list[RawAircraft]:
        try:
            r = await self._client.get(self.url)
            r.raise_for_status()
            return parse_aircraft_json(r.json())
        except Exception as e:  # network down, bad JSON, decoder restarting
            log.warning("dump1090 poll failed: %s", e)
            return []
```

- [ ] **Step 5: Write `src/flighttrack/sources/replay.py`**

```python
from __future__ import annotations
import json
import time
from typing import Callable
from flighttrack.models import RawAircraft
from flighttrack.sources.dump1090 import parse_aircraft_json


class ReplaySource:
    """Plays back a JSONL capture of aircraft.json frames at recorded cadence."""

    def __init__(self, path: str, loop: bool = True, clock: Callable[[], float] = time.monotonic):
        with open(path) as f:
            self._frames = [json.loads(line) for line in f if line.strip()]
        if not self._frames:
            raise ValueError(f"replay capture {path} is empty")
        self._loop = loop
        self._clock = clock
        self._t0 = clock()
        base = self._frames[0].get("now", 0.0)
        self._offsets = [fr.get("now", 0.0) - base for fr in self._frames]
        self._span = self._offsets[-1] or 1.0

    async def poll(self) -> list[RawAircraft]:
        elapsed = self._clock() - self._t0
        if self._loop:
            elapsed = elapsed % (self._span + 1e-9)
        idx = 0
        for i, off in enumerate(self._offsets):
            if off <= elapsed:
                idx = i
            else:
                break
        return parse_aircraft_json(self._frames[idx])
```

- [ ] **Step 6: Write `src/flighttrack/sources/factory.py`**

```python
from __future__ import annotations
from flighttrack.config import Settings
from flighttrack.sources.base import AircraftSource
from flighttrack.sources.synthetic import SyntheticSource
from flighttrack.sources.replay import ReplaySource
from flighttrack.sources.dump1090 import Dump1090Source


def build_source(settings: Settings) -> AircraftSource:
    if settings.source == "synthetic":
        return SyntheticSource(settings.receiver, settings.synthetic)
    if settings.source == "replay":
        if settings.replay is None:
            raise ValueError("source=replay requires a `replay:` config block")
        return ReplaySource(settings.replay.path, settings.replay.loop)
    if settings.source == "dump1090":
        return Dump1090Source(settings.dump1090.url)
    raise ValueError(f"unknown source: {settings.source}")
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_sources.py -v`
Expected: PASS (7 tests).

- [ ] **Step 8: Commit**

```bash
git add src/flighttrack/sources/dump1090.py src/flighttrack/sources/replay.py \
        src/flighttrack/sources/factory.py tests/fixtures/aircraft_sample.json tests/test_sources.py
git commit -m "feat: dump1090, replay sources and source factory"
```

---

### Task 5: Tracker — live state, geometry, aging

**Files:**
- Create: `src/flighttrack/tracker.py`
- Test: `tests/test_tracker.py`

**Interfaces:**
- Consumes: `Receiver` from config; `RawAircraft`, `AircraftView`; `geometry.enrich`.
- Produces:
  - `Tracker(receiver: Receiver, stale_timeout_s: float = 30.0)`
  - `Tracker.update(raw: list[RawAircraft], now: float) -> None` — enriches, upserts into live state keyed by icao, stamps each with `now`, drops entries whose last update is older than `stale_timeout_s`.
  - `Tracker.snapshot() -> list[AircraftView]` — current live aircraft; positioned aircraft sorted by `distance_km` ascending, position-less aircraft appended after.
  - `Tracker.to_json() -> dict` — `{"now": <float last update>, "aircraft": [<view dicts>], "receiver": {...}}` for the WebSocket. Only positioned aircraft are included in `aircraft` (the map needs coordinates).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tracker.py
import pytest
from flighttrack.config import Receiver
from flighttrack.models import RawAircraft
from flighttrack.tracker import Tracker

@pytest.fixture
def rx():
    return Receiver(lat=40.0, lon=-105.0, alt_m=1600.0)

def raw(icao, lat=40.5, lon=-105.0, alt=30000, seen=0.0):
    return RawAircraft(icao=icao, callsign="T"+icao, lat=lat, lon=lon, alt_ft=alt,
                       ground_speed_kt=400, track_deg=90, seen_s=seen, rssi=-10.0)

def test_update_and_snapshot_enriches(rx):
    t = Tracker(rx, stale_timeout_s=30)
    t.update([raw("aaa")], now=100.0)
    snap = t.snapshot()
    assert len(snap) == 1 and snap[0].distance_km is not None

def test_snapshot_sorted_by_distance(rx):
    t = Tracker(rx, stale_timeout_s=30)
    t.update([raw("far", lat=42.0), raw("near", lat=40.1)], now=100.0)
    snap = t.snapshot()
    assert snap[0].icao == "near" and snap[1].icao == "far"

def test_stale_aircraft_drop_out(rx):
    t = Tracker(rx, stale_timeout_s=30)
    t.update([raw("aaa")], now=100.0)
    t.update([raw("bbb")], now=140.0)          # 40s later, aaa not refreshed
    icaos = {a.icao for a in t.snapshot()}
    assert icaos == {"bbb"}

def test_positionless_excluded_from_json_but_in_snapshot(rx):
    t = Tracker(rx, stale_timeout_s=30)
    noposn = RawAircraft(icao="ghost", callsign=None, lat=None, lon=None, alt_ft=None,
                         ground_speed_kt=None, track_deg=None, seen_s=0.0, rssi=-25.0)
    t.update([raw("aaa"), noposn], now=100.0)
    assert {a.icao for a in t.snapshot()} == {"aaa", "ghost"}
    j = t.to_json()
    assert [a["icao"] for a in j["aircraft"]] == ["aaa"]
    assert j["receiver"]["lat"] == 40.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tracker.py -v`
Expected: FAIL — `ModuleNotFoundError: flighttrack.tracker`.

- [ ] **Step 3: Write `src/flighttrack/tracker.py`**

```python
from __future__ import annotations
from dataclasses import asdict
from flighttrack.config import Receiver
from flighttrack.models import RawAircraft, AircraftView
from flighttrack.geometry import enrich


class Tracker:
    def __init__(self, receiver: Receiver, stale_timeout_s: float = 30.0):
        self.rx = receiver
        self.stale = stale_timeout_s
        self._live: dict[str, tuple[float, AircraftView]] = {}
        self._now = 0.0

    def update(self, raw: list[RawAircraft], now: float) -> None:
        self._now = now
        for r in raw:
            self._live[r.icao] = (now, enrich(r, self.rx))
        cutoff = now - self.stale
        self._live = {k: v for k, v in self._live.items() if v[0] >= cutoff}

    def snapshot(self) -> list[AircraftView]:
        views = [v for _, v in self._live.values()]
        positioned = [v for v in views if v.distance_km is not None]
        positionless = [v for v in views if v.distance_km is None]
        positioned.sort(key=lambda v: v.distance_km)  # type: ignore[arg-type]
        return positioned + positionless

    def to_json(self) -> dict:
        return {
            "now": self._now,
            "receiver": {"lat": self.rx.lat, "lon": self.rx.lon, "alt_m": self.rx.alt_m},
            "aircraft": [asdict(v) for v in self.snapshot() if v.lat is not None],
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tracker.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/flighttrack/tracker.py tests/test_tracker.py
git commit -m "feat: live-state tracker with geometry and stale aging"
```

---

### Task 6: FastAPI app, ingest loop & WebSocket

**Files:**
- Create: `src/flighttrack/app.py`
- Create: `src/flighttrack/server.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `load_settings`, `Settings`; `build_source`; `Tracker`.
- Produces:
  - `app.ConnectionManager` — `connect(ws)`, `disconnect(ws)`, `async broadcast(data: dict)` that serializes once and drops any socket that raises.
  - `app.create_app(settings: Settings) -> FastAPI` — wires routes, mounts `static/`, and on startup launches the ingest loop (`poll → tracker.update → manager.broadcast`) as a background task; stores `settings`, `tracker`, `manager`, `source` on `app.state`. The loop catches per-iteration exceptions and continues.
  - Routes: `GET /healthz` → `{"status":"ok","source":...}`; `GET /api/config` → receiver + map defaults; `WS /ws/live` → sends the current `tracker.to_json()` immediately on connect, then each broadcast; `GET /` → `static/index.html`.
  - `server.main()` — console entry: `load_settings()`, `create_app`, `uvicorn.run(app, host=settings.host, port=settings.port)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_app.py
import pytest
from fastapi.testclient import TestClient
from flighttrack.config import Settings, Receiver, SyntheticConfig
from flighttrack.app import create_app, ConnectionManager

@pytest.fixture
def client():
    s = Settings(source="synthetic", receiver=Receiver(lat=40.0, lon=-105.0, alt_m=1600.0),
                 synthetic=SyntheticConfig(num_aircraft=3, seed=1), poll_interval_s=0.05)
    app = create_app(s)
    with TestClient(app) as c:   # triggers startup -> ingest loop
        yield c

def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["source"] == "synthetic"

def test_config_endpoint_exposes_receiver(client):
    r = client.get("/api/config")
    body = r.json()
    assert body["receiver"]["lat"] == 40.0

def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]

def test_ws_live_sends_snapshot(client):
    with client.websocket_connect("/ws/live") as ws:
        msg = ws.receive_json()
        assert "aircraft" in msg and "receiver" in msg
        assert isinstance(msg["aircraft"], list)

async def test_broadcast_drops_dead_sockets():
    mgr = ConnectionManager()
    class DeadWS:
        async def send_text(self, _): raise RuntimeError("closed")
    class LiveWS:
        def __init__(self): self.sent = []
        async def send_text(self, t): self.sent.append(t)
    dead, live = DeadWS(), LiveWS()
    mgr.connect(dead); mgr.connect(live)
    await mgr.broadcast({"x": 1})
    assert live.sent and dead not in mgr.active
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_app.py -v`
Expected: FAIL — `ModuleNotFoundError: flighttrack.app`.

- [ ] **Step 3: Write `src/flighttrack/app.py`**

```python
from __future__ import annotations
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from flighttrack.config import Settings
from flighttrack.sources.factory import build_source
from flighttrack.tracker import Tracker

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"


class ConnectionManager:
    def __init__(self) -> None:
        self.active: set[WebSocket] = set()

    def connect(self, ws: WebSocket) -> None:
        self.active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.active.discard(ws)

    async def broadcast(self, data: dict) -> None:
        text = json.dumps(data)
        for ws in list(self.active):
            try:
                await ws.send_text(text)
            except Exception:
                self.active.discard(ws)


async def _ingest_loop(app: FastAPI) -> None:
    source = app.state.source
    tracker: Tracker = app.state.tracker
    manager: ConnectionManager = app.state.manager
    interval = app.state.settings.poll_interval_s
    while True:
        try:
            raw = await source.poll()
            tracker.update(raw, now=time.time())
            await manager.broadcast(tracker.to_json())
        except Exception as e:
            log.warning("ingest iteration failed: %s", e)
        await asyncio.sleep(interval)


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.tracker = Tracker(settings.receiver, settings.stale_timeout_s)
        app.state.manager = ConnectionManager()
        app.state.source = build_source(settings)
        task = asyncio.create_task(_ingest_loop(app))
        try:
            yield
        finally:
            task.cancel()

    app = FastAPI(lifespan=lifespan)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "source": settings.source}

    @app.get("/api/config")
    def config():
        rx = settings.receiver
        return {"receiver": {"lat": rx.lat, "lon": rx.lon, "alt_m": rx.alt_m}}

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.websocket("/ws/live")
    async def ws_live(ws: WebSocket):
        await ws.accept()
        mgr: ConnectionManager = app.state.manager
        mgr.connect(ws)
        try:
            await ws.send_text(json.dumps(app.state.tracker.to_json()))
            while True:
                await ws.receive_text()  # keepalive / ignore client msgs
        except WebSocketDisconnect:
            pass
        finally:
            mgr.disconnect(ws)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
```

- [ ] **Step 4: Write `src/flighttrack/server.py`** and a placeholder static dir so the app boots

```python
# src/flighttrack/server.py
from __future__ import annotations
import uvicorn
from flighttrack.config import load_settings
from flighttrack.app import create_app


def main() -> None:
    settings = load_settings()
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
```

Create `src/flighttrack/static/index.html` as a stub so `GET /` works (replaced in Task 7):

```html
<!doctype html><meta charset="utf-8"><title>Flight Tracker</title><p>ok</p>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_app.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add src/flighttrack/app.py src/flighttrack/server.py src/flighttrack/static/index.html tests/test_app.py
git commit -m "feat: FastAPI app, background ingest loop and live WebSocket"
```

---

### Task 7: Live map frontend + e2e smoke test

**Files:**
- Create: `src/flighttrack/static/index.html` (replace stub)
- Create: `src/flighttrack/static/style.css`
- Create: `src/flighttrack/static/app.js`
- Test: `tests/test_frontend_smoke.py`

**Interfaces:**
- Consumes: `GET /`, `GET /api/config`, `WS /ws/live` from Task 6.
- Produces: a browser page that renders synthetic aircraft as rotated markers on a Leaflet map centered on the receiver, with a contacts sidebar. No new Python interfaces.

- [ ] **Step 1: Write `src/flighttrack/static/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Flight Tracker</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <link rel="stylesheet" href="/static/style.css" />
</head>
<body>
  <div id="app">
    <aside id="sidebar">
      <h1>Overhead</h1>
      <div id="status">connecting…</div>
      <ul id="contacts"></ul>
    </aside>
    <div id="map"></div>
  </div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `src/flighttrack/static/style.css`**

```css
:root { color-scheme: dark; }
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; background: #0b0f14; color: #e6edf3;
  font: 14px/1.4 system-ui, sans-serif; }
#app { display: flex; height: 100vh; }
#sidebar { width: 280px; padding: 12px 16px; overflow-y: auto; border-right: 1px solid #1c2430; }
#sidebar h1 { font-size: 15px; letter-spacing: .08em; text-transform: uppercase; color: #8aa0b4; }
#status { font-size: 12px; color: #6b7d8f; margin-bottom: 8px; }
#contacts { list-style: none; margin: 0; padding: 0; }
#contacts li { padding: 8px 0; border-bottom: 1px solid #141b24; }
#contacts .cs { font-weight: 600; }
#contacts .meta { color: #8aa0b4; font-size: 12px; }
#map { flex: 1; }
.plane { font-size: 20px; text-shadow: 0 0 2px #000; transform-origin: center; }
@media (max-width: 640px) {
  #app { flex-direction: column; }
  #sidebar { width: 100%; height: 40vh; }
}
```

- [ ] **Step 3: Write `src/flighttrack/static/app.js`**

```javascript
let map, youMarker;
const markers = new Map(); // icao -> L.marker

function altColor(ft) {
  if (ft == null) return "#9aa7b2";
  if (ft < 10000) return "#ff5d5d";
  if (ft < 25000) return "#ffb24d";
  return "#5dd0ff";
}

function planeIcon(a) {
  const rot = a.track_deg ?? 0;
  return L.divIcon({
    className: "",
    html: `<div class="plane" style="transform: rotate(${rot}deg); color:${altColor(a.alt_ft)}">✈</div>`,
    iconSize: [20, 20], iconAnchor: [10, 10],
  });
}

function renderContacts(list) {
  const ul = document.getElementById("contacts");
  ul.innerHTML = "";
  for (const a of list) {
    const li = document.createElement("li");
    const dist = a.distance_km != null ? `${a.distance_km.toFixed(1)} km` : "—";
    const alt = a.alt_ft != null ? `${Math.round(a.alt_ft).toLocaleString()} ft` : "—";
    li.innerHTML = `<div class="cs">${a.callsign || a.icao}</div>` +
                   `<div class="meta">${dist} · ${alt} · ${Math.round(a.elevation_deg ?? 0)}°</div>`;
    ul.appendChild(li);
  }
}

function update(data) {
  const seen = new Set();
  for (const a of data.aircraft) {
    seen.add(a.icao);
    let m = markers.get(a.icao);
    if (!m) { m = L.marker([a.lat, a.lon], { icon: planeIcon(a) }).addTo(map); markers.set(a.icao, m); }
    else { m.setLatLng([a.lat, a.lon]); m.setIcon(planeIcon(a)); }
    m.bindTooltip(a.callsign || a.icao);
  }
  for (const [icao, m] of markers) if (!seen.has(icao)) { map.removeLayer(m); markers.delete(icao); }
  renderContacts(data.aircraft);
  document.getElementById("status").textContent =
    `${data.aircraft.length} aircraft · live`;
}

async function init() {
  const cfg = await (await fetch("/api/config")).json();
  const { lat, lon } = cfg.receiver;
  map = L.map("map").setView([lat, lon], 9);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    { attribution: "© OpenStreetMap", maxZoom: 18 }).addTo(map);
  youMarker = L.circleMarker([lat, lon], { radius: 6, color: "#4de6a1", fillOpacity: 1 })
    .addTo(map).bindTooltip("You");

  const proto = location.protocol === "https:" ? "wss" : "ws";
  function connect() {
    const ws = new WebSocket(`${proto}://${location.host}/ws/live`);
    ws.onmessage = (e) => update(JSON.parse(e.data));
    ws.onclose = () => {
      document.getElementById("status").textContent = "reconnecting…";
      setTimeout(connect, 2000);
    };
  }
  connect();
}
init();
```

- [ ] **Step 4: Write the e2e smoke test**

```python
# tests/test_frontend_smoke.py
import socket
import threading
import time
import pytest
import uvicorn
from flighttrack.config import Settings, Receiver, SyntheticConfig
from flighttrack.app import create_app

pytestmark = pytest.mark.e2e


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture
def server_url():
    port = _free_port()
    settings = Settings(source="synthetic",
                        receiver=Receiver(lat=40.0, lon=-105.0, alt_m=1600.0),
                        synthetic=SyntheticConfig(num_aircraft=4, seed=1),
                        poll_interval_s=0.1, port=port)
    config = uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def test_map_renders_a_plane_marker(server_url, page):
    page.goto(server_url)
    # a synthetic plane marker should appear within a few seconds
    page.wait_for_selector(".plane", timeout=8000)
    assert page.locator("#status").inner_text() != "connecting…"
```

- [ ] **Step 5: Run the smoke test**

Run: `playwright install chromium && pytest tests/test_frontend_smoke.py -v -m e2e`
Expected: PASS — a `.plane` marker appears and status leaves "connecting…".
(If Chromium can't be installed in this environment, run the manual check in Step 6 instead and note it.)

- [ ] **Step 6: Manual verification**

Run: `cp config.example.yaml config.yaml` (edit `receiver` to your location), then `flighttrack`.
Open `http://127.0.0.1:8000` — you should see planes orbiting your location, a contacts list counting down distance, and a green "You" dot at the center.

- [ ] **Step 7: Commit**

```bash
git add src/flighttrack/static/index.html src/flighttrack/static/style.css \
        src/flighttrack/static/app.js tests/test_frontend_smoke.py
git commit -m "feat: Leaflet live map frontend with e2e smoke test"
```

---

### Task 8: README & developer run docs

**Files:**
- Create: `README.md`
- Modify: `.gitignore` (ensure `config.yaml`, `captures/`, `*.db` ignored — already set in repo; verify)

**Interfaces:** none (documentation).

- [ ] **Step 1: Write `README.md`**

````markdown
# Flight Tracker (Phase 1)

Personal ADS-B flight tracker. Phase 1 is the live map running on **synthetic
data** — no SDR required. Later phases add logging/stats and history playback
(Phase 2), SDR deployment via systemd + Tailscale serve (Phase 3), then alerts
+ Web Push (Phase 4).

## Run it (Mac, no hardware)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp config.example.yaml config.yaml      # edit `receiver:` to your lat/lon
flighttrack                             # serves http://127.0.0.1:8000
```

Open http://127.0.0.1:8000 — synthetic planes orbit your location.

## Test

```bash
pytest -m "not e2e"          # fast unit/integration suite
playwright install chromium  # once, for the browser smoke test
pytest -m e2e                # browser smoke test
```

## Data sources

Set `source:` in `config.yaml`:
- `synthetic` — fake traffic (default, dev).
- `replay` — play back a captured `aircraft.json` JSONL file (`replay.path`).
- `dump1090` — live SDR via dump1090's `aircraft.json` (production, Phase 4).
````

- [ ] **Step 2: Verify .gitignore and that config.yaml is ignored**

Run: `git status --porcelain config.yaml`
Expected: no output (ignored).

- [ ] **Step 3: Run the full non-e2e suite green**

Run: `pytest -m "not e2e" -v`
Expected: PASS (all tasks' tests).

- [ ] **Step 4: Commit**

```bash
git add README.md .gitignore
git commit -m "docs: Phase 1 README and run instructions"
```

---

## Self-Review

**Spec coverage (Phase 1 slice):**
- Source abstraction + synthetic/replay/dump1090 → Tasks 3, 4. ✓
- Receiver-relative geometry (distance/bearing/elevation) → Task 2. ✓
- Live in-memory state + stale aging → Task 5. ✓
- FastAPI + WebSocket live feed + `/api/config` + `/healthz` → Task 6. ✓
- Leaflet live map, rotated markers, contacts list, dark theme → Task 7. ✓
- Binds 127.0.0.1, synthetic default, config-driven receiver → Tasks 1, 6. ✓
- Capture-to-replay workflow: `ReplaySource` + JSONL format defined (Task 4); the `flighttrack capture` *command* is deferred to Phase 4 (needs the Ubuntu box) — noted, not a Phase 1 gap.
- Deferred by phase (not gaps): SQLite/logging, stats, history playback, alerts, Web Push/PWA, systemd, tailscale serve.

**Placeholder scan:** none — every step has concrete code or an exact command.

**Type consistency:** `RawAircraft`/`AircraftView` field names are reused verbatim across Tasks 2–7; `parse_aircraft_json` shared by dump1090 + replay; `to_json()` shape (`now`/`receiver`/`aircraft`) matches what `app.js` reads and what `test_app`/`test_tracker` assert; `ConnectionManager.active`/`connect`/`broadcast` names match Task 6 tests.

**Review Focus coverage:**
- Position-less aircraft → `test_enrich_without_position_leaves_geometry_none` (T2), `test_positionless_excluded_from_json_but_in_snapshot` (T5), synthetic emits one (T3). ✓
- Source unreachable/malformed → `test_dump1090_source_swallows_errors` (T4); ingest loop try/except (T6). ✓
- Stale aging → `test_stale_aircraft_drop_out` (T5). ✓
- WS dead-socket drop → `test_broadcast_drops_dead_sockets` (T6). ✓
- Missing/invalid receiver config → `test_missing_receiver_exits` (T1). ✓
