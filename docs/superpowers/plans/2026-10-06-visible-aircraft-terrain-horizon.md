# Visible-aircraft terrain-horizon indicator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flag aircraft that are geometrically above the real terrain skyline as seen from the receiver, with a glowing map halo and a `VISIBLE` list badge.

**Architecture:** An offline script precomputes a per-site terrain skyline (max blocking elevation angle per azimuth) into `data/horizon.json`. At runtime a `Horizon` model loads it; `geometry.enrich()` sets `AircraftView.visible = elevation_deg > horizon.obstruction_deg(bearing_deg)`. The flag rides the existing websocket to the frontend, which renders a halo on the icon and a badge in the list. Feature is off (no false positives) when no profile is present.

**Tech Stack:** Python 3.12, pydantic, FastAPI, numpy (generator only), vanilla JS + Leaflet, pytest + pytest-playwright.

**Spec:** `docs/superpowers/specs/2026-10-06-visible-aircraft-terrain-horizon-design.md`

## Global Constraints

- All Python tooling runs through **`uv`** (`uv run pytest`, `uv run python …`, `uv add …`).
- `numpy` is a **generator-only** dependency; the server (`flighttrack/*`) must not import it.
- **Feature-off when no profile:** if `horizon.path` is unset or the file is missing/malformed, `visible` is always `False` and nothing renders. Never fall back to a flat-horizon test.
- Visibility uses a **strict** comparison: `elevation_deg > obstruction_deg(bearing)` **and** `elevation_deg > 0`.
- v1 is **geometric only** — no daylight, weather, or filter/sort toggles.
- Distances/data stay in their existing units; this feature adds no new units.
- Every commit message ends with the two attribution lines:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01LdyPuRnSeJCHwYk5aJGJy1`.
- e2e tests are marked `@pytest.mark.e2e` and run with `-m e2e`; default `uv run pytest` excludes them.

## Review Focus

- **Missing/malformed `horizon.json`** → `Horizon.load` returns `None`, feature off, no crash. (Task 1)
- **Azimuth interpolation wrap-around** at the 360°/0° seam. (Task 1)
- **Aircraft with no altitude or no position** → `visible` stays `False` even with a horizon loaded. (Task 2)
- **Plane exactly at the skyline angle** → not visible (strict `>`). (Task 2)
- **Distant flat terrain** → curvature/refraction yields a slightly negative angle that is clamped to 0, so flat ground never spuriously blocks. (Task 5)

---

### Task 1: Runtime horizon model

**Files:**
- Create: `src/flighttrack/horizon.py`
- Test: `tests/test_horizon.py`

**Interfaces:**
- Produces: `Horizon(az_step_deg: float, horizon_deg: list[float])`; classmethod `Horizon.load(path: str | None) -> Horizon | None`; method `obstruction_deg(bearing_deg: float) -> float`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_horizon.py
import json
from flighttrack.horizon import Horizon


def test_load_none_returns_none():
    assert Horizon.load(None) is None


def test_load_missing_file_returns_none(tmp_path):
    assert Horizon.load(str(tmp_path / "nope.json")) is None


def test_load_malformed_returns_none(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ not json")
    assert Horizon.load(str(p)) is None


def test_load_empty_profile_returns_none(tmp_path):
    p = tmp_path / "empty.json"
    p.write_text(json.dumps({"az_step_deg": 1.0, "horizon_deg": []}))
    assert Horizon.load(str(p)) is None


def test_load_valid(tmp_path):
    p = tmp_path / "h.json"
    p.write_text(json.dumps({"az_step_deg": 90.0, "horizon_deg": [0, 10, 20, 30]}))
    h = Horizon.load(str(p))
    assert h is not None and h.obstruction_deg(90.0) == 20.0


def test_obstruction_interpolates_and_wraps():
    h = Horizon(90.0, [0.0, 10.0, 20.0, 30.0])   # samples at 0,90,180,270
    assert h.obstruction_deg(0.0) == 0.0
    assert h.obstruction_deg(45.0) == 5.0         # halfway 0->10
    assert h.obstruction_deg(90.0) == 10.0
    assert h.obstruction_deg(315.0) == 15.0       # halfway 30->0 across the seam
    assert h.obstruction_deg(360.0) == 0.0        # wraps to 0
    assert h.obstruction_deg(-45.0) == 15.0       # negative bearing normalises
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_horizon.py -q`
Expected: FAIL — `ModuleNotFoundError: flighttrack.horizon`.

