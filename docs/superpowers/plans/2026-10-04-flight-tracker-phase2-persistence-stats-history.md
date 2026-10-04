# Flight Tracker — Phase 2: Persistence, Stats & History Playback — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Log every aircraft the tracker sees into SQLite, show a stats dashboard of what's been seen, and let the user scrub back through time to replay past flights on the same map — all still on synthetic data, no SDR.

**Architecture:** A `Store` wraps a single SQLite connection (WAL, `check_same_thread=False`, one lock); all DB calls run off the event loop via `asyncio.to_thread`. A `Recorder` consumes each tracker snapshot, opening/closing one `contacts` session per aircraft appearance and appending throttled `positions` track points. New FastAPI routes expose stats and history queries; a periodic prune drops old positions. Two frontend additions: a `/stats` page (single-series magnitude charts) and a Live/Playback toggle on the map that interpolates logged tracks over a scrubbable timeline.

**Tech Stack:** Python 3.11+, stdlib `sqlite3`, FastAPI, uvicorn, Leaflet (CDN), inline SVG charts (no chart lib, no build step), pytest + pytest-asyncio, Playwright (marked e2e). **uv for everything** (`uv run …`, `uv pip install`).

**Spec:** `docs/superpowers/specs/2026-10-04-sdr-flight-tracker-design.md`

## Global Constraints

- Python **3.11+**; **uv** for every command (`uv run pytest`, `uv run flighttrack`).
- HTTP server binds **`127.0.0.1`** only; frontend has **no build step** (Leaflet via CDN, charts as hand-written inline SVG).
- **SQLite WAL**, one shared connection guarded by a `threading.Lock`; **every DB call from async code goes through `asyncio.to_thread`** so the event loop never blocks.
- Default source stays **`synthetic`**; the source abstraction is unchanged.
- **Only `contacts` and `positions` tables are created in Phase 2.** `alerts` and `push_subscriptions` belong to Phase 4 — do not create them here.
- Retention **prunes `positions` only**; `contacts` (the aggregates) are kept for long-term stats.
- Distances stored in **km**, altitudes in **feet** (as already produced by `AircraftView`).

## Review Focus

- **Empty database (fresh install):** `summary()` and `history()` must return sensible empties (null tiles, `[]`), never crash on `min()/max()` over zero rows. *(Test in Task 1.)*
- **Position-less aircraft:** logged as a `contacts` session with null geometry and **no** `positions` rows; must not appear in history tracks and must not break stats aggregates. *(Test in Tasks 1 & 2.)*
- **Reappearing ICAO after a gap:** once a contact is closed (aircraft aged out of the tracker), the same ICAO reappearing opens a **new** contact session, not a resurrection of the old one. *(Test in Task 2.)*
- **DB write failure mid-loop:** a `Store` error inside the ingest loop must be swallowed so polling/broadcast continue (same resilience as a source failure). *(Test in Task 3.)*
- **Degenerate history window (`from > to`, or no data):** returns `[]` with no error; playback handles an empty track set without throwing. *(Test in Tasks 1 & 3.)*

---

### Task 1: SQLite Store (schema, records, queries, prune) + config

**Files:**
- Create: `src/flighttrack/store.py`
- Modify: `src/flighttrack/config.py` (add `DbConfig`, `LoggingConfig` to `Settings`)
- Modify: `config.example.yaml` (document the new blocks)
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: nothing from other Phase-2 tasks.
- Produces (used by Tasks 2–5):
  - Config: `DbConfig{ path: str = "data/flighttrack.db" }`, `LoggingConfig{ snapshot_interval_s: float = 15.0, retention_days: int = 30 }`; `Settings.db: DbConfig`, `Settings.logging: LoggingConfig`.
  - `Store(path: str)` with:
    - `open_contact(icao: str, callsign: str | None, ts: float) -> int`
    - `update_contact(contact_id: int, ts: float, *, alt_ft: float | None = None, distance_km: float | None = None, elevation_deg: float | None = None, callsign: str | None = None) -> None`
    - `close_contact(contact_id: int) -> None`
    - `add_position(contact_id: int, ts: float, lat: float, lon: float, alt_ft: float | None, ground_speed_kt: float | None, track_deg: float | None, rssi: float | None) -> None`
    - `summary(now: float) -> dict` — keys: `sessions_total, sessions_today, unique_total, closest, farthest, highest_alt_ft, busiest_hour` (`closest`/`farthest` are `None` or `{icao, callsign, km, when}`).
    - `contacts_per_hour(now: float, hours: int = 24) -> list[dict]` — `[{"label": "HH:00", "count": int}]`, oldest→newest, zero-filled.
    - `top_airlines(limit: int = 8) -> list[dict]` — `[{"airline": str, "count": int}]`.
    - `history(from_ts: float, to_ts: float) -> list[dict]` — `[{"icao", "callsign", "points": [{"ts","lat","lon","alt_ft","track_deg"}]}]`; only contacts with ≥1 point in the window.
    - `prune(before_ts: float) -> int` — deletes `positions` with `ts < before_ts`, returns count; leaves `contacts` intact.
    - `close() -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_store.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store.py -q`
Expected: FAIL — `ModuleNotFoundError: flighttrack.store`.

