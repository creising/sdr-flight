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

    def contacts_buckets(self, start_ts: float, end_ts: float, n: int) -> list[dict]:
        if n <= 0 or end_ts <= start_ts:
            return []
        width = (end_ts - start_ts) / n
        with self._lock:
            out = []
            for i in range(n):
                lo = start_ts + i * width
                hi = lo + width
                c = self._db.execute(
                    "SELECT count(*) c FROM contacts WHERE first_seen>=? AND first_seen<?",
                    (lo, hi)).fetchone()["c"]
                out.append({"start": lo, "count": c})
            return out

    def top_airlines(self, limit: int = 8) -> list[dict]:
        import re
        with self._lock:
            rows = self._db.execute(
                "SELECT callsign FROM contacts WHERE callsign IS NOT NULL AND length(callsign)>=3"
            ).fetchall()
        if not rows:
            return []
        total = len(rows)
        airline: dict[str, int] = {}
        ga = 0
        for r in rows:
            cs = r["callsign"]
            if re.match(r"^[A-Z]{3}\d", cs):
                airline[cs[:3]] = airline.get(cs[:3], 0) + 1
            else:
                ga += 1
        ranked = sorted(airline.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        out = [{"airline": a, "count": c, "share": c / total} for a, c in ranked]
        if ga:
            out.append({"airline": "Private / GA", "count": ga, "share": ga / total})
        return out

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
