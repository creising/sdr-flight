from __future__ import annotations
import csv
import os
import sqlite3


def build_faa_db(master_path: str, acftref_path: str, db_path: str) -> int:
    """Join the FAA MASTER (registrations) and ACFTREF (model reference) files into a
    compact SQLite table keyed by ICAO Mode-S hex. Returns the number of rows loaded."""
    ref: dict[str, tuple[str, str]] = {}
    with open(acftref_path, newline="") as f:
        for row in csv.DictReader(f):
            code = (row.get("CODE") or "").strip()
            if code:
                ref[code] = ((row.get("MFR") or "").strip(), (row.get("MODEL") or "").strip())

    rows = []
    with open(master_path, newline="") as f:
        for row in csv.DictReader(f):
            hexc = (row.get("MODE S CODE HEX") or "").strip().lower()
            if not hexc:
                continue
            mfr, model = ref.get((row.get("MFR MDL CODE") or "").strip(), ("", ""))
            n = (row.get("N-NUMBER") or "").strip()
            year = (row.get("YEAR MFR") or "").strip()
            rows.append((hexc, ("N" + n) if n else None, mfr or None, model or None, year or None))

    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("DROP TABLE IF EXISTS faa_aircraft")
    con.execute("CREATE TABLE faa_aircraft (hex TEXT PRIMARY KEY, n_number TEXT, "
                "make TEXT, model TEXT, year TEXT)")
    con.executemany("INSERT OR REPLACE INTO faa_aircraft VALUES (?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return len(rows)


class FaaLookup:
    """Read-only lookup of aircraft make/model/year by ICAO hex. Graceful when the DB
    is absent (returns None), so the app runs fine before the registry is imported."""

    def __init__(self, db_path: str):
        self._con = None
        if db_path and os.path.exists(db_path):
            try:
                self._con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True,
                                            check_same_thread=False)
            except sqlite3.Error:
                self._con = None

    def lookup(self, hex: str) -> dict | None:
        if self._con is None or not hex:
            return None
        row = self._con.execute(
            "SELECT n_number, make, model, year FROM faa_aircraft WHERE hex=?",
            (hex.lower(),)).fetchone()
        if not row:
            return None
        return {"n_number": row[0], "make": row[1], "model": row[2], "year": row[3]}

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
