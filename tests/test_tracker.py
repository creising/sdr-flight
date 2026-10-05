import pytest
from flighttrack.config import Receiver
from flighttrack.models import RawAircraft
from flighttrack.tracker import Tracker


@pytest.fixture
def rx():
    return Receiver(lat=40.0, lon=-105.0, alt_m=1600.0)


def raw(icao, lat=40.5, lon=-105.0, alt=30000, seen=0.0):
    return RawAircraft(icao=icao, callsign="T" + icao, lat=lat, lon=lon, alt_ft=alt,
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


def test_raw_for_and_to_json_excludes_raw(rx):
    t = Tracker(rx, stale_timeout_s=30)
    r = RawAircraft(icao="aaa", callsign="Taaa", lat=40.5, lon=-105.0, alt_ft=30000,
                    ground_speed_kt=400, track_deg=90, seen_s=0.0, rssi=-10.0,
                    raw={"hex": "aaa", "category": "A3", "squawk": "1200"})
    t.update([r], now=100.0)
    assert t.raw_for("aaa")["category"] == "A3"
    assert t.raw_for("zzz") is None
    j = t.to_json()
    assert "raw" not in j["aircraft"][0]   # the full stream stays lean


def test_positionless_excluded_from_json_but_in_snapshot(rx):
    t = Tracker(rx, stale_timeout_s=30)
    noposn = RawAircraft(icao="ghost", callsign=None, lat=None, lon=None, alt_ft=None,
                         ground_speed_kt=None, track_deg=None, seen_s=0.0, rssi=-25.0)
    t.update([raw("aaa"), noposn], now=100.0)
    assert {a.icao for a in t.snapshot()} == {"aaa", "ghost"}
    j = t.to_json()
    assert [a["icao"] for a in j["aircraft"]] == ["aaa"]
    assert j["receiver"]["lat"] == 40.0
