import asyncio
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from flighttrack.config import Settings, Receiver, SyntheticConfig
from flighttrack.app import create_app, ConnectionManager, _ingest_loop
from flighttrack.tracker import Tracker


@pytest.fixture
def client():
    s = Settings(source="synthetic", receiver=Receiver(lat=40.0, lon=-105.0, alt_m=1600.0),
                 synthetic=SyntheticConfig(num_aircraft=3, seed=1), poll_interval_s=0.05)
    app = create_app(s)
    with TestClient(app) as c:   # triggers startup -> ingest loop
        yield c


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["source"] == "synthetic"


def test_config_endpoint_exposes_receiver(client):
    r = client.get("/api/config")
    body = r.json()
    assert body["receiver"]["lat"] == 40.0


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]


def test_ws_live_sends_snapshot(client):
    with client.websocket_connect("/ws/live") as ws:
        msg = ws.receive_json()
        assert "aircraft" in msg and "receiver" in msg
        assert isinstance(msg["aircraft"], list)


async def test_broadcast_drops_dead_sockets():
    mgr = ConnectionManager()

    class DeadWS:
        async def send_text(self, _):
            raise RuntimeError("closed")

    class LiveWS:
        def __init__(self):
            self.sent = []

        async def send_text(self, t):
            self.sent.append(t)

    dead, live = DeadWS(), LiveWS()
    mgr.connect(dead)
    mgr.connect(live)
    await mgr.broadcast({"x": 1})
    assert live.sent and dead not in mgr.active


