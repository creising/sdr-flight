from __future__ import annotations
from flighttrack.config import Settings
from flighttrack.sources.base import AircraftSource
from flighttrack.sources.synthetic import SyntheticSource
from flighttrack.sources.replay import ReplaySource
from flighttrack.sources.dump1090 import Dump1090Source


def build_source(settings: Settings) -> AircraftSource:
    if settings.source == "synthetic":
        return SyntheticSource(settings.receiver, settings.synthetic)
    if settings.source == "replay":
        if settings.replay is None:
            raise ValueError("source=replay requires a `replay:` config block")
        return ReplaySource(settings.replay.path, settings.replay.loop)
    if settings.source == "dump1090":
        return Dump1090Source(settings.dump1090.url)
    raise ValueError(f"unknown source: {settings.source}")