- [ ] **Step 3: Write the implementation**

```python
# src/flighttrack/horizon.py
from __future__ import annotations
import json
import logging

log = logging.getLogger(__name__)


class Horizon:
    """Terrain skyline: the max blocking elevation angle (deg) per azimuth,
    sampled every ``az_step_deg`` degrees starting at due north (0°)."""

    def __init__(self, az_step_deg: float, horizon_deg: list[float]):
        self._step = az_step_deg
        self._h = horizon_deg
        self._n = len(horizon_deg)

    @classmethod
    def load(cls, path: str | None) -> "Horizon | None":
        if not path:
            return None
        try:
            with open(path) as f:
                data = json.load(f)
            h = data["horizon_deg"]
            step = float(data["az_step_deg"])
            if not isinstance(h, list) or len(h) == 0 or step <= 0:
                raise ValueError("empty or invalid horizon profile")
            return cls(step, [float(x) for x in h])
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            log.warning("Horizon profile not loaded from %s: %s", path, e)
            return None

    def obstruction_deg(self, bearing_deg: float) -> float:
        """Linearly-interpolated skyline angle for a compass bearing, wrapping
        across the 0°/360° seam."""
        az = (bearing_deg % 360.0) / self._step
        i = int(az) % self._n
        j = (i + 1) % self._n
        frac = az - int(az)
        return self._h[i] + (self._h[j] - self._h[i]) * frac
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_horizon.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/flighttrack/horizon.py tests/test_horizon.py
git commit -m "feat: runtime terrain-horizon model with graceful load"
```

---

### Task 2: Visibility flag in the model and enrichment

**Files:**
- Modify: `src/flighttrack/models.py` (add `visible` to `AircraftView`)
- Modify: `src/flighttrack/geometry.py` (`enrich` gains a `horizon` arg)
- Test: `tests/test_geometry.py` (append)

**Interfaces:**
- Consumes: `Horizon.obstruction_deg` from Task 1.
- Produces: `AircraftView.visible: bool`; `enrich(raw, receiver, horizon=None) -> AircraftView`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_geometry.py  (append)
from flighttrack.horizon import Horizon
from flighttrack.models import RawAircraft


def _plane(alt_ft=35000, lat=40.05, lon=-105.0):
    return RawAircraft(icao="vis", callsign="VIS1", lat=lat, lon=lon, alt_ft=alt_ft,
                       ground_speed_kt=400, track_deg=90, seen_s=0.0, rssi=-10.0)


def test_visible_true_above_skyline(rx):
    # ~62° up; a 5° skyline everywhere -> visible
    v = g.enrich(_plane(), rx, Horizon(90.0, [5, 5, 5, 5]))
    assert v.elevation_deg > 5 and v.visible is True


def test_not_visible_below_skyline(rx):
    v = g.enrich(_plane(), rx, Horizon(90.0, [80, 80, 80, 80]))   # skyline higher than plane
    assert v.visible is False


def test_not_visible_without_horizon(rx):
    assert g.enrich(_plane(), rx).visible is False


def test_not_visible_without_altitude(rx):
    v = g.enrich(_plane(alt_ft=None), rx, Horizon(90.0, [0, 0, 0, 0]))
    assert v.elevation_deg is None and v.visible is False


def test_not_visible_without_position(rx):
    noposn = RawAircraft(icao="g", callsign=None, lat=None, lon=None, alt_ft=None,
                         ground_speed_kt=None, track_deg=None, seen_s=0.0, rssi=-20.0)
    assert g.enrich(noposn, rx, Horizon(90.0, [0, 0, 0, 0])).visible is False