async def test_ingest_loop_continues_after_poll_error():
    """A source.poll() exception must be swallowed so the loop keeps running."""
    calls = {"n": 0}

    class FlakySource:
        async def poll(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return []

    app = SimpleNamespace(state=SimpleNamespace(
        source=FlakySource(),
        tracker=Tracker(Receiver(lat=0.0, lon=0.0)),
        manager=ConnectionManager(),
        settings=SimpleNamespace(poll_interval_s=0.01)))
    task = asyncio.create_task(_ingest_loop(app))
    await asyncio.sleep(0.05)
    task.cancel()
    assert calls["n"] >= 2  # survived the first exception and polled again


def test_lifespan_closes_source(monkeypatch):
    """On shutdown the lifespan must close a source that exposes aclose()."""
    class SpySource:
        def __init__(self):
            self.closed = False

        async def poll(self):
            return []

        async def aclose(self):
            self.closed = True

    spy = SpySource()
    monkeypatch.setattr("flighttrack.app.build_source", lambda s: spy)
    s = Settings(source="synthetic", receiver=Receiver(lat=40.0, lon=-105.0),
                 poll_interval_s=0.05)
    app = create_app(s)
    with TestClient(app):
        pass
    assert spy.closed


def test_loop_records_contacts_to_store():
    from flighttrack.config import Settings, Receiver, SyntheticConfig, DbConfig
    s = Settings(source="synthetic", receiver=Receiver(lat=40.0, lon=-105.0, alt_m=1600.0),
                 synthetic=SyntheticConfig(num_aircraft=3, seed=1), poll_interval_s=0.02,
                 db=DbConfig(path=":memory:"))
    app = create_app(s)
    import time as _t
    with TestClient(app) as c:
        _t.sleep(0.2)  # let the loop record a few ticks
        r = c.get("/api/stats/summary")
        assert r.status_code == 200
        assert r.json()["sessions_total"] >= 1


def test_history_endpoint_shape():
    import time as _t
    from flighttrack.config import Settings, Receiver, DbConfig
    s = Settings(source="synthetic", receiver=Receiver(lat=40.0, lon=-105.0),
                 poll_interval_s=0.02, db=DbConfig(path=":memory:"))
    app = create_app(s)
    with TestClient(app) as c:
        store = app.state.store
        # Seed within the retention window — the prune loop deletes positions older
        # than retention_days measured from real wall-clock now.
        base = _t.time()
        cid = store.open_contact("abc", "UAL1", ts=base)
        store.add_position(cid, base, 40.1, -105.1, 35000, 450, 270, -12.0)
        r = c.get("/api/history", params={"from": base - 100, "to": base + 100})
        assert r.status_code == 200
        body = [h for h in r.json() if h["icao"] == "abc"]
        assert body and body[0]["points"][0]["lat"] == 40.1


def test_flight_endpoint_caches(monkeypatch):
    from flighttrack.config import Settings, Receiver, DbConfig
    calls = {"n": 0}

    async def fake_fetch(callsign, client):
        calls["n"] += 1
        return {"callsign": callsign, "airline": "American Airlines",
                "origin": {"code": "PHL", "city": "Philadelphia", "name": "x"},
                "destination": {"code": "TPA", "city": "Tampa", "name": "y"},
                "aircraft_type": "A321", "registration": "N1",
                "route_known": True, "lookup_ok": True}

    async def no_photo(hex, client):
        return None

    monkeypatch.setenv("FLIGHTAWARE_API_KEY", "TESTKEY")   # enables the aero client
    monkeypatch.setattr("flighttrack.app.fetch_flight", fake_fetch)
    monkeypatch.setattr("flighttrack.app.fetch_photo", no_photo)
    s = Settings(source="synthetic", receiver=Receiver(lat=40.0, lon=-105.0),
                 poll_interval_s=0.02, db=DbConfig(path=":memory:"))
    app = create_app(s)
    with TestClient(app) as c:
        r1 = c.get("/api/flight/AAL2322", params={"hex": "ad4c2a"})
        assert r1.status_code == 200 and r1.json()["origin"]["code"] == "PHL"
        r2 = c.get("/api/flight/AAL2322", params={"hex": "ad4c2a"})
        assert r2.json()["destination"]["code"] == "TPA"
    assert calls["n"] == 1   # second request served from cache, not re-fetched


def test_flight_endpoint_does_not_cache_transient_failure(monkeypatch):
    from flighttrack.config import Settings, Receiver, DbConfig
    calls = {"n": 0}

    async def flaky_fetch(callsign, client):
        calls["n"] += 1
        return {"callsign": callsign, "route_known": False, "lookup_ok": False}  # transient error

    async def no_photo(hex, client):
        return None

    monkeypatch.setenv("FLIGHTAWARE_API_KEY", "TESTKEY")
    monkeypatch.setattr("flighttrack.app.fetch_flight", flaky_fetch)
    monkeypatch.setattr("flighttrack.app.fetch_photo", no_photo)
    s = Settings(source="synthetic", receiver=Receiver(lat=40.0, lon=-105.0),
                 poll_interval_s=0.02, db=DbConfig(path=":memory:"))
    app = create_app(s)
    with TestClient(app) as c:
        c.get("/api/flight/AAL1", params={"hex": "aa"})
        c.get("/api/flight/AAL1", params={"hex": "aa"})
    assert calls["n"] == 2   # transient failures are NOT cached -> retried every time


def test_flight_endpoint_merges_faa_and_photo(tmp_path, monkeypatch):
    from flighttrack.faa import build_faa_db
    from flighttrack.config import Settings, Receiver, DbConfig
    (tmp_path / "M.txt").write_text(
        "N-NUMBER,MFR MDL CODE,YEAR MFR,MODE S CODE HEX\n770TR,2072003,1979,AA6AC0\n")
    (tmp_path / "R.txt").write_text("CODE,MFR,MODEL\n2072003,FAIRCHILD,SA227-AC\n")
    faadb = str(tmp_path / "faa.db")
    build_faa_db(str(tmp_path / "M.txt"), str(tmp_path / "R.txt"), faadb)

    async def fake_route(callsign, client):
        return {"callsign": callsign, "route_known": True, "lookup_ok": True, "airline": "AA",
                "origin": {"code": "JFK"}, "destination": {"code": "LHR"},
                "aircraft_type": "B77W", "registration": None}

    async def fake_photo(hex, client):
        return {"thumbnail": "https://t/x.jpg", "link": "https://p/x", "credit": "Jane"}

    monkeypatch.setenv("FLIGHTAWARE_API_KEY", "K")
    monkeypatch.setattr("flighttrack.app.fetch_flight", fake_route)
    monkeypatch.setattr("flighttrack.app.fetch_photo", fake_photo)
    s = Settings(source="synthetic", receiver=Receiver(lat=40.0, lon=-105.0),
                 poll_interval_s=0.02, db=DbConfig(path=":memory:"), faa_db_path=faadb)
    app = create_app(s)
    with TestClient(app) as c:
        r = c.get("/api/flight/AAL100", params={"hex": "aa6ac0"}).json()
    assert r["make"] == "FAIRCHILD" and r["model"] == "SA227-AC" and r["year"] == "1979"
    assert r["registration"] == "N770TR"      # FAA fills in when route reg is missing
    assert r["photo"]["credit"] == "Jane"
    assert r["origin"]["code"] == "JFK"        # route still present


def test_buckets_endpoint():
    from flighttrack.config import Settings, Receiver, DbConfig
    s = Settings(source="synthetic", receiver=Receiver(lat=40.0, lon=-105.0),
                 poll_interval_s=0.02, db=DbConfig(path=":memory:"))
    app = create_app(s)
    with TestClient(app) as c:
        store = app.state.store
        store.open_contact("a", "UAL1", 100.0)
        r = c.get("/api/stats/buckets", params={"from": 100.0, "to": 200.0, "n": 1})
        assert r.status_code == 200 and r.json()[0]["count"] == 1


async def test_ingest_loop_survives_store_error():
    import asyncio
    from types import SimpleNamespace
    from flighttrack.app import _ingest_loop, ConnectionManager
    from flighttrack.config import Receiver

    class OkSource:
        async def poll(self):
            return []

    class BoomRecorder:
        def __init__(self):
            self.calls = 0

        def on_tick(self, views, now):
            self.calls += 1
            raise RuntimeError("disk full")

    rec = BoomRecorder()
    app = SimpleNamespace(state=SimpleNamespace(
        source=OkSource(), tracker=Tracker(Receiver(lat=0.0, lon=0.0)),
        manager=ConnectionManager(), recorder=rec,
        settings=SimpleNamespace(poll_interval_s=0.01)))
    task = asyncio.create_task(_ingest_loop(app))
    await asyncio.sleep(0.05)
    task.cancel()
    assert rec.calls >= 2  # kept looping despite the recorder raising each time
