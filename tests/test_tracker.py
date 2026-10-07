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


def _alt(t, icao="aaa"):
    return {a.icao: a.alt_ft for a in t.snapshot()}[icao]


def test_altitude_spike_rejected_carries_forward(rx):
    # A single corrupt frame (30k -> 114k in ~1s) must not replace the real altitude.
    t = Tracker(rx, stale_timeout_s=60)
    t.update([raw("aaa", alt=30000)], now=100.0)
    t.update([raw("aaa", alt=114400)], now=101.0)
    assert _alt(t) == 30000


def test_reading_after_spike_is_accepted(rx):
    # After a rejected spike, the next plausible reading flows through normally.
    t = Tracker(rx, stale_timeout_s=60)
    t.update([raw("aaa", alt=30000)], now=100.0)
    t.update([raw("aaa", alt=114400)], now=101.0)   # rejected -> 30000
    t.update([raw("aaa", alt=30050)], now=102.0)
    assert _alt(t) == 30050


def test_normal_climb_is_accepted(rx):
    # A realistic climb (7000 ft over 120s ≈ 3500 fpm) is NOT a spike.
    t = Tracker(rx, stale_timeout_s=600)
    t.update([raw("aaa", alt=30000)], now=100.0)
    t.update([raw("aaa", alt=37000)], now=220.0)
    assert _alt(t) == 37000


def test_absurd_first_frame_dropped(rx):
    # No prior reading to compare, but the value is physically impossible -> dropped.
    t = Tracker(rx, stale_timeout_s=60)
    t.update([raw("aaa", alt=120000)], now=100.0)
    assert _alt(t) is None


def test_negative_absurd_altitude_dropped(rx):
    t = Tracker(rx, stale_timeout_s=60)
    t.update([raw("aaa", alt=-5000)], now=100.0)
    assert _alt(t) is None


def test_positionless_excluded_from_json_but_in_snapshot(rx):
    t = Tracker(rx, stale_timeout_s=30)
    noposn = RawAircraft(icao="ghost", callsign=None, lat=None, lon=None, alt_ft=None,
                         ground_speed_kt=None, track_deg=None, seen_s=0.0, rssi=-25.0)
    t.update([raw("aaa"), noposn], now=100.0)
    assert {a.icao for a in t.snapshot()} == {"aaa", "ghost"}
    j = t.to_json()
    assert [a["icao"] for a in j["aircraft"]] == ["aaa"]
    assert j["receiver"]["lat"] == 40.0


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
