from __future__ import annotations
import logging
import httpx

log = logging.getLogger(__name__)

AERO_BASE = "https://aeroapi.flightaware.com/aeroapi"


def _airport(a: dict | None) -> dict | None:
    if not isinstance(a, dict):
        return None
    return {
        "code": a.get("code_iata") or a.get("code_icao") or a.get("code"),
        "city": a.get("city"),
        "name": a.get("name"),
    }


def _pick_active(flights: list[dict]) -> dict | None:
    """Pick the flight that matches what we're seeing right now: prefer one that's
    airborne (departed, not yet arrived); else the most relevant recent entry."""
    if not flights:
        return None
    airborne = [f for f in flights if f.get("actual_off") and not f.get("actual_on")]
    if airborne:
        return airborne[-1]
    # not airborne: prefer ones that have departed; else the last listed
    departed = [f for f in flights if f.get("actual_off")]
    return (departed or flights)[-1]


async def fetch_flight(ident: str, client: httpx.AsyncClient) -> dict:
    """Look up the ACTUAL current flight for an ident via FlightAware AeroAPI.
    `client` must be configured with base_url=AERO_BASE and the `x-apikey` header.
    Degrades gracefully; `lookup_ok` is True only on a definitive answer (gates caching)."""
    out = {
        "callsign": ident, "airline": None, "origin": None, "destination": None,
        "aircraft_type": None, "registration": None, "route_known": False, "lookup_ok": False,
    }
    try:
        r = await client.get(f"/flights/{ident}")
        if r.status_code == 200:
            out["lookup_ok"] = True
            f = _pick_active(r.json().get("flights", []))
            if f:
                out["origin"] = _airport(f.get("origin"))
                out["destination"] = _airport(f.get("destination"))
                out["route_known"] = bool(out["origin"] and out["destination"])
                out["aircraft_type"] = f.get("aircraft_type")
                out["registration"] = f.get("registration")
                out["airline"] = f.get("operator_iata") or f.get("operator")
        elif r.status_code in (400, 404):
            out["lookup_ok"] = True   # definitively no such ident
        # 401/403 (bad key), 429 (rate limit), 5xx -> transient: leave lookup_ok False
        else:
            log.warning("aeroapi %s for %s", r.status_code, ident)
    except Exception as e:  # network/timeout -> transient, do not cache
        log.warning("aeroapi lookup failed for %s: %s", ident, e)
    return out