def test_not_visible_exactly_at_skyline(rx):
    # Build a plane whose elevation equals the skyline angle; strict > means not visible.
    v0 = g.enrich(_plane(), rx)                      # compute its elevation
    v = g.enrich(_plane(), rx, Horizon(90.0, [v0.elevation_deg] * 4))
    assert v.visible is False
```

(The `rx` fixture and `g` import already exist at the top of `tests/test_geometry.py`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_geometry.py -q`
Expected: FAIL — `AircraftView` has no attribute `visible` / `enrich` takes no `horizon`.

- [ ] **Step 3: Add the model field**

In `src/flighttrack/models.py`, in `AircraftView`, add after `elevation_deg`:

```python
    visible: bool = False       # above the local terrain skyline (if a profile is loaded)
```

- [ ] **Step 4: Thread the horizon through `enrich`**

In `src/flighttrack/geometry.py`, change the signature and add the visibility calc:

```python
def enrich(raw: RawAircraft, receiver: Receiver, horizon=None) -> AircraftView:
    v = AircraftView(**raw.__dict__)
    if raw.lat is None or raw.lon is None:
        return v
    v.distance_km = haversine_km(receiver.lat, receiver.lon, raw.lat, raw.lon)
    v.bearing_deg = initial_bearing_deg(receiver.lat, receiver.lon, raw.lat, raw.lon)
    if raw.alt_ft is not None:
        v.elevation_deg = elevation_deg(v.distance_km, receiver.alt_m, raw.alt_ft * _FT_TO_M)
        if horizon is not None and v.elevation_deg > 0 \
                and v.elevation_deg > horizon.obstruction_deg(v.bearing_deg):
            v.visible = True
    return v
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_geometry.py -q`
Expected: PASS (new tests plus the existing ones).

- [ ] **Step 6: Commit**

```bash
git add src/flighttrack/models.py src/flighttrack/geometry.py tests/test_geometry.py
git commit -m "feat: compute aircraft visibility against the terrain horizon"
```

---

### Task 3: Config, tracker, and app wiring

**Files:**
- Modify: `src/flighttrack/config.py` (add `HorizonConfig`, `Settings.horizon`)
- Modify: `src/flighttrack/tracker.py` (`__init__` gains `horizon`, pass to `enrich`)
- Modify: `src/flighttrack/app.py` (load `Horizon`, pass to `Tracker`)
- Modify: `config.example.yaml` (document the `horizon` block)
- Test: `tests/test_tracker.py` (append)

**Interfaces:**
- Consumes: `Horizon` (Task 1), `enrich(..., horizon)` (Task 2).
- Produces: `Tracker(receiver, stale_timeout_s=30.0, horizon=None)`; `Settings.horizon.path: str | None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_tracker.py  (append)
from flighttrack.horizon import Horizon


def test_visible_flows_to_snapshot_and_json(rx):
    t = Tracker(rx, stale_timeout_s=30, horizon=Horizon(90.0, [0, 0, 0, 0]))
    t.update([raw("aaa", lat=40.05, alt=35000)], now=100.0)
    assert t.snapshot()[0].visible is True
    assert t.to_json()["aircraft"][0]["visible"] is True


def test_no_horizon_means_not_visible(rx):
    t = Tracker(rx, stale_timeout_s=30)            # default horizon=None
    t.update([raw("aaa", lat=40.05, alt=35000)], now=100.0)
    assert t.snapshot()[0].visible is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_tracker.py -q`
Expected: FAIL — `Tracker.__init__` has no `horizon` keyword.

- [ ] **Step 3: Add the config model**

In `src/flighttrack/config.py`, add a model and field:

```python
class HorizonConfig(BaseModel):
    path: str | None = None   # data/horizon.json, built by scripts/build_horizon.py
```

and inside `Settings`, next to `faa_db_path`:

```python
    horizon: HorizonConfig = HorizonConfig()
```

- [ ] **Step 4: Thread the horizon through the tracker**

In `src/flighttrack/tracker.py`:

