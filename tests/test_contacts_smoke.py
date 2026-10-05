import socket, threading, time
import pytest, uvicorn
from flighttrack.config import Settings, Receiver, SyntheticConfig, DbConfig
from flighttrack.app import create_app

pytestmark = pytest.mark.e2e


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture
def server_url():
    port = _free_port()
    s = Settings(source="synthetic", receiver=Receiver(lat=40.0, lon=-105.0, alt_m=1600.0),
                 synthetic=SyntheticConfig(num_aircraft=4, seed=1), poll_interval_s=0.05,
                 db=DbConfig(path=":memory:"), port=port)
    srv = uvicorn.Server(uvicorn.Config(create_app(s), host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=srv.run, daemon=True); th.start()
    for _ in range(50):
        if srv.started: break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True; th.join(timeout=5)


def test_contacts_and_lookup_render_live(server_url, page):
    page.goto(server_url)
    page.wait_for_selector(".contact-row", timeout=8000)      # populated from live synthetic data
    assert page.locator(".contact-row").count() >= 1
    assert "NO CONTACTS" not in page.locator("#lookup").inner_text()
    assert page.locator("#lookup .lk-call").count() == 1


def test_lookup_picks_highest_elevation(server_url, page):
    page.goto(server_url)
    page.wait_for_selector("#contacts", timeout=8000)
    call = page.evaluate("""async () => {
        const c = await import('/static/js/contacts.js');
        c.renderContacts([
          {icao:'low', callsign:'LOW1', lat:40.1, lon:-105.0, alt_ft:30000, distance_km:40, elevation_deg:10, track_deg:0, bearing_deg:0},
          {icao:'high', callsign:'HIGH9', lat:40.02, lon:-105.0, alt_ft:12000, distance_km:2, elevation_deg:85, track_deg:0, bearing_deg:90},
        ]);
        return document.querySelector('#lookup .lk-call').textContent;
    }""")
    assert call == "HIGH9"


def test_contacts_escape_xss(server_url, page):
    page.goto(server_url)
    page.wait_for_selector("#contacts", timeout=8000)
    page.evaluate("""async () => {
        const c = await import('/static/js/contacts.js');
        c.renderContacts([{icao:'evil', callsign:"<img src=x onerror='window.__xss=1'>",
          lat:40.05, lon:-105.0, alt_ft:1000, distance_km:1, elevation_deg:80, track_deg:0, bearing_deg:0}]);
    }""")
    page.wait_for_timeout(300)
    assert page.evaluate("window.__xss") is None
