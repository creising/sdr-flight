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
                 db=DbConfig(path=":memory:"),
                 logging=LoggingConfig(snapshot_interval_s=0.0),
                 port=port)
    server = uvicorn.Server(uvicorn.Config(create_app(s), host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True); th.start()
    for _ in range(50):
        if server.started: break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True; th.join(timeout=5)


def test_switch_to_playback_loads_history(server_url, page):
    page.goto(server_url)
    page.wait_for_selector(".plane", timeout=8000)      # live first
    time.sleep(1.5)                                     # let positions accumulate in the DB
    page.click("#mode-playback")
    page.wait_for_selector("#playback-controls:not([hidden])", timeout=4000)
    # history fetched for the window; scrubbing to the end should show the playtime label
    page.wait_for_function("document.getElementById('playtime').textContent.length > 0", timeout=6000)