```python
    def __init__(self, receiver: Receiver, stale_timeout_s: float = 30.0, horizon=None):
        self.rx = receiver
        self.stale = stale_timeout_s
        self.horizon = horizon
        self._live: dict[str, tuple[float, AircraftView]] = {}
        self._last_alt: dict[str, tuple[float, float]] = {}
        self._now = 0.0
```

and in `update`, change the enrich call:

```python
            self._live[r.icao] = (now, enrich(r, self.rx, self.horizon))
```

- [ ] **Step 5: Load the horizon at startup**

In `src/flighttrack/app.py`, add the import near the other `flighttrack` imports:

```python
from flighttrack.horizon import Horizon
```

and change the tracker construction in `lifespan`:

```python
        app.state.tracker = Tracker(settings.receiver, settings.stale_timeout_s,
                                    horizon=Horizon.load(settings.horizon.path))
```

- [ ] **Step 6: Document the config block**

In `config.example.yaml`, add:

```yaml
# Optional terrain skyline for the "visible from here" indicator.
# Build with: uv run python scripts/build_horizon.py
# horizon:
#   path: data/horizon.json
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_tracker.py tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/flighttrack/config.py src/flighttrack/tracker.py src/flighttrack/app.py config.example.yaml tests/test_tracker.py
git commit -m "feat: load terrain horizon from config and feed the tracker"
```

---

### Task 4: Frontend indicator (halo + VISIBLE badge)

**Files:**
- Modify: `src/flighttrack/static/js/map.js` (`icon()` halo)
- Modify: `src/flighttrack/static/js/contacts.js` (row badge + card badge)
- Modify: `src/flighttrack/static/css/app.css` (`.vis-tag`, `.lk-vis`, `.ac-halo`)
- Test: `tests/test_live_map_smoke.py` (append, e2e)

**Interfaces:**
- Consumes: `aircraft[].visible` from the websocket payload (Task 3).

- [ ] **Step 1: Write the failing e2e test**

```python
# tests/test_live_map_smoke.py  (append)
from flighttrack.horizon import Horizon


def test_visible_indicator_renders(server, page):
    url, app = server
    # Flat skyline -> every positioned synthetic plane above the receiver is "visible".
    app.state.tracker.horizon = Horizon(90.0, [0, 0, 0, 0])
    page.goto(url)
    page.wait_for_selector(".ac-marker", timeout=8000)
    page.wait_for_selector(".ac-halo", timeout=8000)          # glow on the map
    assert page.locator(".vis-tag").count() >= 1              # VISIBLE badge in the list
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_live_map_smoke.py::test_visible_indicator_renders -q -m e2e`
Expected: FAIL — `.ac-halo` never appears.

- [ ] **Step 3: Add the halo in `map.js`**

In `src/flighttrack/static/js/map.js`, inside `icon(a, opts = {})`, after the `sel` ring is built and before the `return`, add:

```javascript
  const halo = a.visible
    ? `<circle cx="17" cy="17" r="16" fill="${color}" opacity="0.18" class="ac-halo"/>`
    : "";
```

and put `${halo}` first inside the `<svg>` so it sits behind the marker:

```javascript
      `<svg width="34" height="34" viewBox="0 0 34 34">${halo}${ring}${sel}` +
```

- [ ] **Step 4: Add the badges in `contacts.js`**

In `renderContacts`, next to the existing `oh` tag (the overhead tag), add a visible tag and include it in the row sub-line:

```javascript
    const vis = a.visible
      ? `<span class="vis-tag cond">VISIBLE</span> ` : "";
```

```javascript
        <span class="c-sub">${oh}${vis}</span>
```

In `cardShell`, add an empty span inside `.lk-top-right`, right before the close button logic:

```javascript
      <span class="lk-top-right"><span class="lk-vis cond"></span><span class="cond lk-dir"></span>${
```

In `updateTelemetry(el, s)`, after the `.lk-dir` is set, keep the card badge in sync:

```javascript
  const visEl = q(".lk-vis"); if (visEl) visEl.textContent = s.visible ? "VISIBLE" : "";
```

- [ ] **Step 5: Style the badges in `app.css`**

Add near the existing `.oh-tag` rule (reuse its shape, distinct colour):

