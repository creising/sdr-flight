import socket, threading, time
import pytest, uvicorn
from flighttrack.config import Settings, Receiver, SyntheticConfig, DbConfig, LoggingConfig
from flighttrack.app import create_app

pytestmark = pytest.mark.e2e


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture
def server_url():
    port = _free_port()
    s = Settings(source="synthetic", receiver=Receiver(lat=40.0, lon=-105.0, alt_m=1600.0),
                 synthetic=SyntheticConfig(num_aircraft=4, seed=1), poll_interval_s=0.05,
                 db=DbConfig(path=":memory:"), logging=LoggingConfig(snapshot_interval_s=0.0),
                 port=port)
    srv = uvicorn.Server(uvicorn.Config(create_app(s), host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=srv.run, daemon=True); th.start()
    for _ in range(50):
        if srv.started: break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True; th.join(timeout=5)


def test_map_tooltip_escapes_callsign(server_url, page):
    # #1 CRITICAL: Leaflet bindTooltip(string) is an innerHTML sink.
    page.goto(server_url)
    page.wait_for_selector(".ac-marker", timeout=8000)
    # enter replay so the live loop stops overwriting our injected marker
    page.click('.mode-seg[data-mode="replay"]')
    page.wait_for_selector('#app[data-mode="replay"]', timeout=5000)
    # wait until the initial replay frame() has run (clock populated) so it won't overwrite our marker
    page.wait_for_function("document.querySelector('.tl-clock') && document.querySelector('.tl-clock').textContent.length > 0", timeout=5000)
    page.wait_for_timeout(200)
    page.evaluate("""async () => {
        const m = await import('/static/js/map.js');
        m.renderAircraft([{icao:'evil', callsign:"<img src=x onerror='window.__xss=1'>",
          lat:40.02, lon:-105.0, alt_ft:12000, track_deg:0}], {});
    }""")
    page.wait_for_selector(".ac-marker", timeout=5000)
    page.locator(".ac-marker").hover()
    page.wait_for_timeout(400)
    assert page.evaluate("window.__xss") is None
    # and the tooltip content is escaped text, not markup
    assert page.locator(".leaflet-tooltip").count() >= 1


def test_selection_highlights_and_labels(server_url, page):
    # #2: clicking a contact row selects the aircraft (marker highlight); data-block labels render.
    page.goto(server_url)
    page.wait_for_selector(".contact-row", timeout=8000)
    assert page.locator(".ac-label").count() >= 1           # labelsOn default -> data-block labels
    page.locator(".contact-row").first.click()
    page.wait_for_selector(".ac-wrap.selected", timeout=5000)
    assert page.locator(".ac-wrap.selected").count() == 1


def test_reduced_motion_playback_advances(server_url, page):
    # #3: under prefers-reduced-motion, pressing play must still advance the clock.
    page.emulate_media(reduced_motion="reduce")
    page.goto(server_url)
    page.wait_for_selector("#timeline .tl-hist", timeout=8000)
    time.sleep(1.2)                                          # accumulate history
    bb = page.locator("#timeline .tl-hist").bounding_box()
    page.mouse.click(bb["x"] + bb["width"] - 8, bb["y"] + 20)   # enter replay near 'now'
    page.wait_for_selector(".tl-clock", timeout=5000)
    page.click(".playpause")
    first = page.locator(".tl-clock").inner_text()
    page.wait_for_timeout(1200)
    assert page.locator(".tl-clock").inner_text() != first   # clock advanced
