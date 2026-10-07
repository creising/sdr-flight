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
