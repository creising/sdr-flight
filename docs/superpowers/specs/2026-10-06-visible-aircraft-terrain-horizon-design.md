# Visible-aircraft indicator (terrain-aware horizon) — design

## Goal

Indicate on the live map which aircraft are **geometrically visible from the
receiver's house right now** — i.e. above the real terrain skyline in their
direction — not merely above a flat horizon. The receiver sits in mountainous
terrain (Weaverville, NC), so nearby ridges block low-elevation-angle views;
a flat-horizon test would wrongly flag planes hidden behind a mountain.

Success: a plane that is actually above the local skyline in its compass
direction is marked (glowing halo on the map icon + a `VISIBLE` badge in the
contacts list); a plane behind a ridge is not.

## Scope (v1)

In scope:
- Purely **geometric** line-of-sight above the terrain skyline. Works day or
  night (aircraft lights / contrails), so no daylight or weather gating.
- An **offline-precomputed** terrain horizon profile for the receiver site,
  shipped as a data file; the runtime check is a cheap comparison.
- Map halo + contacts-list/selected-card `VISIBLE` badge.

Explicitly out of scope (deferred, not v1):
- Daylight (sun-above-horizon) gating.
- Cloud / weather gating.
- A "show only visible" filter or sort toggle.
- Predicting *future* visibility along the track (this flags current state).

## Definition of "visible"

A positioned aircraft with a computed elevation angle is visible when:

```
elevation_deg > terrain_horizon_deg(bearing_deg)   AND   elevation_deg > 0
```

- `elevation_deg` and `bearing_deg` already come from `geometry.enrich()`.
  `elevation_deg` accounts for the observer's altitude vs the aircraft's.
- `terrain_horizon_deg(az)` is the maximum terrain elevation angle (the
  skyline) in that azimuth, from the precomputed profile.
- The "field of view looking up" is the entire sky **above** the terrain
  skyline — there is no upper cone limit (straight up is visible).

If no horizon profile is configured/loadable, the feature is **off**:
`visible` is always `False` and no indicator renders. We deliberately do NOT
fall back to a flat-horizon test, because in the mountains that would flag
nearly everything as visible and mislead.

## Components

### 1. Horizon generator — `scripts/build_horizon.py` (offline)

A standalone script (sibling of `scripts/import_faa.py`), run with `uv` on the
dev machine. Inputs (CLI args, defaulting from `config.yaml`):
- `--lat --lon --alt-m` — observer origin (receiver).
- `--radius-km` (default 40) — how far out to consider blocking terrain.
- `--az-step-deg` (default 1.0) — azimuth resolution (→ 360 samples).
- `--sample-step-m` (default 30) — along-ray sampling interval (~SRTM1 res).
- `--out` (default `data/horizon.json`).

Algorithm:
1. Determine which SRTM1 (~30 m, 1 arc-second) tiles cover the radius around
   the origin. Download each from the AWS Open Data "terrain tiles" dataset
   (`https://elevation-tiles-prod.s3.amazonaws.com/skadi/{Nxx}/{Nxx}{Wyyy}.hgt.gz`),
   no auth, gzipped `.hgt`. Cache locally; skip download if present.
2. Parse each tile into a 3601×3601 int16 elevation grid (big-endian), voids
   (-32768) treated as missing.
3. Build a bilinear sampler `elev(lat, lon)` over the mosaicked grid.
4. For each azimuth `az` in `[0, 360)` step `az_step_deg`:
   - Walk outward from the origin in `sample_step_m` increments to `radius_km`,
     projecting each step to a lat/lon (local equirectangular / destination
     point is fine at these distances).
   - For each terrain sample at ground distance `d` and elevation `h_terrain`,
     compute the apparent elevation angle from the observer:
     `angle = atan2( (h_terrain - h_obs) - drop(d), d )`
     where `drop(d) = d² / (2 · k · R_earth)` with `k ≈ 1.13` (standard visual
     refraction) corrects for Earth curvature so distant ridges are not
     overstated.
   - Keep the maximum angle over the ray; clamp to `>= 0` (sky is never below
     a flat horizon for visibility purposes; a downhill-all-the-way azimuth
     yields 0).
5. Write `data/horizon.json`:
   ```json
   {
     "origin": {"lat": 35.72, "lon": -82.56, "alt_m": 650},
     "radius_km": 40, "az_step_deg": 1.0,
     "horizon_deg": [ ... 360 values ... ]
   }
   ```

