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
    server = uvicorn.Server(uvicorn.Config(create_app(s), host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True); th.start()
    for _ in range(50):
        if server.started: break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True; th.join(timeout=5)


def test_stats_page_renders_tiles_and_chart(server_url, page):
    page.goto(server_url + "/stats")
    page.wait_for_selector(".tile", timeout=8000)
    page.wait_for_selector("#perhour svg", timeout=8000)      # chart rendered
    assert page.locator(".tile").count() >= 4
    # 24 hourly buckets always render a rect each (zero-height on empty hours),
    # so assert DOM presence rather than visibility.
    assert page.locator("#perhour svg rect").count() >= 1
    assert page.locator("#airlines svg").count() == 1
