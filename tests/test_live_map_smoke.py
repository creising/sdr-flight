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


def test_sidebar_shell(server, page):
    url, _ = server
    page.goto(url)
    page.wait_for_selector("#sidebar .wordmark", timeout=8000)
    assert page.locator("#sidebar .wordmark").inner_text().strip() == "OVERHEAD"
    assert page.locator(".mode-seg").count() == 2             # Live / Replay segments
    assert page.locator("#status").count() == 1
