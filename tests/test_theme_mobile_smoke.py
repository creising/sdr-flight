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


def test_mobile_details_dismiss_collapses_sheet(server_url, page):
    # On a phone, bringing up a flight's details expands the sheet over the map;
    # closing the details (×) must collapse it back so the map is usable again.
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(server_url)
    page.wait_for_selector(".sheet-handle", timeout=8000)
    page.click(".sheet-handle")                       # expand so the list is reachable
    page.wait_for_selector(".contact-row", timeout=8000)
    page.locator(".contact-row").first.click()
    assert page.locator("#sidebar").evaluate("el => el.classList.contains('expanded')")
    # The card rebuilds once when flight-detail resolves; wait for that settle.
    page.wait_for_selector(".lk-route:not(.loading)", timeout=6000)
    page.locator(".lk-close").click()
    # Sheet collapses back to peek so the map is visible again.
    assert not page.locator("#sidebar").evaluate("el => el.classList.contains('expanded')")


def test_mobile_close_button_collapses(server_url, page):
    # The ✕ on the expanded sheet collapses it back to the map.
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(server_url)
    page.wait_for_selector(".sheet-handle", timeout=8000)
    page.click(".sheet-handle")                       # expand
    assert page.locator("#sidebar").evaluate("el => el.classList.contains('expanded')")
    page.locator(".sheet-close").click()
    assert not page.locator("#sidebar").evaluate("el => el.classList.contains('expanded')")


def test_mobile_handle_drag_down_collapses(server_url, page):
    # Dragging the handle down must collapse the sheet (not tap, not pan the map).
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(server_url)
    page.wait_for_selector(".sheet-handle", timeout=8000)
    page.click(".sheet-handle")                       # expand
    assert page.locator("#sidebar").evaluate("el => el.classList.contains('expanded')")
    box = page.locator(".sheet-handle").bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(cx, cy)
    page.mouse.down()
    page.mouse.move(cx, cy + 90, steps=8)             # drag down past the swipe threshold
    page.mouse.up()
    assert not page.locator("#sidebar").evaluate("el => el.classList.contains('expanded')")


def test_mobile_handle_stays_pinned_when_scrolled(server_url, page):
    # The pull-down handle must stay visible at the top of the expanded sheet even
    # after the card grows/scrolls (e.g. the aircraft photo loads).
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(server_url)
    page.wait_for_selector(".sheet-handle", timeout=8000)
    page.click(".sheet-handle")
    page.wait_for_selector(".contact-row", timeout=8000)
    page.locator(".contact-row").first.click()
    page.wait_for_selector(".lk-route:not(.loading)", timeout=6000)
    # Scroll the sheet to the bottom, then confirm the handle is still pinned at top.
    gap = page.evaluate("""() => {
      const sb = document.querySelector('#sidebar');
      sb.scrollTop = sb.scrollHeight;
      const h = document.querySelector('.sheet-bar').getBoundingClientRect();
      const s = sb.getBoundingClientRect();
      return h.top - s.top;   // ~0 when sticky-pinned to the top
    }""")
    assert gap < 8
