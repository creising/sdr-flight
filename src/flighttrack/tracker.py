from __future__ import annotations
from dataclasses import asdict
from flighttrack.config import Receiver
from flighttrack.models import RawAircraft, AircraftView
from flighttrack.geometry import enrich


class Tracker:
    def __init__(self, receiver: Receiver, stale_timeout_s: float = 30.0):
        self.rx = receiver
        self.stale = stale_timeout_s
        self._live: dict[str, tuple[float, AircraftView]] = {}
        self._now = 0.0

    def update(self, raw: list[RawAircraft], now: float) -> None:
        self._now = now
        for r in raw:
            self._live[r.icao] = (now, enrich(r, self.rx))
        cutoff = now - self.stale
        self._live = {k: v for k, v in self._live.items() if v[0] >= cutoff}

    def snapshot(self) -> list[AircraftView]:
        views = [v for _, v in self._live.values()]
        positioned = [v for v in views if v.distance_km is not None]
        positionless = [v for v in views if v.distance_km is None]
        positioned.sort(key=lambda v: v.distance_km)  # type: ignore[arg-type]
        return positioned + positionless

    def to_json(self) -> dict:
        return {
            "now": self._now,
            "receiver": {"lat": self.rx.lat, "lon": self.rx.lon, "alt_m": self.rx.alt_m},
            "aircraft": [asdict(v) for v in self.snapshot() if v.lat is not None],
        }
