import textwrap
import pytest
from flighttrack.config import load_settings


def test_loads_yaml_with_receiver(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent("""
        source: synthetic
        receiver:
          lat: 40.0
          lon: -105.0
          alt_m: 1600
        poll_interval_s: 0.5
    """))
    s = load_settings(str(cfg))
    assert s.source == "synthetic"
    assert s.receiver.lat == 40.0
    assert s.receiver.alt_m == 1600
    assert s.poll_interval_s == 0.5
    assert s.host == "127.0.0.1"  # default


def test_missing_file_exits_with_message(tmp_path, capsys):
    with pytest.raises(SystemExit):
        load_settings(str(tmp_path / "nope.yaml"))


def test_missing_receiver_exits(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("source: synthetic\n")
    with pytest.raises(SystemExit):
        load_settings(str(cfg))


def test_malformed_yaml_exits(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("source: [unclosed\n")  # invalid YAML syntax
    with pytest.raises(SystemExit):
        load_settings(str(cfg))


def test_non_mapping_yaml_exits(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("- a\n- b\n")  # a list, not a mapping
    with pytest.raises(SystemExit):
        load_settings(str(cfg))
