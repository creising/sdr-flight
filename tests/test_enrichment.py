import httpx
import pytest
from flighttrack.enrichment import fetch_flight, AERO_BASE

FLIGHTS_OK = {"flights": [
    {  # scheduled-only future leg (no actual_off) — should NOT be picked
        "ident": "SWA1278", "aircraft_type": "B737",
        "origin": {"code_iata": "XXX", "name": "Should Not Pick", "city": "Nowhere"},
        "destination": {"code_iata": "YYY", "name": "Nope", "city": "Nowhere"},
        "actual_off": None, "actual_on": None,
    },
    {  # currently airborne — should be picked
        "ident": "SWA1278", "operator": "SWA", "operator_iata": "WN",
        "registration": "N8888A", "aircraft_type": "B738",
        "origin": {"code_iata": "BNA", "code_icao": "KBNA", "name": "Nashville Intl", "city": "Nashville"},
        "destination": {"code_iata": "MCO", "code_icao": "KMCO", "name": "Orlando Intl", "city": "Orlando"},
        "actual_off": "2026-10-05T01:00:00Z", "actual_on": None,
    },
]}


def _client(status=200, body=FLIGHTS_OK):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers.get("x-apikey") == "TESTKEY"      # key sent as header
        assert "/flights/" in req.url.path
        return httpx.Response(status, json=body)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=AERO_BASE,
                             headers={"x-apikey": "TESTKEY"})


async def test_fetch_flight_picks_airborne_flight():
    client = _client()
    r = await fetch_flight("SWA1278", client)
    assert r["lookup_ok"] is True and r["route_known"] is True
    assert r["origin"]["code"] == "BNA" and r["origin"]["city"] == "Nashville"
    assert r["destination"]["code"] == "MCO"
    assert r["aircraft_type"] == "B738" and r["registration"] == "N8888A"
    assert r["airline"] in ("WN", "SWA")
    await client.aclose()


async def test_fetch_flight_404_is_definitive():
    client = _client(status=404, body={"title": "not found"})
    r = await fetch_flight("ZZZ999", client)
    assert r["lookup_ok"] is True and r["route_known"] is False
    await client.aclose()


async def test_fetch_flight_401_is_transient_not_cacheable():
    client = _client(status=401, body={"title": "bad key"})
    r = await fetch_flight("SWA1278", client)
    assert r["lookup_ok"] is False   # auth/rate/5xx -> don't cache
    await client.aclose()


async def test_fetch_flight_network_error_not_cacheable():
    def boom(req): raise httpx.ConnectError("down")
    client = httpx.AsyncClient(transport=httpx.MockTransport(boom), base_url=AERO_BASE,
                               headers={"x-apikey": "TESTKEY"})
    r = await fetch_flight("SWA1278", client)
    assert r["lookup_ok"] is False and r["callsign"] == "SWA1278"
    await client.aclose()
