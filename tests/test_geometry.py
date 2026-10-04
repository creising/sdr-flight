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
