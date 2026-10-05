from __future__ import annotations
import logging
import httpx

log = logging.getLogger(__name__)

BASE = "https://api.adsbdb.com/v0"


def _airport(a: dict | None) -> dict | None:
    if not isinstance(a, dict):
        return None
    return {
        "code": a.get("iata_code") or a.get("icao_code"),
        "city": a.get("municipality"),
        "name": a.get("name"),
    }


async def fetch_flight(callsign: str, hex: str | None, client: httpx.AsyncClient) -> dict:
    """Look up a flight's route (origin/destination + airline) by callsign and the
    aircraft (type/registration) by ICAO hex, via the free adsbdb.com API. Any failure
    degrades gracefully to unknown fields — never raises."""
    out = {
        "callsign": callsign, "airline": None, "origin": None, "destination": None,
        "aircraft_type": None, "registration": None, "route_known": False,
        "lookup_ok": False,   # True only on a DEFINITIVE answer (found or real 404); gates caching
    }
    try:
        r = await client.get(f"{BASE}/callsign/{callsign}")
        if r.status_code == 200:
            out["lookup_ok"] = True
            fr = r.json().get("response")
            fr = fr.get("flightroute") if isinstance(fr, dict) else None
            if fr:
                out["route_known"] = True
                out["airline"] = (fr.get("airline") or {}).get("name")
                out["origin"] = _airport(fr.get("origin"))
                out["destination"] = _airport(fr.get("destination"))
        elif r.status_code == 404:
            out["lookup_ok"] = True   # definitively not in the route DB
        # 429 / 5xx / other -> leave lookup_ok False (transient; retry next time)
    except Exception as e:  # network error / timeout -> transient, do not cache
        log.warning("adsbdb route lookup failed for %s: %s", callsign, e)

    if hex:
        try:
            r = await client.get(f"{BASE}/aircraft/{hex}")
            if r.status_code == 200:
                ac = r.json().get("response")
                ac = ac.get("aircraft") if isinstance(ac, dict) else None
                if ac:
                    out["aircraft_type"] = ac.get("type")
                    out["registration"] = ac.get("registration")
        except Exception as e:
            log.warning("adsbdb aircraft lookup failed for %s: %s", hex, e)

    return out
