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


def test_theme_toggle_to_light(server_url, page):
    page.emulate_media(color_scheme="dark")   # known dark baseline (auto -> dark)
    page.goto(server_url)
    page.wait_for_selector(".theme-toggle", timeout=8000)
    dark_bg = page.eval_on_selector("body", "b => getComputedStyle(b).backgroundColor")
    # cycle until pref == light
    for _ in range(3):
        if page.evaluate("document.documentElement.getAttribute('data-theme-pref')") == "light":
            break
        page.click(".theme-toggle")
    assert page.evaluate("document.documentElement.getAttribute('data-theme')") == "light"
    light_bg = page.eval_on_selector("body", "b => getComputedStyle(b).backgroundColor")
    assert light_bg != dark_bg


def test_auto_respects_prefers_color_scheme(server_url, page):
    page.emulate_media(color_scheme="light")
    page.goto(server_url)
    page.wait_for_selector("#sidebar .wordmark", timeout=8000)
    assert page.evaluate("document.documentElement.getAttribute('data-theme')") == "light"


def test_mobile_bottom_sheet(server_url, page):
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(server_url)
    page.wait_for_selector(".sheet-handle", timeout=8000)
    assert page.locator("#topbar").is_visible()
    assert not page.locator("#sidebar").evaluate("el => el.classList.contains('expanded')")
    page.click(".sheet-handle")
    assert page.locator("#sidebar").evaluate("el => el.classList.contains('expanded')")