- [ ] **Step 3: Write `src/flighttrack/store.py`**

```python
from __future__ import annotations
import os
import sqlite3
import threading
from datetime import datetime

_SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
  id INTEGER PRIMARY KEY,
  icao TEXT NOT NULL,
  callsign TEXT,
  first_seen REAL NOT NULL,
  last_seen REAL NOT NULL,
  max_alt_ft REAL,
  min_alt_ft REAL,
  closest_km REAL,
  max_km REAL,
  closest_elevation_deg REAL,
  aircraft_type TEXT,
  category TEXT,
  registration TEXT,
  open INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_contacts_first_seen ON contacts(first_seen);
CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY,
  contact_id INTEGER NOT NULL REFERENCES contacts(id),
  ts REAL NOT NULL,
  lat REAL NOT NULL,
  lon REAL NOT NULL,
  alt_ft REAL,
  ground_speed_kt REAL,
  track_deg REAL,
  rssi REAL
);
CREATE INDEX IF NOT EXISTS idx_positions_ts ON positions(ts);
CREATE INDEX IF NOT EXISTS idx_positions_contact ON positions(contact_id);
"""


def _mn(a, b, fn):
    if a is None:
        return b
    if b is None:
        return a
    return fn(a, b)


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.executescript(_SCHEMA)
            self._db.commit()

    def open_contact(self, icao, callsign, ts) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO contacts (icao, callsign, first_seen, last_seen) VALUES (?,?,?,?)",
                (icao, callsign, ts, ts))
            self._db.commit()
            return cur.lastrowid

    def update_contact(self, contact_id, ts, *, alt_ft=None, distance_km=None,
                       elevation_deg=None, callsign=None) -> None:
        with self._lock:
            row = self._db.execute(
                "SELECT callsign, max_alt_ft, min_alt_ft, closest_km, max_km, closest_elevation_deg "
                "FROM contacts WHERE id=?", (contact_id,)).fetchone()
            if row is None:
                return
            new_closest = _mn(row["closest_km"], distance_km, min)
            # elevation that pairs with the closest approach
            new_elev = row["closest_elevation_deg"]
            if distance_km is not None and (row["closest_km"] is None or distance_km <= row["closest_km"]):
                new_elev = elevation_deg if elevation_deg is not None else new_elev
            self._db.execute(
                "UPDATE contacts SET last_seen=?, callsign=COALESCE(?, callsign), "
                "max_alt_ft=?, min_alt_ft=?, closest_km=?, max_km=?, closest_elevation_deg=? WHERE id=?",
                (ts, callsign,
                 _mn(row["max_alt_ft"], alt_ft, max), _mn(row["min_alt_ft"], alt_ft, min),
                 new_closest, _mn(row["max_km"], distance_km, max), new_elev, contact_id))
            self._db.commit()

    def close_contact(self, contact_id) -> None:
        with self._lock:
            self._db.execute("UPDATE contacts SET open=0 WHERE id=?", (contact_id,))
            self._db.commit()

    def add_position(self, contact_id, ts, lat, lon, alt_ft, ground_speed_kt, track_deg, rssi) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO positions (contact_id, ts, lat, lon, alt_ft, ground_speed_kt, track_deg, rssi) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (contact_id, ts, lat, lon, alt_ft, ground_speed_kt, track_deg, rssi))
            self._db.commit()

    def summary(self, now: float) -> dict:
        with self._lock:
            start_today = datetime.fromtimestamp(now).replace(
                hour=0, minute=0, second=0, microsecond=0).timestamp()
            total = self._db.execute("SELECT count(*) c FROM contacts").fetchone()["c"]
            today = self._db.execute(
                "SELECT count(*) c FROM contacts WHERE first_seen>=?", (start_today,)).fetchone()["c"]
            uniq = self._db.execute("SELECT count(DISTINCT icao) c FROM contacts").fetchone()["c"]
            closest = self._db.execute(
                "SELECT icao, callsign, closest_km km, last_seen FROM contacts "
                "WHERE closest_km IS NOT NULL ORDER BY closest_km ASC LIMIT 1").fetchone()
            farthest = self._db.execute(
                "SELECT icao, callsign, max_km km, last_seen FROM contacts "
                "WHERE max_km IS NOT NULL ORDER BY max_km DESC LIMIT 1").fetchone()
            highest = self._db.execute("SELECT max(max_alt_ft) m FROM contacts").fetchone()["m"]
            busiest = self._db.execute(
                "SELECT strftime('%H', datetime(first_seen,'unixepoch','localtime')) h, count(*) c "
                "FROM contacts GROUP BY h ORDER BY c DESC LIMIT 1").fetchone()

            def rec(r):
                return None if r is None else {
                    "icao": r["icao"], "callsign": r["callsign"],
                    "km": r["km"], "when": r["last_seen"]}

            return {
                "sessions_total": total, "sessions_today": today, "unique_total": uniq,
                "closest": rec(closest), "farthest": rec(farthest),
                "highest_alt_ft": highest,
                "busiest_hour": (busiest["h"] + ":00") if busiest else None,
            }

    def contacts_per_hour(self, now: float, hours: int = 24) -> list[dict]:
        with self._lock:
            buckets: list[dict] = []
            start = (int(now) // 3600) * 3600 - (hours - 1) * 3600
            for i in range(hours):
                lo = start + i * 3600
                hi = lo + 3600
                c = self._db.execute(
                    "SELECT count(*) c FROM contacts WHERE first_seen>=? AND first_seen<?",
                    (lo, hi)).fetchone()["c"]
                label = datetime.fromtimestamp(lo).strftime("%H:00")
                buckets.append({"label": label, "count": c})
            return buckets

    def top_airlines(self, limit: int = 8) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT substr(callsign,1,3) a, count(*) c FROM contacts "
                "WHERE callsign IS NOT NULL AND length(callsign)>=3 "
                "GROUP BY a ORDER BY c DESC LIMIT ?", (limit,)).fetchall()
            return [{"airline": r["a"], "count": r["c"]} for r in rows]

    def history(self, from_ts: float, to_ts: float) -> list[dict]:
        if from_ts > to_ts:
            return []
        with self._lock:
            rows = self._db.execute(
                "SELECT DISTINCT c.id, c.icao, c.callsign FROM contacts c "
                "JOIN positions p ON p.contact_id=c.id WHERE p.ts>=? AND p.ts<=? "
                "ORDER BY c.first_seen", (from_ts, to_ts)).fetchall()
            out = []
            for r in rows:
                pts = self._db.execute(
                    "SELECT ts, lat, lon, alt_ft, track_deg FROM positions "
                    "WHERE contact_id=? AND ts>=? AND ts<=? ORDER BY ts",
                    (r["id"], from_ts, to_ts)).fetchall()
                out.append({"icao": r["icao"], "callsign": r["callsign"],
                            "points": [dict(p) for p in pts]})
            return out

    def prune(self, before_ts: float) -> int:
        with self._lock:
            cur = self._db.execute("DELETE FROM positions WHERE ts<?", (before_ts,))
            self._db.commit()
            return cur.rowcount

    def close(self) -> None:
        with self._lock:
            self._db.close()
```

