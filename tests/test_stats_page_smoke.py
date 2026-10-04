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


def test_stats_page_renders_tiles_and_chart(server, page):
    server_url, _ = server
    page.goto(server_url + "/stats")
    page.wait_for_selector(".tile", timeout=8000)
    page.wait_for_selector("#perhour svg", timeout=8000)      # chart rendered
    assert page.locator(".tile").count() >= 4
    # 24 hourly buckets always render a rect each (zero-height on empty hours),
    # so assert DOM presence rather than visibility.
    assert page.locator("#perhour svg rect").count() >= 1
    assert page.locator("#airlines svg").count() == 1


def test_stats_escapes_malicious_callsign(server, page):
    server_url, app = server
    # Seed a very-close contact whose callsign is an XSS payload -> it becomes the
    # "closest pass" tile. If unescaped, the onerror fires and sets window.__xss.
    base = time.time()
    store = app.state.store
    cid = store.open_contact("evil", "<img src=x onerror='window.__xss=1'>", base)
    store.update_contact(cid, base, alt_ft=1000, distance_km=0.05, elevation_deg=85.0)
    page.goto(server_url + "/stats")
    page.wait_for_selector(".tile", timeout=8000)
    page.wait_for_timeout(300)
    assert page.evaluate("window.__xss") is None            # payload never executed
    # the literal text is present (escaped), proving it rendered as text not markup
    assert "onerror" in page.content()
