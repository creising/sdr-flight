from __future__ import annotations
import asyncio
import json
import logging
import httpx
from flighttrack.models import RawAircraft

log = logging.getLogger(__name__)


def parse_aircraft_json(doc: dict) -> list[RawAircraft]:
    out: list[RawAircraft] = []
    for a in doc.get("aircraft", []):
        hexid = a.get("hex")
        if not hexid:
            continue
        alt = a.get("alt_baro")
        if alt == "ground" or not isinstance(alt, (int, float)):
            alt = None
        flight = a.get("flight")
        sq = a.get("squawk")
        out.append(RawAircraft(
            icao=hexid,
            callsign=flight.strip() if isinstance(flight, str) and flight.strip() else None,
            lat=a.get("lat"), lon=a.get("lon"),
            alt_ft=float(alt) if alt is not None else None,
            ground_speed_kt=a.get("gs"), track_deg=a.get("track"),
            seen_s=float(a.get("seen", 0.0)), rssi=a.get("rssi"),
            baro_rate=a.get("baro_rate") if a.get("baro_rate") is not None else a.get("geom_rate"),
            squawk=str(sq) if sq is not None else None,
            raw=a))
    return out


class Dump1090Source:
    """Reads dump1090's aircraft.json over HTTP, or directly from a local file when
    `url` is a filesystem path or file:// URL (clean single-box deploy, no web server)."""

    def __init__(self, url: str, client: httpx.AsyncClient | None = None):
        self.url = url
        if url.startswith("file://"):
            self._path = url[len("file://"):]
        elif url.startswith("/") or url.startswith("./"):
            self._path = url
        else:
            self._path = None
        self._client = None if self._path else (client or httpx.AsyncClient(timeout=3.0))

    def _read_file(self) -> dict:
        with open(self._path) as f:
            return json.load(f)

    async def poll(self) -> list[RawAircraft]:
        try:
            if self._path is not None:
                doc = await asyncio.to_thread(self._read_file)
                return parse_aircraft_json(doc)
            r = await self._client.get(self.url)
            r.raise_for_status()
            return parse_aircraft_json(r.json())
        except Exception as e:  # network down, file missing, bad JSON, decoder restarting
            log.warning("dump1090 poll failed: %s", e)
            return []

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
