from __future__ import annotations
import json
import time
from typing import Callable
from flighttrack.models import RawAircraft
from flighttrack.sources.dump1090 import parse_aircraft_json


class ReplaySource:
    """Plays back a JSONL capture of aircraft.json frames at recorded cadence."""

    def __init__(self, path: str, loop: bool = True, clock: Callable[[], float] = time.monotonic):
        with open(path) as f:
            self._frames = [json.loads(line) for line in f if line.strip()]
        if not self._frames:
            raise ValueError(f"replay capture {path} is empty")
        self._loop = loop
        self._clock = clock
        self._t0 = clock()
        base = self._frames[0].get("now", 0.0)
        self._offsets = [fr.get("now", 0.0) - base for fr in self._frames]
        self._span = self._offsets[-1] or 1.0

    async def poll(self) -> list[RawAircraft]:
        elapsed = self._clock() - self._t0
        if self._loop:
            elapsed = elapsed % (self._span + 1e-9)
        idx = 0
        for i, off in enumerate(self._offsets):
            if off <= elapsed:
                idx = i
            else:
                break
        return parse_aircraft_json(self._frames[idx])
