import json
import pathlib
import httpx
import pytest
from flighttrack.config import Settings, Receiver, ReplayConfig, Dump1090Config
from flighttrack.sources import dump1090, replay
from flighttrack.sources.factory import build_source
from flighttrack.sources.synthetic import SyntheticSource

FIX = pathlib.Path(__file__).parent / "fixtures" / "aircraft_sample.json"


def test_parse_maps_and_cleans_fields():
    doc = json.loads(FIX.read_text())
    planes = dump1090.parse_aircraft_json(doc)
    assert len(planes) == 3
    ual = next(p for p in planes if p.icao == "a1b2c3")
    assert ual.callsign == "UAL123"           # trimmed
    assert ual.alt_ft == 35000 and ual.lat == 40.1
    ground = next(p for p in planes if p.icao == "d4e5f6")
    assert ground.alt_ft is None               # "ground" -> None
    assert ground.lat is None                  # no position
    minimal = next(p for p in planes if p.icao == "112233")
    assert minimal.callsign is None and minimal.ground_speed_kt is None


def test_parse_skips_records_without_hex():
    planes = dump1090.parse_aircraft_json({"aircraft": [{"flight": "X"}, {"hex": "aa"}]})
    assert [p.icao for p in planes] == ["aa"]


async def test_dump1090_source_swallows_errors():
    transport = httpx.MockTransport(lambda req: httpx.Response(500))
    client = httpx.AsyncClient(transport=transport)
    src = dump1090.Dump1090Source("http://x/data/aircraft.json", client=client)
    assert await src.poll() == []              # no raise
    await client.aclose()


async def test_dump1090_source_parses_ok():
    body = FIX.read_text()
    transport = httpx.MockTransport(lambda req: httpx.Response(200, text=body))
    client = httpx.AsyncClient(transport=transport)
    src = dump1090.Dump1090Source("http://x/data/aircraft.json", client=client)
    planes = await src.poll()
    assert len(planes) == 3
    await client.aclose()


async def test_dump1090_aclose_closes_client():
    client = httpx.AsyncClient()
    src = dump1090.Dump1090Source("http://x/data/aircraft.json", client=client)
    await src.aclose()
    assert client.is_closed


async def test_dump1090_reads_local_file(tmp_path):
    f = tmp_path / "aircraft.json"
    f.write_text(FIX.read_text())
    src = dump1090.Dump1090Source(str(f))          # a filesystem path, not an http url
    planes = await src.poll()
    assert len(planes) == 3
    await src.aclose()                             # must be a no-op for the file source


async def test_dump1090_file_missing_is_swallowed(tmp_path):
    src = dump1090.Dump1090Source(str(tmp_path / "nope.json"))
    assert await src.poll() == []                  # decoder not up yet -> no crash


async def test_replay_reads_frames(tmp_path):
    cap = tmp_path / "cap.jsonl"
    f0 = {"now": 0.0, "aircraft": [{"hex": "aa", "lat": 1.0, "lon": 2.0, "alt_baro": 5000, "seen": 0}]}
    f1 = {"now": 1.0, "aircraft": [{"hex": "aa", "lat": 1.1, "lon": 2.0, "alt_baro": 5000, "seen": 0}]}
    cap.write_text(json.dumps(f0) + "\n" + json.dumps(f1) + "\n")
    clock = {"t": 0.0}
    src = replay.ReplaySource(str(cap), loop=True, clock=lambda: clock["t"])
    p0 = await src.poll()
    assert p0[0].lat == 1.0
    clock["t"] = 1.0
    p1 = await src.poll()
    assert p1[0].lat == 1.1


def test_factory_requires_replay_config():
    s = Settings(source="replay", receiver=Receiver(lat=0, lon=0), replay=None)
    with pytest.raises(ValueError):
        build_source(s)


def test_factory_builds_synthetic():
    s = Settings(source="synthetic", receiver=Receiver(lat=0, lon=0))
    assert isinstance(build_source(s), SyntheticSource)
