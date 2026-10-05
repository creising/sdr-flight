#!/usr/bin/env python3
"""Download the FAA Releasable Aircraft Database and build a compact hex->make/model/year
SQLite DB for offline aircraft lookups. Run inside the project venv:

    uv run python scripts/import_faa.py [data/faa.db]

Re-run periodically (the FAA refreshes the data roughly weekly).
"""
from __future__ import annotations
import io
import os
import sys
import tempfile
import urllib.request
import zipfile

from flighttrack.faa import build_faa_db

URL = "https://registry.faa.gov/database/ReleasableAircraft.zip"


def main(db_path: str = "data/faa.db") -> None:
    print(f"Downloading {URL} …", flush=True)
    req = urllib.request.Request(URL, headers={"User-Agent": "sdr-flight/1.0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        blob = r.read()
    print(f"  downloaded {len(blob) / 1e6:.1f} MB; extracting MASTER.txt + ACFTREF.txt", flush=True)
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            names = {n.upper(): n for n in z.namelist()}
            z.extract(names["MASTER.TXT"], td)
            z.extract(names["ACFTREF.TXT"], td)
            master = os.path.join(td, names["MASTER.TXT"])
            acftref = os.path.join(td, names["ACFTREF.TXT"])
        n = build_faa_db(master, acftref, db_path)
    print(f"  built {db_path}: {n} aircraft", flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/faa.db")