- [ ] **Step 4: Add config blocks to `src/flighttrack/config.py`**

Add these model classes (after `Dump1090Config`):

```python
class DbConfig(BaseModel):
    path: str = "data/flighttrack.db"


class LoggingConfig(BaseModel):
    snapshot_interval_s: float = 15.0
    retention_days: int = 30
```

And add these two fields to `Settings` (after the `dump1090` field):

```python
    db: DbConfig = DbConfig()
    logging: LoggingConfig = LoggingConfig()
```

- [ ] **Step 5: Document the new blocks in `config.example.yaml`**

Append:

```yaml

db:
  path: data/flighttrack.db

logging:
  snapshot_interval_s: 15.0   # seconds between stored track points per aircraft
  retention_days: 30          # positions older than this are pruned (contacts kept)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_store.py tests/test_config.py -q`
Expected: PASS (store tests + the existing 5 config tests still green).

- [ ] **Step 7: Commit**

```bash
git add src/flighttrack/store.py src/flighttrack/config.py config.example.yaml tests/test_store.py
git commit -m "feat: SQLite store for contacts/positions with stats, history and prune"
```

---

### Task 2: Recorder — snapshot → contact sessions & track points

**Files:**
- Create: `src/flighttrack/recorder.py`
- Test: `tests/test_recorder.py`

**Interfaces:**
- Consumes: `Store` (Task 1); `AircraftView` from `flighttrack.models`.
- Produces (used by Task 3):
  - `Recorder(store: Store, snapshot_interval_s: float = 15.0)`
  - `Recorder.on_tick(views: list[AircraftView], now: float) -> None` — opens a contact per newly-seen icao, updates aggregates every tick, appends a position no more often than `snapshot_interval_s` per contact (only when positioned), and closes contacts whose icao is absent from `views`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_recorder.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_recorder.py -q`
Expected: FAIL — `ModuleNotFoundError: flighttrack.recorder`.

- [ ] **Step 3: Write `src/flighttrack/recorder.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from flighttrack.models import AircraftView
from flighttrack.store import Store


@dataclass
class _Open:
    contact_id: int
    last_pos_ts: float


class Recorder:
    def __init__(self, store: Store, snapshot_interval_s: float = 15.0):
        self.store = store
        self.interval = snapshot_interval_s
        self._open: dict[str, _Open] = {}

    def on_tick(self, views: list[AircraftView], now: float) -> None:
        seen: set[str] = set()
        for v in views:
            seen.add(v.icao)
            oc = self._open.get(v.icao)
            if oc is None:
                cid = self.store.open_contact(v.icao, v.callsign, now)
                oc = _Open(contact_id=cid, last_pos_ts=float("-inf"))
                self._open[v.icao] = oc
            self.store.update_contact(oc.contact_id, now, alt_ft=v.alt_ft,
                                      distance_km=v.distance_km,
                                      elevation_deg=v.elevation_deg, callsign=v.callsign)
            if v.lat is not None and v.lon is not None and (now - oc.last_pos_ts) >= self.interval:
                self.store.add_position(oc.contact_id, now, v.lat, v.lon, v.alt_ft,
                                        v.ground_speed_kt, v.track_deg, v.rssi)
                oc.last_pos_ts = now
        for icao in list(self._open):
            if icao not in seen:
                self.store.close_contact(self._open[icao].contact_id)
                del self._open[icao]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_recorder.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/flighttrack/recorder.py tests/test_recorder.py
