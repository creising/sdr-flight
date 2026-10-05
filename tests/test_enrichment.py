import httpx
import pytest
from flighttrack.enrichment import fetch_flight

ROUTE_OK = {"response": {"flightroute": {
    "callsign": "AAL2322",
    "airline": {"name": "American Airlines", "icao": "AAL"},
    "origin": {"iata_code": "PHL", "icao_code": "KPHL", "municipality": "Philadelphia",
               "name": "Philadelphia International Airport"},
    "destination": {"iata_code": "TPA", "icao_code": "KTPA", "municipality": "Tampa",
                    "name": "Tampa International Airport"},
}}}
AIRCRAFT_OK = {"response": {"aircraft": {"type": "Airbus A321", "registration": "N123AA"}}}


def _transport(route_status=200, route_body=ROUTE_OK, ac_status=200, ac_body=AIRCRAFT_OK):
    def handler(req: httpx.Request) -> httpx.Response:
        if "/callsign/" in req.url.path:
            return httpx.Response(route_status, json=route_body)
        if "/aircraft/" in req.url.path:
            return httpx.Response(ac_status, json=ac_body)
        return httpx.Response(404)
    return httpx.MockTransport(handler)


async def test_fetch_flight_route_and_aircraft():
    client = httpx.AsyncClient(transport=_transport())
    r = await fetch_flight("AAL2322", "ad4c2a", client)
    assert r["route_known"] is True
    assert r["lookup_ok"] is True
    assert r["airline"] == "American Airlines"
    assert r["origin"]["code"] == "PHL" and r["origin"]["city"] == "Philadelphia"
    assert r["destination"]["code"] == "TPA"
    assert r["aircraft_type"] == "Airbus A321" and r["registration"] == "N123AA"
    await client.aclose()


async def test_fetch_flight_definitive_not_found_is_lookup_ok():
    # a real 404 ("unknown callsign") is a definitive answer -> cacheable
    client = httpx.AsyncClient(transport=_transport(
        route_status=404, route_body={"response": "unknown callsign"},
        ac_status=404, ac_body={"response": "unknown aircraft"}))
    r = await fetch_flight("ZZZ999", "000000", client)
    assert r["route_known"] is False and r["lookup_ok"] is True
    assert r["origin"] is None and r["aircraft_type"] is None
    await client.aclose()


async def test_fetch_flight_transient_error_not_cacheable():
    def boom(req): raise httpx.ConnectError("down")
    client = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    r = await fetch_flight("AAL2322", "ad4c2a", client)
    assert r["route_known"] is False and r["lookup_ok"] is False   # don't cache a transient failure
    assert r["callsign"] == "AAL2322"
    await client.aclose()


async def test_fetch_flight_rate_limited_not_cacheable():
    client = httpx.AsyncClient(transport=_transport(route_status=429, route_body={}))
    r = await fetch_flight("AAL2322", "ad4c2a", client)
    assert r["lookup_ok"] is False   # 429 is transient -> retry later, don't cache
    await client.aclose()
