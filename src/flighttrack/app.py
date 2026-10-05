from __future__ import annotations
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from flighttrack.config import Settings
from flighttrack.sources.factory import build_source
from flighttrack.tracker import Tracker
import httpx
from flighttrack.store import Store
from flighttrack.recorder import Recorder
from flighttrack.enrichment import fetch_flight

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"


class ConnectionManager:
    def __init__(self) -> None:
        self.active: set[WebSocket] = set()

    def connect(self, ws: WebSocket) -> None:
        self.active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.active.discard(ws)

    async def broadcast(self, data: dict) -> None:
        text = json.dumps(data)
        for ws in list(self.active):
            try:
                await ws.send_text(text)
            except Exception:
                self.active.discard(ws)


async def _ingest_loop(app: FastAPI) -> None:
    source = app.state.source
    tracker: Tracker = app.state.tracker
    manager: ConnectionManager = app.state.manager
    recorder = getattr(app.state, "recorder", None)
    interval = app.state.settings.poll_interval_s
    while True:
        try:
            raw = await source.poll()
            now = time.time()
            tracker.update(raw, now=now)
            if recorder is not None:
                await asyncio.to_thread(recorder.on_tick, tracker.snapshot(), now)
            await manager.broadcast(tracker.to_json())
        except Exception as e:
            log.warning("ingest iteration failed: %s", e)
        await asyncio.sleep(interval)


async def _prune_loop(app: FastAPI) -> None:
    store = app.state.store
    retention_s = app.state.settings.logging.retention_days * 86400
    while True:
        try:
            await asyncio.to_thread(store.prune, time.time() - retention_s)
        except Exception as e:
            log.warning("prune failed: %s", e)
        await asyncio.sleep(3600)


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.tracker = Tracker(settings.receiver, settings.stale_timeout_s)
        app.state.manager = ConnectionManager()
        app.state.source = build_source(settings)
        app.state.store = Store(settings.db.path)
        app.state.recorder = Recorder(app.state.store, settings.logging.snapshot_interval_s)
        app.state.enrich_client = httpx.AsyncClient(timeout=6.0)
        tasks = [asyncio.create_task(_ingest_loop(app)),
                 asyncio.create_task(_prune_loop(app))]
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            for t in tasks:
                try:
                    await t
                except asyncio.CancelledError:
                    pass
            close = getattr(app.state.source, "aclose", None)
            if close is not None:
                await close()
            await app.state.enrich_client.aclose()
            app.state.store.close()

    app = FastAPI(lifespan=lifespan)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "source": settings.source}

    @app.get("/api/config")
    def config():
        rx = settings.receiver
        return {"receiver": {"lat": rx.lat, "lon": rx.lon, "alt_m": rx.alt_m}}

    @app.get("/api/stats/summary")
    async def stats_summary():
        return await asyncio.to_thread(app.state.store.summary, time.time())

    @app.get("/api/stats/per-hour")
    async def stats_per_hour():
        return await asyncio.to_thread(app.state.store.contacts_per_hour, time.time(), 24)

    @app.get("/api/stats/airlines")
    async def stats_airlines():
        return await asyncio.to_thread(app.state.store.top_airlines, 8)

    @app.get("/api/stats/buckets")
    async def stats_buckets(from_: float = Query(..., alias="from"),
                            to: float = Query(...), n: int = Query(96)):
        return await asyncio.to_thread(app.state.store.contacts_buckets, from_, to, n)

    @app.get("/api/history")
    async def history(from_: float = Query(..., alias="from"), to: float = Query(...)):
        return await asyncio.to_thread(app.state.store.history, from_, to)

    @app.get("/api/flight/{callsign}")
    async def flight(callsign: str, hex: str = Query("")):
        store = app.state.store
        key = f"{callsign}|{hex}"
        now = time.time()
        cached = await asyncio.to_thread(store.get_cached_flight, key, now)
        if cached is not None:
            data, age = cached
            ttl = 7 * 86400 if data.get("route_known") else 1800   # not-found refreshes every 30 min
            if age <= ttl:
                return data
        data = await fetch_flight(callsign, hex or None, app.state.enrich_client)
        if data.get("lookup_ok"):          # only cache definitive answers, never transient failures
            await asyncio.to_thread(store.put_cached_flight, key, data, now)
        return data

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/stats")
    def stats_page():
        return FileResponse(STATIC / "stats.html")

    @app.websocket("/ws/live")
    async def ws_live(ws: WebSocket):
        await ws.accept()
        mgr: ConnectionManager = app.state.manager
        mgr.connect(ws)
        try:
            await ws.send_text(json.dumps(app.state.tracker.to_json()))
            while True:
                await ws.receive_text()  # keepalive / ignore client msgs
        except WebSocketDisconnect:
            pass
        finally:
            mgr.disconnect(ws)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