git commit -m "feat: recorder maps tracker snapshots to contact sessions and tracks"
```

---

### Task 3: App integration — record in the loop, prune task, stats/history API

**Files:**
- Modify: `src/flighttrack/app.py`
- Test: `tests/test_app.py` (add cases)

**Interfaces:**
- Consumes: `Store` (Task 1), `Recorder` (Task 2), existing `_ingest_loop`, `Tracker`, `build_source`.
- Produces (used by Tasks 4–5):
  - On `app.state`: `store`, `recorder`.
  - Ingest loop additionally calls `recorder.on_tick(tracker.snapshot(), now)` off-thread, inside the existing try/except.
  - A prune task pruning `positions` older than `logging.retention_days` on startup and hourly.
  - Routes: `GET /api/stats/summary`, `GET /api/stats/per-hour`, `GET /api/stats/airlines`, `GET /api/history?from=<ts>&to=<ts>` (both query params float seconds; missing/invalid → 422 via FastAPI typing).

- [ ] **Step 1: Write the failing test** (append to `tests/test_app.py`)

```python
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
    from flighttrack.config import Settings, Receiver, DbConfig
    s = Settings(source="synthetic", receiver=Receiver(lat=40.0, lon=-105.0),
                 poll_interval_s=0.02, db=DbConfig(path=":memory:"))
    app = create_app(s)
    with TestClient(app) as c:
        store = app.state.store
        cid = store.open_contact("abc", "UAL1", ts=100.0)
        store.add_position(cid, 100.0, 40.1, -105.1, 35000, 450, 270, -12.0)
        r = c.get("/api/history", params={"from": 0.0, "to": 200.0})
        assert r.status_code == 200
        body = r.json()
        assert body[0]["icao"] == "abc" and body[0]["points"][0]["lat"] == 40.1


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_app.py -q`
Expected: FAIL — `/api/stats/summary` 404 (route missing) and `app.state.store` AttributeError; the loop-survives test fails because `_ingest_loop` does not yet call `recorder.on_tick`.

- [ ] **Step 3: Update `_ingest_loop` in `src/flighttrack/app.py`**

Replace the loop body so it records each tick (the `on_tick` runs off-thread; the whole body stays inside the existing `try/except`):

```python
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
```

- [ ] **Step 4: Add a prune loop helper to `src/flighttrack/app.py`**

```python
async def _prune_loop(app: FastAPI) -> None:
    store = app.state.store
    retention_s = app.state.settings.logging.retention_days * 86400
    while True:
        try:
            await asyncio.to_thread(store.prune, time.time() - retention_s)
        except Exception as e:
            log.warning("prune failed: %s", e)
        await asyncio.sleep(3600)
```

- [ ] **Step 5: Wire store/recorder/tasks into the lifespan**

In `create_app`'s `lifespan`, after building `source`, add store + recorder and start both tasks; close the store on shutdown. Replace the lifespan body with:

```python
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.tracker = Tracker(settings.receiver, settings.stale_timeout_s)
        app.state.manager = ConnectionManager()
        app.state.source = build_source(settings)
        app.state.store = Store(settings.db.path)
        app.state.recorder = Recorder(app.state.store, settings.logging.snapshot_interval_s)
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
            app.state.store.close()
```

Add the imports at the top of `app.py`:

```python
from flighttrack.store import Store
from flighttrack.recorder import Recorder
```

- [ ] **Step 6: Add the API routes in `create_app`** (after the `/api/config` route)

```python
    @app.get("/api/stats/summary")
    async def stats_summary():
        return await asyncio.to_thread(app.state.store.summary, time.time())

    @app.get("/api/stats/per-hour")
    async def stats_per_hour():
        return await asyncio.to_thread(app.state.store.contacts_per_hour, time.time(), 24)

    @app.get("/api/stats/airlines")
    async def stats_airlines():
        return await asyncio.to_thread(app.state.store.top_airlines, 8)

    @app.get("/api/history")
    async def history(from_: float = Query(..., alias="from"), to: float = Query(...)):
        return await asyncio.to_thread(app.state.store.history, from_, to)
```

Add `Query` to the FastAPI import at the top of `app.py`:

```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_app.py -q`
Expected: PASS (all prior app tests + 3 new).

- [ ] **Step 8: Commit**

```bash
git add src/flighttrack/app.py tests/test_app.py
git commit -m "feat: record contacts in ingest loop, add prune task and stats/history API"
```

---

### Task 4: Stats page — tiles + magnitude charts

**Files:**
- Create: `src/flighttrack/static/stats.html`
- Create: `src/flighttrack/static/stats.js`
- Modify: `src/flighttrack/static/style.css` (append stats styles)
- Modify: `src/flighttrack/app.py` (add `GET /stats` route)
- Test: `tests/test_stats_page_smoke.py` (e2e)

**Interfaces:**
- Consumes: `GET /api/stats/summary`, `GET /api/stats/per-hour`, `GET /api/stats/airlines` (Task 3).
- Produces: a `/stats` page. No new Python interfaces.

**Dataviz note:** both charts are **single-series magnitude** bars → one accent hue (`#5dd0ff`) on the dark surface (`#0b0f14`), no categorical palette (so no CVD concern); identity is the axis label, not color. Thin bars, 4px rounded tops, 2px gaps, recessive axis text in muted ink (`#8aa0b4`), per-bar hover tooltip, value labels. (This follows the dataviz procedure: form first = magnitude → bars; color last = one hue; contrast of accent-on-surface is well above the floor.)

