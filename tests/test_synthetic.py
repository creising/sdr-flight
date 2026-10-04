import pytest
from flighttrack.config import Receiver, SyntheticConfig
from flighttrack.sources.synthetic import SyntheticSource


@pytest.fixture
def rx():
    return Receiver(lat=40.0, lon=-105.0, alt_m=1600.0)


async def test_poll_returns_configured_count(rx):
    clock = {"t": 0.0}
    src = SyntheticSource(rx, SyntheticConfig(num_aircraft=4, seed=1), clock=lambda: clock["t"])
    planes = await src.poll()
    assert len(planes) == 4
    assert all(p.icao for p in planes)


async def test_positions_change_over_time(rx):
    clock = {"t": 0.0}
    src = SyntheticSource(rx, SyntheticConfig(num_aircraft=3, seed=1), clock=lambda: clock["t"])
    first = {p.icao: (p.lat, p.lon) for p in await src.poll() if p.lat is not None}
    clock["t"] = 30.0
    second = {p.icao: (p.lat, p.lon) for p in await src.poll() if p.lat is not None}
    moved = [k for k in first if first[k] != second.get(k)]
    assert moved, "at least one positioned aircraft should have moved"


async def test_includes_a_positionless_aircraft(rx):
    clock = {"t": 0.0}
    src = SyntheticSource(rx, SyntheticConfig(num_aircraft=4, seed=1), clock=lambda: clock["t"])
    planes = await src.poll()
    assert any(p.lat is None and p.lon is None for p in planes)


async def test_deterministic_for_same_seed(rx):
    a = SyntheticSource(rx, SyntheticConfig(num_aircraft=4, seed=7), clock=lambda: 0.0)
    b = SyntheticSource(rx, SyntheticConfig(num_aircraft=4, seed=7), clock=lambda: 0.0)
    assert [p.icao for p in await a.poll()] == [p.icao for p in await b.poll()]
