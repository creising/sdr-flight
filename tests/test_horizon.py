import json
from flighttrack.horizon import Horizon


def test_load_none_returns_none():
    assert Horizon.load(None) is None


def test_load_missing_file_returns_none(tmp_path):
    assert Horizon.load(str(tmp_path / "nope.json")) is None


def test_load_malformed_returns_none(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ not json")
    assert Horizon.load(str(p)) is None


def test_load_empty_profile_returns_none(tmp_path):
    p = tmp_path / "empty.json"
    p.write_text(json.dumps({"az_step_deg": 1.0, "horizon_deg": []}))
    assert Horizon.load(str(p)) is None


def test_load_valid(tmp_path):
    p = tmp_path / "h.json"
    p.write_text(json.dumps({"az_step_deg": 90.0, "horizon_deg": [0, 10, 20, 30]}))
    h = Horizon.load(str(p))
    assert h is not None and h.obstruction_deg(90.0) == 10.0


def test_obstruction_interpolates_and_wraps():
    h = Horizon(90.0, [0.0, 10.0, 20.0, 30.0])   # samples at 0,90,180,270
    assert h.obstruction_deg(0.0) == 0.0
    assert h.obstruction_deg(45.0) == 5.0         # halfway 0->10
    assert h.obstruction_deg(90.0) == 10.0
    assert h.obstruction_deg(315.0) == 15.0       # halfway 30->0 across the seam
    assert h.obstruction_deg(360.0) == 0.0        # wraps to 0
    assert h.obstruction_deg(-45.0) == 15.0       # negative bearing normalises
