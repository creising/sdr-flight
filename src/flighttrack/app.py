from __future__ import annotations
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from flighttrack.config import Settings
from flighttrack.sources.factory import build_source
from flighttrack.tracker import Tracker

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
    interval = app.state.settings.poll_interval_s
    while True:
        try:
            raw = await source.poll()
            tracker.update(raw, now=time.time())
            await manager.broadcast(tracker.to_json())
        except Exception as e:
            log.warning("ingest iteration failed: %s", e)
        await asyncio.sleep(interval)


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.tracker = Tracker(settings.receiver, settings.stale_timeout_s)
        app.state.manager = ConnectionManager()
        app.state.source = build_source(settings)
        task = asyncio.create_task(_ingest_loop(app))
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            close = getattr(app.state.source, "aclose", None)
            if close is not None:
                await close()

    app = FastAPI(lifespan=lifespan)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "source": settings.source}

    @app.get("/api/config")
    def config():
        rx = settings.receiver
        return {"receiver": {"lat": rx.lat, "lon": rx.lon, "alt_m": rx.alt_m}}

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

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
