import math
import pytest
from flighttrack.config import Receiver
from flighttrack.models import RawAircraft
from flighttrack import geometry as g
from flighttrack.horizon import Horizon


@pytest.fixture
def rx():
    return Receiver(lat=40.0, lon=-105.0, alt_m=1600.0)


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
