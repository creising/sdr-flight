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


def observer_elevation(sample_elev, lat, lon, obs_agl_m, fallback_m):
    """Observer elevation (m): DEM ground at the origin + antenna height,
    falling back to a passed MSL value only when the DEM has no sample there."""
    ground = sample_elev(lat, lon)
    base = ground if ground is not None else fallback_m
    return base + obs_agl_m


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
    ap.add_argument("--obs-agl-m", type=float, default=8.0,
                    help="antenna height above ground level (m)")
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
    sampler = _make_sampler(tiles)
    ground = sampler(lat, lon)
    obs_elev = observer_elevation(sampler, lat, lon, args.obs_agl_m, alt)
    horizon = compute_horizon(sampler, lat, lon, obs_elev,
                              args.radius_km, args.az_step_deg, args.sample_step_m)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump({"origin": {"lat": lat, "lon": lon, "alt_m": obs_elev,
                              "ground_m": ground, "obs_agl_m": args.obs_agl_m},
                   "radius_km": args.radius_km, "az_step_deg": args.az_step_deg,
                   "horizon_deg": [round(a, 3) for a in horizon]}, f)
    print(f"wrote {args.out}: {len(horizon)} azimuths, "
          f"max skyline {max(horizon):.1f}°")


if __name__ == "__main__":
    main()
