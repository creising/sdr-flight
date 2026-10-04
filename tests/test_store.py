import pytest
from flighttrack.store import Store


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def test_empty_summary_is_null_safe(store):
    s = store.summary(now=1_000_000.0)
    assert s["sessions_total"] == 0
    assert s["closest"] is None and s["farthest"] is None
    assert s["highest_alt_ft"] is None


def test_empty_history_and_airlines(store):
    assert store.history(0.0, 10.0) == []
    assert store.top_airlines() == []
    buckets = store.contacts_per_hour(now=1_000_000.0, hours=3)
    assert len(buckets) == 3                       # 3 zero-filled hour buckets
    assert all(b["count"] == 0 for b in buckets)
    assert all(isinstance(b["label"], str) for b in buckets)


def test_contact_aggregates_and_position(store):
    cid = store.open_contact("abc", "UAL1", ts=100.0)
    store.update_contact(cid, 100.0, alt_ft=35000, distance_km=20.0, elevation_deg=30.0)
    store.update_contact(cid, 101.0, alt_ft=34000, distance_km=12.0, elevation_deg=45.0)
    store.add_position(cid, 100.0, 40.1, -105.1, 35000, 450, 270, -12.0)
    store.close_contact(cid)
    summ = store.summary(now=101.0)
    assert summ["sessions_total"] == 1
    assert summ["closest"]["km"] == pytest.approx(12.0)
    assert summ["highest_alt_ft"] == pytest.approx(35000)


def test_positionless_contact_has_no_points_in_history(store):
    cid = store.open_contact("ghost", None, ts=100.0)
    store.update_contact(cid, 100.0)  # no geometry
    store.close_contact(cid)
    assert store.history(0.0, 200.0) == []        # no positions -> not in history


def test_history_returns_points_in_window(store):
    cid = store.open_contact("abc", "UAL1", ts=100.0)
    store.add_position(cid, 100.0, 40.1, -105.1, 35000, 450, 270, -12.0)
    store.add_position(cid, 110.0, 40.2, -105.1, 35000, 450, 270, -12.0)
    store.add_position(cid, 999.0, 41.0, -105.1, 35000, 450, 270, -12.0)  # outside
    h = store.history(90.0, 120.0)
    assert len(h) == 1 and h[0]["icao"] == "abc"
    assert [p["lat"] for p in h[0]["points"]] == [40.1, 40.2]


def test_history_inverted_range_is_empty(store):
    cid = store.open_contact("abc", "UAL1", ts=100.0)
    store.add_position(cid, 100.0, 40.1, -105.1, 35000, 450, 270, -12.0)
    assert store.history(120.0, 90.0) == []


def test_top_airlines_counts_callsign_prefix(store):
    for cs in ["UAL1", "UAL2", "DAL9"]:
        store.open_contact(cs[:3].lower(), cs, ts=100.0)
    air = {a["airline"]: a["count"] for a in store.top_airlines()}
    assert air["UAL"] == 2 and air["DAL"] == 1


def test_prune_drops_old_positions_keeps_contacts(store):
    cid = store.open_contact("abc", "UAL1", ts=100.0)
    store.add_position(cid, 100.0, 40.1, -105.1, 35000, 450, 270, -12.0)
    store.add_position(cid, 500.0, 40.2, -105.1, 35000, 450, 270, -12.0)
    deleted = store.prune(before_ts=200.0)
    assert deleted == 1
    assert store.summary(now=500.0)["sessions_total"] == 1   # contact kept
    assert len(store.history(0.0, 1000.0)[0]["points"]) == 1
