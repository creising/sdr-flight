import pytest
from flighttrack.models import AircraftView
from flighttrack.store import Store
from flighttrack.recorder import Recorder


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def view(icao, lat=40.1, lon=-105.1, alt=35000, dist=20.0, elev=30.0, cs=None):
    return AircraftView(icao=icao, callsign=cs or ("T" + icao), lat=lat, lon=lon,
                        alt_ft=alt, ground_speed_kt=450, track_deg=270, seen_s=0.0,
                        rssi=-12.0, distance_km=dist, bearing_deg=0.0, elevation_deg=elev)


def test_opens_contact_and_records_position(store):
    r = Recorder(store, snapshot_interval_s=0.0)
    r.on_tick([view("abc")], now=100.0)
    assert store.summary(now=100.0)["sessions_total"] == 1
    assert len(store.history(0.0, 200.0)[0]["points"]) == 1


def test_position_snapshot_is_throttled(store):
    r = Recorder(store, snapshot_interval_s=15.0)
    r.on_tick([view("abc")], now=100.0)
    r.on_tick([view("abc")], now=105.0)   # within interval -> no new point
    r.on_tick([view("abc")], now=120.0)   # 20s later -> new point
    pts = store.history(0.0, 200.0)[0]["points"]
    assert len(pts) == 2


def test_absent_icao_closes_and_reappearance_opens_new(store):
    r = Recorder(store, snapshot_interval_s=0.0)
    r.on_tick([view("abc")], now=100.0)
    r.on_tick([], now=130.0)               # abc gone -> closed
    r.on_tick([view("abc")], now=200.0)    # reappears -> NEW session
    assert store.summary(now=200.0)["sessions_total"] == 2


def test_positionless_view_opens_contact_without_points(store):
    r = Recorder(store, snapshot_interval_s=0.0)
    pl = AircraftView(icao="ghost", callsign=None, lat=None, lon=None, alt_ft=None,
                      ground_speed_kt=None, track_deg=None, seen_s=0.0, rssi=-25.0)
    r.on_tick([pl], now=100.0)
    assert store.summary(now=100.0)["sessions_total"] == 1
    assert store.history(0.0, 200.0) == []
