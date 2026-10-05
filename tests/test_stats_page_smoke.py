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
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True); th.start()
    for _ in range(50):
        if server.started: break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}", app
    server.should_exit = True; th.join(timeout=5)


def test_stats_renders_tiles_clock_airlines(server, page):
    url, app = server
    import time as _t
    store = app.state.store
    base = _t.time()
    for cs in ["UAL1", "UAL2", "DAL9", "N123AB"]:
        cid = store.open_contact(cs[:3].lower(), cs, base)
        store.update_contact(cid, base, alt_ft=30000, distance_km=10.0, elevation_deg=20.0)
    page.goto(url + "/stats")
    page.wait_for_selector(".headline-tile", timeout=8000)
    assert page.locator(".headline-tile").count() == 2
    assert page.locator(".record-tile").count() == 4
    assert page.locator("#radial svg rect").count() == 24
    page.wait_for_selector(".airline-row", timeout=8000)
    assert "Private / GA" in page.content()


def test_stats_escapes_malicious_callsign(server, page):
    url, app = server
    import time as _t
    store = app.state.store
    base = _t.time()
    cid = store.open_contact("evil", "<img src=x onerror='window.__xss=1'>", base)
    store.update_contact(cid, base, alt_ft=1000, distance_km=0.05, elevation_deg=85.0)
    page.goto(url + "/stats")
    page.wait_for_selector(".record-tile", timeout=8000)
    page.wait_for_timeout(300)
    assert page.evaluate("window.__xss") is None