```css
.vis-tag, .lk-vis { font-size: 10px; font-weight: 600; letter-spacing: .1em;
  color: var(--bg); background: oklch(0.82 0.13 195); border-radius: 4px; padding: 1px 5px; }
.lk-vis:empty { display: none; }
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/test_live_map_smoke.py::test_visible_indicator_renders -q -m e2e`
Expected: PASS.

- [ ] **Step 7: Run the frontend smoke suite for regressions**

Run: `uv run pytest tests/test_live_map_smoke.py tests/test_contacts_smoke.py -q -m e2e`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/flighttrack/static/js/map.js src/flighttrack/static/js/contacts.js src/flighttrack/static/css/app.css tests/test_live_map_smoke.py
git commit -m "feat: show a halo and VISIBLE badge for visible aircraft"
```

---

### Task 5: Offline horizon generator

**Files:**
- Create: `scripts/build_horizon.py`
- Test: `tests/test_build_horizon.py`
- Modify: `pyproject.toml` (add `numpy` via `uv add numpy`)

**Interfaces:**
- Produces: `compute_horizon(sample_elev, origin_lat, origin_lon, obs_alt_m, radius_km, az_step_deg, sample_step_m) -> list[float]` — pure, network-free, injectable elevation sampler `sample_elev(lat, lon) -> float` (metres).

- [ ] **Step 1: Add numpy (generator-only dependency)**

Run: `uv add numpy`
Then confirm the server does not import it: `grep -rn "import numpy" src/flighttrack` returns nothing.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_build_horizon.py
import math
import importlib.util
from pathlib import Path

# Load the script module by path (scripts/ is not a package).
_spec = importlib.util.spec_from_file_location(
    "build_horizon", Path(__file__).resolve().parents[1] / "scripts" / "build_horizon.py")
build_horizon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_horizon)


def test_flat_terrain_is_zero():
    # Observer at 100 m over flat 100 m terrain: every azimuth clamps to 0.
    h = build_horizon.compute_horizon(
        lambda lat, lon: 100.0, 40.0, -105.0, obs_alt_m=100.0,
        radius_km=10, az_step_deg=90.0, sample_step_m=100.0)
    assert len(h) == 4
    assert all(abs(a) < 1e-6 for a in h)


def test_single_peak_blocks_its_azimuth():
    # A 2000 m peak ~5 km due east (az 90°); 100 m elsewhere; observer at 100 m.
    peak_lat, peak_lon = 40.0, -105.0 + 5000.0 / (111320.0 * math.cos(math.radians(40.0)))

    def sample(lat, lon):
        d = math.hypot((lat - peak_lat) * 111320.0,
                       (lon - peak_lon) * 111320.0 * math.cos(math.radians(40.0)))
        return 2000.0 if d < 150.0 else 100.0

    h = build_horizon.compute_horizon(
        sample, 40.0, -105.0, obs_alt_m=100.0,
        radius_km=10, az_step_deg=90.0, sample_step_m=100.0)
    east = h[1]   # azimuths 0,90,180,270 -> index 1 is 90° (east)
    drop = 5000.0 ** 2 / (2 * 1.13 * 6371000.0)
    expected = math.degrees(math.atan2((2000.0 - 100.0) - drop, 5000.0))
    assert abs(east - expected) < 1.0           # within a degree of the analytic value
    assert h[0] < 1e-6 and h[2] < 1e-6 and h[3] < 1e-6   # other directions flat
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_build_horizon.py -q`
Expected: FAIL — `scripts/build_horizon.py` does not exist.

- [ ] **Step 4: Write the generator**

