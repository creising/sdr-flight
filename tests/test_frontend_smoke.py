import socket
import threading
import time
import pytest
import uvicorn
from flighttrack.config import Settings, Receiver, SyntheticConfig
from flighttrack.app import create_app

pytestmark = pytest.mark.e2e


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture
def server_url():
    port = _free_port()
    settings = Settings(source="synthetic",
                        receiver=Receiver(lat=40.0, lon=-105.0, alt_m=1600.0),
                        synthetic=SyntheticConfig(num_aircraft=4, seed=1),
                        poll_interval_s=0.1, port=port)
    config = uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def test_map_renders_a_plane_marker(server_url, page):
    page.goto(server_url)
    # a synthetic plane marker should appear within a few seconds
    page.wait_for_selector(".plane", timeout=8000)
    assert page.locator("#status").inner_text() != "connecting…"
