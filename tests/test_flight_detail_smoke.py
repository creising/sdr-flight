import socket, threading, time
import pytest, uvicorn
from flighttrack.config import Settings, Receiver, SyntheticConfig, DbConfig
from flighttrack.app import create_app

pytestmark = pytest.mark.e2e


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture
def server():
    port = _free_port()
    s = Settings(source="synthetic", receiver=Receiver(lat=40.0, lon=-105.0, alt_m=1600.0),
                 synthetic=SyntheticConfig(num_aircraft=4, seed=1), poll_interval_s=0.05,
                 db=DbConfig(path=":memory:"), port=port)
    app = create_app(s)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=srv.run, daemon=True); th.start()
    for _ in range(50):
        if srv.started: break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}", app
    srv.should_exit = True; th.join(timeout=5)


def test_clicking_plane_shows_route(server, page):
    url, app = server
    page.goto(url)
    page.wait_for_selector(".contact-row", timeout=8000)
    contacts = page.evaluate(
        "async () => { const s = await import('/static/js/state.js'); "
        "return s.state.contacts.map(c => ({icao: c.icao, callsign: c.callsign})); }")
    # Pre-seed the flight cache so /api/flight returns a known route without calling adsbdb.
    for c in contacts:
        cs = c["callsign"] or c["icao"]
        app.state.store.put_cached_flight(f"{cs}|{c['icao']}", {
            "callsign": cs, "airline": "American Airlines",
            "origin": {"code": "PHL", "city": "Philadelphia", "name": "x"},
            "destination": {"code": "TPA", "city": "Tampa", "name": "y"},
            "aircraft_type": "A321", "registration": "N1", "route_known": True,
        }, time.time())
    page.locator(".contact-row").first.click()
    page.wait_for_selector(".lk-route .rt-leg", timeout=6000)
    txt = page.locator(".lk-route").inner_text()
    assert "PHL" in txt and "TPA" in txt and "American Airlines" in txt