`numpy` is used for tile parsing and sampling. It is a generator-only
dependency (the server does not import it); added via `uv`.

### 2. Runtime horizon model — `flighttrack/horizon.py`

```
class Horizon:
    @classmethod
    def load(cls, path: str | None) -> "Horizon | None"   # None if absent/bad
    def obstruction_deg(self, bearing_deg: float) -> float # interpolated skyline
```

- `load` returns `None` on a missing path, missing file, or malformed JSON
  (logged once), so startup never fails on a bad/absent profile.
- `obstruction_deg` linearly interpolates between the two nearest azimuth
  samples (wrapping at 360°).

Config: optional `horizon.path` key (e.g. `data/horizon.json`). Loaded once at
app startup and handed to the `Tracker`.

### 3. Visibility calculation

- `models.AircraftView` gains `visible: bool = False`.
- `geometry.enrich(raw, receiver, horizon=None)` gains an optional `horizon`
  arg; after computing `bearing_deg`/`elevation_deg` it sets
  `v.visible = horizon is not None and v.elevation_deg is not None
   and v.elevation_deg > 0 and v.elevation_deg > horizon.obstruction_deg(v.bearing_deg)`.
- `Tracker` holds `self.horizon` (passed in `__init__`, default `None`) and
  passes it to `enrich`. The altitude-spike filter already runs before
  `enrich`, so `visible` is computed from the sanitized altitude.
- `Tracker.to_json()`'s `lean()` already serialises all non-`raw` fields, so
  `visible` flows to the websocket automatically.

### 4. Frontend indicator

- `map.js`: when `a.visible`, render a soft glowing halo on the icon —
  implemented as an extra SVG circle with a blur/soft stroke in the aircraft's
  altitude colour, visually distinct from the overhead ring (thin solid) and
  the selection ring (dashed). A CSS class drives the glow so it themes.
- `contacts.js`: a `VISIBLE` tag in the contacts row sub-line and on the
  selected/look-up card, styled like the existing `OVERHEAD` tag (reuse the
  `oh-tag` pattern with a distinct colour token).
- A plane may be both overhead and visible; both tags can show. Overhead
  (≥40° up) always implies visible, but the two are computed independently.

## Data flow

```
source.poll() → RawAircraft[]
  → Tracker.update(): spike-filter alt → enrich(raw, rx, horizon) → AircraftView{visible}
      → recorder (unchanged; ignores visible)
      → to_json() → websocket → live.js → map.js halo + contacts.js VISIBLE badge
```

No new HTTP endpoints. No DB changes (visibility is live-only, not persisted).

## Error handling / edge cases

- No/invalid `horizon.json` → `Horizon.load` returns `None` → feature off.
- Aircraft without a position or altitude → `visible` stays `False`.
- Tile download failure in the generator → clear error; the script exits
  non-zero and writes nothing (operator reruns; server keeps old profile).
- Horizon profile is origin-specific: if the receiver coords change, the
  profile is stale and must be regenerated. Documented with the coord-change
  procedure (README + deployment notes).

## Testing

- `tests/test_horizon.py` — `Horizon.obstruction_deg` interpolation incl.
  wrap-around at 360°; `load(None)`/missing/malformed → `None`.
- `tests/test_geometry.py` — `enrich` with a stub horizon: a plane above the
  skyline → `visible True`; the same geometry with a higher stub skyline →
  `False`; no horizon → `False`.
- `tests/test_build_horizon.py` — feed the ray/angle computation a tiny
  synthetic in-memory DEM: flat terrain → ~0° (allowing for curvature drop);
  a single known peak at a known distance → the expected blocking angle within
  tolerance. (No network; the DEM sampler is injected.)
- e2e (`tests/test_live_map_smoke.py`): start the app with a stub horizon that
  makes at least one synthetic aircraft visible; assert the halo element and a
  `VISIBLE` badge appear, and that a plane below the stub skyline shows neither.

## Operations

- Generate once on the dev Mac: `uv run python scripts/build_horizon.py`
  (reads `config.yaml` origin), producing `data/horizon.json`.
- Deploy: copy `data/horizon.json` to mercury's `~/sdr-flight/data/`, set
  `horizon.path` in mercury's `config.yaml`, restart `flighttrack`.
- Regenerate whenever the receiver coordinates change.
- `data/horizon.json` is small (~360 floats) and committed to the repo for the
  current site; the generator and raw DEM tiles are not committed (tiles are
  large and cacheable).
```
