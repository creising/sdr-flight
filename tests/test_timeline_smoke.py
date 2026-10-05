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


def test_live_strip_renders(server_url, page):
    page.goto(server_url)
    page.wait_for_selector("#timeline .bar", timeout=8000)
    assert page.locator("#timeline .bar").count() >= 1
    assert page.locator("#timeline .now-pill").count() == 1


def test_scrub_enters_replay_and_back(server_url, page):
    page.goto(server_url)
    page.wait_for_selector("#timeline .tl-hist", timeout=8000)
    time.sleep(1.0)  # accumulate some history
    page.locator("#timeline .tl-hist").click(position={"x": 60, "y": 20})
    page.wait_for_selector('#app[data-mode="replay"]', timeout=5000)
    page.wait_for_selector(".back-to-live", timeout=5000)
    assert page.locator(".tl-clock").count() == 1
    # window chip keeps us in replay
    page.locator('.win-chip[data-win="21600"]').click()
    assert page.locator('#app[data-mode="replay"]').count() == 1
    # back to live
    page.locator(".back-to-live").click()
    page.wait_for_selector('#app[data-mode="live"]', timeout=5000)
    assert page.locator("#timeline .now-pill").count() == 1


def test_scrub_to_empty_region_no_error(server_url, page):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(server_url)
    page.wait_for_selector("#timeline .tl-hist", timeout=8000)
    time.sleep(0.5)
    page.locator("#timeline .tl-hist").click(position={"x": 2, "y": 20})  # far left = ~24h ago, no data
    page.wait_for_selector('#app[data-mode="replay"]', timeout=5000)
    page.wait_for_timeout(300)
    assert errors == []
