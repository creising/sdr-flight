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


def test_live_map_renders_markers(server, page):
    url, _ = server
    page.goto(url)
    page.wait_for_selector(".leaflet-container", timeout=8000)
    page.wait_for_selector(".ac-marker", timeout=8000)       # a chevron aircraft marker
    assert page.locator(".ring-label").count() >= 1           # range-ring labels


def test_tracking_draws_path_and_projection(server, page):
    url, _ = server
    page.goto(url)
    page.wait_for_selector(".contact-row", timeout=8000)
    page.locator(".contact-row").first.click()
    page.wait_for_selector(".lk-track", timeout=6000)
    page.locator(".lk-track").click()
    # Button flips to TRACKING and the map gains a flown-path + projection ray.
    assert page.locator(".lk-track").inner_text().strip() == "TRACKING"
    page.wait_for_selector(".track-path", timeout=6000)
    page.wait_for_selector(".track-projection", timeout=6000)
    page.wait_for_selector(".wp-label", timeout=6000)      # per-minute waypoint labels
    page.wait_for_timeout(300)   # let a couple of live ticks extend the path
    assert page.locator(".track-path").count() >= 1
    assert page.locator(".track-projection").count() >= 1
    assert page.locator(".wp-label").count() == 5          # one dot-label per minute to 5
    assert page.locator(".wp-label").first.inner_text().strip() == "1′"
    # Toggling off removes everything and resets the button.
    page.locator(".lk-track").click()
    assert page.locator(".lk-track").inner_text().strip() == "TRACK"
    page.wait_for_selector(".track-path", state="detached", timeout=6000)
    assert page.locator(".track-projection").count() == 0
    assert page.locator(".wp-label").count() == 0


def test_dest_point_projects_due_north(server, page):
    # Geodesic helper: 60 nmi due north ≈ +1° latitude, longitude unchanged.
    url, _ = server
    page.goto(url)
    page.wait_for_selector(".leaflet-container", timeout=8000)
    res = page.evaluate(
        "async () => { const u = await import('/static/js/util.js'); "
        "return u.destPoint(40.0, -105.0, 0, 60); }")
    assert abs(res[0] - 41.0) < 0.05
    assert abs(res[1] + 105.0) < 0.01


def test_recenter_button_returns_to_receiver(server, page):
    url, _ = server
    page.goto(url)
    page.wait_for_selector(".leaflet-container", timeout=8000)
    # Pan far away, then re-center.
    page.evaluate("async () => { (await import('/static/js/map.js')).getMap().setView([50, -90], 7); }")
    page.locator("#recenter").click()
    c = page.evaluate("async () => { const m = (await import('/static/js/map.js')).getMap();"
                      " const ll = m.getCenter(); return {lat: ll.lat, lng: ll.lng, z: m.getZoom()}; }")
    assert abs(c["lat"] - 40.0) < 0.01 and abs(c["lng"] + 105.0) < 0.01   # receiver in the fixture
    assert c["z"] == 10


def test_sidebar_shell(server, page):
    url, _ = server
    page.goto(url)
    page.wait_for_selector("#sidebar .wordmark", timeout=8000)
    assert page.locator("#sidebar .wordmark").inner_text().strip() == "OVERHEAD"
    assert page.locator(".mode-seg").count() == 2             # Live / Replay segments
    assert page.locator("#status").count() == 1