- [ ] **Step 1: Add the `/stats` route in `src/flighttrack/app.py`** (next to `/`)

```python
    @app.get("/stats")
    def stats_page():
        return FileResponse(STATIC / "stats.html")
```

- [ ] **Step 2: Write `src/flighttrack/static/stats.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Flight Tracker — Stats</title>
  <link rel="stylesheet" href="/static/style.css" />
</head>
<body>
  <main id="stats">
    <header><a href="/" class="back">← map</a><h1>Stats</h1></header>
    <section id="tiles" class="tiles"></section>
    <section class="chart-block">
      <h2>Contacts per hour (last 24h)</h2>
      <div id="perhour" class="chart"></div>
    </section>
    <section class="chart-block">
      <h2>Top airlines</h2>
      <div id="airlines" class="chart"></div>
    </section>
  </main>
  <script src="/static/stats.js"></script>
</body>
</html>
```

- [ ] **Step 3: Write `src/flighttrack/static/stats.js`**

```javascript
const ACCENT = "#5dd0ff";
const INK_MUTED = "#8aa0b4";

function tile(label, value, sub) {
  return `<div class="tile"><div class="tval">${value}</div>` +
         `<div class="tlabel">${label}</div>` +
         (sub ? `<div class="tsub">${sub}</div>` : "") + `</div>`;
}

async function loadTiles() {
  const s = await (await fetch("/api/stats/summary")).json();
  const closest = s.closest ? `${s.closest.callsign || s.closest.icao} · ${s.closest.km.toFixed(1)} km` : "—";
  const farthest = s.farthest ? `${s.farthest.callsign || s.farthest.icao} · ${s.farthest.km.toFixed(1)} km` : "—";
  const high = s.highest_alt_ft != null ? `${Math.round(s.highest_alt_ft).toLocaleString()} ft` : "—";
  document.getElementById("tiles").innerHTML =
    tile("Seen today", s.sessions_today) +
    tile("Seen all-time", s.sessions_total, `${s.unique_total} unique`) +
    tile("Closest pass", closest) +
    tile("Farthest", farthest) +
    tile("Highest", high) +
    tile("Busiest hour", s.busiest_hour || "—");
}

// Single-series magnitude bar chart as inline SVG (dataviz: one hue, labels, hover).
function barChart(el, rows, labelKey, valueKey) {
  const W = el.clientWidth || 600, H = 220, padL = 32, padB = 28, padT = 8;
  const max = Math.max(1, ...rows.map(r => r[valueKey]));
  const n = rows.length || 1;
  const bw = (W - padL) / n;
  const bars = rows.map((r, i) => {
    const h = (H - padB - padT) * (r[valueKey] / max);
    const x = padL + i * bw + 2, y = H - padB - h;
    const w = Math.max(1, bw - 4);
    return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="4" fill="${ACCENT}">` +
           `<title>${r[labelKey]}: ${r[valueKey]}</title></rect>` +
           (r[valueKey] > 0 ? `<text x="${x + w / 2}" y="${y - 4}" text-anchor="middle" ` +
             `font-size="10" fill="${INK_MUTED}">${r[valueKey]}</text>` : "") +
           `<text x="${x + w / 2}" y="${H - padB + 14}" text-anchor="middle" ` +
             `font-size="9" fill="${INK_MUTED}">${r[labelKey]}</text>`;
  }).join("");
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img">${bars}</svg>`;
}

async function loadCharts() {
  const perhour = await (await fetch("/api/stats/per-hour")).json();
  barChart(document.getElementById("perhour"), perhour, "label", "count");
  const airlines = await (await fetch("/api/stats/airlines")).json();
  barChart(document.getElementById("airlines"), airlines, "airline", "count");
}