```python
# scripts/build_horizon.py
"""Build a terrain skyline (max blocking elevation angle per azimuth) for the
receiver, from SRTM1 (~30 m) elevation tiles on the AWS Open Data "terrain
tiles" dataset. Output: data/horizon.json. Run with `uv run python`.

Regenerate whenever the receiver coordinates change."""
from __future__ import annotations
import argparse
import gzip
import json
import math
import os
import sys
import urllib.request

_R_EARTH_M = 6371000.0
_REFRACTION_K = 1.13          # standard visual refraction (effective-radius factor)
_SKADI = "https://elevation-tiles-prod.s3.amazonaws.com/skadi/{ns}{lat:02d}/{ns}{lat:02d}{ew}{lon:03d}.hgt.gz"


def compute_horizon(sample_elev, origin_lat, origin_lon, obs_alt_m,
                    radius_km, az_step_deg, sample_step_m):
    """Return [max blocking elevation angle (deg)] per azimuth, clamped to >= 0.

    ``sample_elev(lat, lon) -> metres`` is injected so this is testable without
    any network or file access."""
    coslat = math.cos(math.radians(origin_lat))
    radius_m = radius_km * 1000.0
    n = int(round(360.0 / az_step_deg))
    out = []
    for k in range(n):
        az = math.radians(k * az_step_deg)
        best = 0.0
        d = sample_step_m
        while d <= radius_m:
            lat2 = origin_lat + (d * math.cos(az)) / 111320.0
            lon2 = origin_lon + (d * math.sin(az)) / (111320.0 * coslat)
            h = sample_elev(lat2, lon2)
            if h is not None:
                drop = d * d / (2.0 * _REFRACTION_K * _R_EARTH_M)
                ang = math.degrees(math.atan2((h - obs_alt_m) - drop, d))
                if ang > best:
                    best = ang
            d += sample_step_m
        out.append(best)
    return out


def _tile_name(lat, lon):
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return ns, abs(int(math.floor(lat))), ew, abs(int(math.floor(lon)))


def _load_tiles(origin_lat, origin_lon, radius_km, cache_dir):
    """Download + parse the SRTM1 tiles covering the radius into a dict of
    {(tile_lat, tile_lon): numpy int16 grid}. 3601x3601, 1 arc-second."""
    import numpy as np
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * math.cos(math.radians(origin_lat)))
    tiles = {}
    lat = int(math.floor(origin_lat - dlat))
    while lat <= int(math.floor(origin_lat + dlat)):
        lon = int(math.floor(origin_lon - dlon))
        while lon <= int(math.floor(origin_lon + dlon)):
            ns, la, ew, lo = _tile_name(lat + 0.0, lon + 0.0)
            fname = f"{ns}{la:02d}{ew}{lo:03d}.hgt"
            path = os.path.join(cache_dir, fname)
            if not os.path.exists(path):
                url = _SKADI.format(ns=ns, lat=la, ew=ew, lon=lo)
                print(f"downloading {url}")
                with urllib.request.urlopen(url, timeout=60) as r:
                    raw = gzip.decompress(r.read())
                os.makedirs(cache_dir, exist_ok=True)
                with open(path, "wb") as f:
                    f.write(raw)
            grid = np.frombuffer(open(path, "rb").read(), dtype=">i2").astype("float32")
            grid = grid.reshape(3601, 3601)
            grid[grid == -32768] = float("nan")
            tiles[(lat, lon)] = grid
            lon += 1
        lat += 1
    return tiles


def _make_sampler(tiles):
    """Bilinear elevation sampler over the mosaicked SRTM1 grids."""
    import numpy as np

    def sample(lat, lon):
        tlat, tlon = int(math.floor(lat)), int(math.floor(lon))
        grid = tiles.get((tlat, tlon))
        if grid is None:
            return None
        # row 0 is the north edge (tlat+1); 3600 steps per degree.
        y = (tlat + 1 - lat) * 3600.0
        x = (lon - tlon) * 3600.0
        y0, x0 = int(math.floor(y)), int(math.floor(x))
        if not (0 <= y0 < 3600 and 0 <= x0 < 3600):
            return None
        fy, fx = y - y0, x - x0
        g = grid
        v = (g[y0, x0] * (1 - fy) * (1 - fx) + g[y0, x0 + 1] * (1 - fy) * fx
             + g[y0 + 1, x0] * fy * (1 - fx) + g[y0 + 1, x0 + 1] * fy * fx)
        return None if np.isnan(v) else float(v)

    return sample


def main() -> None:
    ap = argparse.ArgumentParser(description="Build data/horizon.json for the receiver.")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--alt-m", type=float)
    ap.add_argument("--radius-km", type=float, default=40.0)
    ap.add_argument("--az-step-deg", type=float, default=1.0)
    ap.add_argument("--sample-step-m", type=float, default=30.0)
    ap.add_argument("--out", default="data/horizon.json")
    ap.add_argument("--cache-dir", default=".srtm_cache")
    args = ap.parse_args()

    lat, lon, alt = args.lat, args.lon, args.alt_m
    if lat is None or lon is None or alt is None:
        import yaml
        with open(args.config) as f:
            rx = (yaml.safe_load(f) or {}).get("receiver", {})
        lat = lat if lat is not None else rx["lat"]
        lon = lon if lon is not None else rx["lon"]
        alt = alt if alt is not None else rx.get("alt_m", 0.0)

    tiles = _load_tiles(lat, lon, args.radius_km, args.cache_dir)
    if not tiles:
        sys.exit("No elevation tiles available for that location.")
    horizon = compute_horizon(_make_sampler(tiles), lat, lon, alt,
                              args.radius_km, args.az_step_deg, args.sample_step_m)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump({"origin": {"lat": lat, "lon": lon, "alt_m": alt},
                   "radius_km": args.radius_km, "az_step_deg": args.az_step_deg,
                   "horizon_deg": [round(a, 3) for a in horizon]}, f)
    print(f"wrote {args.out}: {len(horizon)} azimuths, "
          f"max skyline {max(horizon):.1f}°")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_build_horizon.py -q`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add scripts/build_horizon.py tests/test_build_horizon.py pyproject.toml uv.lock
