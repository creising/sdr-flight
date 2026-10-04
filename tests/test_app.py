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
