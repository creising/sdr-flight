from __future__ import annotations
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
        out.append(RawAircraft(
            icao=hexid,
            callsign=flight.strip() if isinstance(flight, str) and flight.strip() else None,
            lat=a.get("lat"), lon=a.get("lon"),
            alt_ft=float(alt) if alt is not None else None,
            ground_speed_kt=a.get("gs"), track_deg=a.get("track"),
            seen_s=float(a.get("seen", 0.0)), rssi=a.get("rssi")))
    return out


class Dump1090Source:
    def __init__(self, url: str, client: httpx.AsyncClient | None = None):
        self.url = url
        self._client = client or httpx.AsyncClient(timeout=3.0)

    async def poll(self) -> list[RawAircraft]:
        try:
            r = await self._client.get(self.url)
            r.raise_for_status()
            return parse_aircraft_json(r.json())
        except Exception as e:  # network down, bad JSON, decoder restarting
            log.warning("dump1090 poll failed: %s", e)
            return []

    async def aclose(self) -> None:
        await self._client.aclose()