git commit -m "feat: offline terrain-horizon generator from SRTM tiles"
```

---

### Task 6: Generate the profile and wire it on mercury (manual / ops)

**Files:**
- Create (generated, committed): `data/horizon.json`
- Modify: `README.md` (one line under the receiver-coordinates note)

- [ ] **Step 1: Generate the profile for the live receiver coordinates**

Run (uses mercury's exact coords; do not rely on the repo's dev config):

```bash
uv run python scripts/build_horizon.py --lat 35.72089558089826 --lon -82.55515870972845 --alt-m 650 --out data/horizon.json
```

Expected: prints the tile download(s) and `wrote data/horizon.json: 360 azimuths, max skyline <N>°`. Sanity-check that the max skyline is a plausible mountain angle (a few degrees to ~15°), not 0 and not absurd.

- [ ] **Step 2: Full test run**

Run: `uv run pytest -q && uv run pytest -q -m e2e`
Expected: all pass.

- [ ] **Step 3: Commit the generated profile**

```bash
git add data/horizon.json README.md
git commit -m "feat: ship terrain horizon profile for the receiver site"
```

- [ ] **Step 4: Deploy to mercury**

```bash
scp data/horizon.json ChrisKraft@100.81.4.41:~/sdr-flight/data/horizon.json
# Append a top-level horizon block only if one isn't already present.
ssh ChrisKraft@100.81.4.41 "cd ~/sdr-flight && grep -q '^horizon:' config.yaml || printf '\nhorizon:\n  path: data/horizon.json\n' >> config.yaml"
```

Then confirm `config.yaml` on mercury has a top-level `horizon:` block with `path: data/horizon.json`, and restart:

```bash
ssh root@100.81.4.41 "systemctl restart flighttrack && sleep 1 && systemctl is-active flighttrack"
```

- [ ] **Step 5: Verify live**

Confirm the websocket payload now carries `visible` and at least one aircraft currently above the skyline shows the halo/badge (spot-check against the live map). Note in `README.md` that `data/horizon.json` must be regenerated when the receiver moves.

---

## Notes for the executor

- The `data/horizon.json` committed in Task 6 matches the **deployed** receiver coordinates, not the repo's dev `config.yaml` (which still holds approximate synthetic-dev coords).
- Tasks 1–5 are pure code + tests and fully covered by the suite; Task 6 is manual ops (network download + remote deploy) and is not gated by automated tests.