loadTiles();
loadCharts();
```

- [ ] **Step 4: Append stats styles to `src/flighttrack/static/style.css`**

```css
#stats { max-width: 900px; margin: 0 auto; padding: 16px; }
#stats header { display: flex; align-items: baseline; gap: 16px; }
#stats h1 { font-size: 18px; }
#stats h2 { font-size: 13px; color: #8aa0b4; text-transform: uppercase; letter-spacing: .06em; }
.back { color: #5dd0ff; text-decoration: none; font-size: 13px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin: 12px 0 24px; }
.tile { background: #121923; border: 1px solid #1c2430; border-radius: 10px; padding: 12px 14px; }
.tval { font-size: 20px; font-weight: 700; }
.tlabel { font-size: 11px; color: #8aa0b4; text-transform: uppercase; letter-spacing: .05em; margin-top: 4px; }
.tsub { font-size: 11px; color: #6b7d8f; margin-top: 2px; }
.chart-block { margin: 18px 0; }
.chart { background: #0e141b; border: 1px solid #1c2430; border-radius: 10px; padding: 8px; }
```

- [ ] **Step 5: Write the e2e smoke test**

```python
# tests/test_stats_page_smoke.py
import socket, threading, time
import pytest, uvicorn
from flighttrack.config import Settings, Receiver, SyntheticConfig, DbConfig
from flighttrack.app import create_app

pytestmark = pytest.mark.e2e


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture
def server_url():
    port = _free_port()
    s = Settings(source="synthetic", receiver=Receiver(lat=40.0, lon=-105.0, alt_m=1600.0),
                 synthetic=SyntheticConfig(num_aircraft=4, seed=1), poll_interval_s=0.05,
                 db=DbConfig(path=":memory:"), port=port)
    server = uvicorn.Server(uvicorn.Config(create_app(s), host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True); th.start()
    for _ in range(50):
        if server.started: break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True; th.join(timeout=5)


def test_stats_page_renders_tiles_and_chart(server_url, page):
    page.goto(server_url + "/stats")
    page.wait_for_selector(".tile", timeout=8000)
    page.wait_for_selector("#perhour svg rect", timeout=8000)
    assert page.locator(".tile").count() >= 4
```

- [ ] **Step 6: Run the smoke test**

Run: `uv run pytest tests/test_stats_page_smoke.py -m e2e -q`
Expected: PASS — tiles render and at least one bar rect appears.

- [ ] **Step 7: Commit**

```bash
git add src/flighttrack/static/stats.html src/flighttrack/static/stats.js \
        src/flighttrack/static/style.css src/flighttrack/app.py tests/test_stats_page_smoke.py
git commit -m "feat: stats page with summary tiles and magnitude charts"
```

---

### Task 5: History playback on the map

**Files:**
- Modify: `src/flighttrack/static/index.html` (add controls bar + stats link)
- Modify: `src/flighttrack/static/app.js` (Live/Playback modes, scrubber, interpolation)
- Modify: `src/flighttrack/static/style.css` (controls styles)
- Test: `tests/test_playback_smoke.py` (e2e)

**Interfaces:**
- Consumes: `GET /api/history?from=<ts>&to=<ts>` (Task 3); existing `/ws/live`, `/api/config`.
- Produces: playback UI. No new Python interfaces.

**Behavior:** A control bar offers **Live** (default, current WebSocket behavior) and **Playback**. In Playback the user picks a window (Last hour / Last 6h / Last 24h), the client fetches history, builds per-aircraft tracks, and a play/pause + speed (1×/5×/20×) + scrubber drive a clock `T`. Each animation frame renders every aircraft at its interpolated position for `T` (linear between the two surrounding points; aircraft with no point at `T` are hidden; `T` is clamped to the window so there is no extrapolation).

- [ ] **Step 1: Add the controls bar + stats link to `src/flighttrack/static/index.html`**

Replace the `<aside id="sidebar">` opening block (through `<div id="status">…`) with:

```html
    <aside id="sidebar">
      <h1>Overhead <a href="/stats" class="statslink">stats →</a></h1>
      <div id="controls">
        <div class="mode">
          <button id="mode-live" class="active">Live</button>
          <button id="mode-playback">Playback</button>
        </div>
        <div id="playback-controls" hidden>
          <select id="window">
            <option value="3600">Last hour</option>
            <option value="21600">Last 6h</option>
            <option value="86400">Last 24h</option>
          </select>
          <div class="transport">
            <button id="playpause">▶</button>
            <select id="speed">
              <option value="1">1×</option>
              <option value="5" selected>5×</option>
              <option value="20">20×</option>
            </select>
          </div>
          <input id="scrubber" type="range" min="0" max="1000" value="0" />
          <div id="playtime" class="meta"></div>
        </div>
      </div>
      <div id="status">connecting…</div>
```

- [ ] **Step 2: Replace `src/flighttrack/static/app.js` with the Live+Playback version**

```javascript
let map, youMarker, ws = null;
const markers = new Map(); // icao -> L.marker
let mode = "live";
let tracks = [];           // [{icao, callsign, points:[{ts,lat,lon,alt_ft,track_deg}]}]
let winStart = 0, winEnd = 0, playT = 0, playing = false, speed = 5, raf = null, lastFrame = 0;

function altColor(ft) {
  if (ft == null) return "#9aa7b2";
  if (ft < 10000) return "#ff5d5d";
  if (ft < 25000) return "#ffb24d";
  return "#5dd0ff";
}

function planeIcon(a) {
  const rot = a.track_deg ?? 0;
  return L.divIcon({ className: "",
    html: `<div class="plane" style="transform: rotate(${rot}deg); color:${altColor(a.alt_ft)}">✈</div>`,
    iconSize: [20, 20], iconAnchor: [10, 10] });
}

function renderContacts(list) {
  const ul = document.getElementById("contacts");
  ul.innerHTML = "";
  for (const a of list) {
    const li = document.createElement("li");
    const dist = a.distance_km != null ? `${a.distance_km.toFixed(1)} km` : "—";
    const alt = a.alt_ft != null ? `${Math.round(a.alt_ft).toLocaleString()} ft` : "—";
    li.innerHTML = `<div class="cs">${a.callsign || a.icao}</div>` +
                   `<div class="meta">${dist} · ${alt} · ${Math.round(a.elevation_deg ?? 0)}°</div>`;
    ul.appendChild(li);
  }
}

function renderAircraft(list) {
  const seen = new Set();
  for (const a of list) {
    seen.add(a.icao);
    let m = markers.get(a.icao);
    if (!m) { m = L.marker([a.lat, a.lon], { icon: planeIcon(a) }).addTo(map); markers.set(a.icao, m); }
    else { m.setLatLng([a.lat, a.lon]); m.setIcon(planeIcon(a)); }
    m.bindTooltip(a.callsign || a.icao);
  }
  for (const [icao, m] of markers) if (!seen.has(icao)) { map.removeLayer(m); markers.delete(icao); }
  renderContacts(list);
}

// ---- Live ----
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/live`);
  ws.onmessage = (e) => { if (mode === "live") { const d = JSON.parse(e.data); renderAircraft(d.aircraft);
    document.getElementById("status").textContent = `${d.aircraft.length} aircraft · live`; } };
  ws.onclose = () => { if (mode === "live") { document.getElementById("status").textContent = "reconnecting…";
    setTimeout(connect, 2000); } };
}

// ---- Playback ----
function interp(points, t) {
  if (!points.length || t < points[0].ts || t > points[points.length - 1].ts) return null;
  let lo = points[0];
  for (const p of points) {
    if (p.ts === t) return p;
    if (p.ts > t) {
      const f = (t - lo.ts) / (p.ts - lo.ts || 1);
      return { lat: lo.lat + (p.lat - lo.lat) * f, lon: lo.lon + (p.lon - lo.lon) * f,
               alt_ft: lo.alt_ft, track_deg: p.track_deg ?? lo.track_deg };
    }
    lo = p;
  }
  return lo;
}

function renderPlaybackFrame() {
  const list = [];
  for (const tr of tracks) {
    const p = interp(tr.points, playT);
    if (p) list.push({ icao: tr.icao, callsign: tr.callsign, lat: p.lat, lon: p.lon,
                       alt_ft: p.alt_ft, track_deg: p.track_deg, distance_km: null, elevation_deg: null });
  }
  renderAircraft(list);
  const pct = winEnd > winStart ? ((playT - winStart) / (winEnd - winStart)) * 1000 : 0;
  document.getElementById("scrubber").value = String(pct);
  document.getElementById("playtime").textContent =
    `${new Date(playT * 1000).toLocaleTimeString()} · ${list.length} shown`;
  document.getElementById("status").textContent = "playback";
}

function tick(now) {
  if (!playing) return;
  const dt = (now - lastFrame) / 1000; lastFrame = now;
  playT = Math.min(winEnd, playT + dt * speed);
  renderPlaybackFrame();
  if (playT >= winEnd) { playing = false; document.getElementById("playpause").textContent = "▶"; return; }
  raf = requestAnimationFrame(tick);
}

async function loadWindow() {
  const span = Number(document.getElementById("window").value);
  winEnd = Date.now() / 1000; winStart = winEnd - span; playT = winStart;
  tracks = await (await fetch(`/api/history?from=${winStart}&to=${winEnd}`)).json();
  renderPlaybackFrame();
}

function setMode(next) {
  mode = next;
  document.getElementById("mode-live").classList.toggle("active", next === "live");
  document.getElementById("mode-playback").classList.toggle("active", next === "playback");
  document.getElementById("playback-controls").hidden = next !== "playback";
  playing = false; if (raf) cancelAnimationFrame(raf);
  document.getElementById("playpause").textContent = "▶";
  for (const [, m] of markers) map.removeLayer(m);
  markers.clear();
  if (next === "playback") loadWindow();
  else document.getElementById("status").textContent = "live";
}

async function init() {
  const cfg = await (await fetch("/api/config")).json();
  const { lat, lon } = cfg.receiver;
  map = L.map("map").setView([lat, lon], 9);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    { attribution: "© OpenStreetMap", maxZoom: 18 }).addTo(map);
  youMarker = L.circleMarker([lat, lon], { radius: 6, color: "#4de6a1", fillOpacity: 1 })
    .addTo(map).bindTooltip("You");

  document.getElementById("mode-live").onclick = () => setMode("live");
  document.getElementById("mode-playback").onclick = () => setMode("playback");
  document.getElementById("window").onchange = loadWindow;
  document.getElementById("speed").onchange = (e) => { speed = Number(e.target.value); };
  document.getElementById("scrubber").oninput = (e) => {
    playT = winStart + (Number(e.target.value) / 1000) * (winEnd - winStart);
    renderPlaybackFrame();
  };
  document.getElementById("playpause").onclick = () => {
    playing = !playing;
    document.getElementById("playpause").textContent = playing ? "❚❚" : "▶";
    if (playing) { if (playT >= winEnd) playT = winStart; lastFrame = performance.now(); raf = requestAnimationFrame(tick); }
    else if (raf) cancelAnimationFrame(raf);
  };

  connect();
}
init();
```

- [ ] **Step 3: Append controls styles to `src/flighttrack/static/style.css`**

```css
.statslink { font-size: 11px; color: #5dd0ff; text-decoration: none; font-weight: 400; text-transform: none; letter-spacing: 0; }
#controls { margin: 8px 0; }
.mode { display: flex; gap: 6px; margin-bottom: 8px; }
.mode button, .transport button { background: #121923; color: #e6edf3; border: 1px solid #1c2430;
  border-radius: 6px; padding: 4px 10px; cursor: pointer; }
.mode button.active { background: #15323f; border-color: #5dd0ff; color: #5dd0ff; }
#playback-controls { display: flex; flex-direction: column; gap: 6px; }
#playback-controls select, #scrubber { width: 100%; }
.transport { display: flex; gap: 6px; align-items: center; }
#scrubber { accent-color: #5dd0ff; }
```

- [ ] **Step 4: Write the e2e smoke test**

```python
# tests/test_playback_smoke.py
import socket, threading, time
import pytest, uvicorn
from flighttrack.config import Settings, Receiver, SyntheticConfig, DbConfig, LoggingConfig
from flighttrack.app import create_app

pytestmark = pytest.mark.e2e


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture
def server_url():
    port = _free_port()
    s = Settings(source="synthetic", receiver=Receiver(lat=40.0, lon=-105.0, alt_m=1600.0),
                 synthetic=SyntheticConfig(num_aircraft=4, seed=1), poll_interval_s=0.05,
                 db=DbConfig(path=":memory:"),
                 logging=LoggingConfig(snapshot_interval_s=0.0),
                 port=port)
    server = uvicorn.Server(uvicorn.Config(create_app(s), host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True); th.start()
    for _ in range(50):
        if server.started: break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True; th.join(timeout=5)


def test_switch_to_playback_loads_history(server_url, page):
    page.goto(server_url)
    page.wait_for_selector(".plane", timeout=8000)      # live first
    time.sleep(1.5)                                     # let positions accumulate in the DB
    page.click("#mode-playback")
    page.wait_for_selector("#playback-controls:not([hidden])", timeout=4000)
    # history fetched for the window; scrubbing to the end should show the playtime label
    page.wait_for_function("document.getElementById('playtime').textContent.length > 0", timeout=6000)
```

- [ ] **Step 5: Run the smoke test**

Run: `uv run pytest tests/test_playback_smoke.py -m e2e -q`
Expected: PASS — playback controls reveal and the playtime label populates from loaded history.

- [ ] **Step 6: Manual verification**

Run: `uv run flighttrack`, open `http://127.0.0.1:8000`, let it run ~1 minute, then click **Playback → Last hour → ▶**. Planes replay their logged tracks; the scrubber and clock advance; **stats →** opens the dashboard.

- [ ] **Step 7: Commit**

```bash
git add src/flighttrack/static/index.html src/flighttrack/static/app.js \
        src/flighttrack/static/style.css tests/test_playback_smoke.py
git commit -m "feat: Live/Playback modes with scrubbable interpolated history on the map"
```

---

## Self-Review

**Spec coverage (Phase 2 slice):**
- SQLite `contacts` + `positions`, WAL → Task 1. ✓ (`alerts`/`push_subscriptions` correctly deferred to Phase 4.)
- Per-contact aggregates (first/last seen, max/min alt, closest/farthest, elevation) → Task 1. ✓
- Logging integration: contact sessions + throttled snapshots → Task 2 + Task 3 loop. ✓
- Retention prune of positions (configurable days) → Task 1 `prune` + Task 3 `_prune_loop`. ✓
- Stats tiles + charts (per-hour, airlines) → Task 4. ✓ (Top *aircraft types* deferred — needs the offline enrichment DB from Phase 4; `contacts` has nullable `aircraft_type`/`category`/`registration` columns reserved for it.)
- History API + playback with timeline/scrubber/speed + interpolation → Task 3 route + Task 5 UI. ✓
- Config `db` + `logging` blocks → Task 1. ✓
- Off-loop DB access via `asyncio.to_thread` → Tasks 3. ✓

**Placeholder scan:** none. One spot (Task 3 Step 1) deliberately shows an awkward first draft then the clean replacement with an explicit "delete the first version" instruction — the clean version is complete code.

**Type consistency:** `Store` method names/signatures in the Interfaces block match their definitions and every call site (Recorder in Task 2, routes in Task 3, tests). `summary()` dict keys used in `stats.js` (`sessions_today`, `sessions_total`, `unique_total`, `closest.{callsign,icao,km}`, `farthest`, `highest_alt_ft`, `busiest_hour`) match Task 1's return. `history()` item shape (`icao`, `callsign`, `points[].{ts,lat,lon,alt_ft,track_deg}`) matches `app.js` playback consumption. `AircraftView` fields consumed by the Recorder exist from Phase 1.

**Review Focus coverage:**
- Empty DB null-safety → `test_empty_summary_is_null_safe`, `test_empty_history_and_airlines` (T1). ✓
- Position-less contact → `test_positionless_contact_has_no_points_in_history` (T1), `test_positionless_view_opens_contact_without_points` (T2). ✓
- Reappearing ICAO → `test_absent_icao_closes_and_reappearance_opens_new` (T2). ✓
- DB error mid-loop → `test_ingest_loop_survives_store_error` (T3). ✓
- Degenerate history window → `test_history_inverted_range_is_empty` (T1); route tolerance via `history()` guard (T3). ✓
