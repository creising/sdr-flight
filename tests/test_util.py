import socket, threading, time
import pytest, uvicorn
from flighttrack.config import Settings, Receiver, DbConfig
from flighttrack.app import create_app

pytestmark = pytest.mark.e2e


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture
def server_url():
    port = _free_port()
    s = Settings(source="synthetic", receiver=Receiver(lat=40.0, lon=-105.0, alt_m=1600.0),
                 poll_interval_s=0.1, db=DbConfig(path=":memory:"), port=port)
    srv = uvicorn.Server(uvicorn.Config(create_app(s), host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=srv.run, daemon=True); th.start()
    for _ in range(50):
        if srv.started: break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True; th.join(timeout=5)


def test_util_helpers(server_url, page):
    page.goto(server_url)
    r = page.evaluate("""async () => {
        const u = await import('/static/js/util.js');
        return {
            overhead: u.isOverhead(50) && !u.isOverhead(39),
            compassN: u.compass16(0), compassE: u.compass16(90),
            fl: u.flightLevel(34000),
            altLow: u.altClass(8000), altHigh: u.altClass(34000), altNull: u.altClass(null),
            trendUp: u.altTrend(100, 200), trendFlat: u.altTrend(100, 100),
            bIn: u.bucketIndex(150, 100, 300, 2), bOut: u.bucketIndex(50, 100, 300, 2),
            esc: u.escapeHtml('<b>&"x'),
            lookup: u.lookupSubject([{icao:'a',elevation_deg:10},{icao:'b',elevation_deg:80}]).icao,
        };
    }""")
    assert r["overhead"] and r["compassN"] == "N" and r["compassE"] == "E"
    assert r["fl"] == "340" and r["altLow"] == "low" and r["altHigh"] == "high" and r["altNull"] is None
    assert r["trendUp"] == "up" and r["trendFlat"] == "flat"
    assert r["bIn"] == 0 and r["bOut"] == -1
    assert r["esc"] == "&lt;b&gt;&amp;&quot;x" and r["lookup"] == "b"
