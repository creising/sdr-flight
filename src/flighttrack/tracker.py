from __future__ import annotations
from dataclasses import asdict, replace
from flighttrack.config import Receiver
from flighttrack.models import RawAircraft, AircraftView
from flighttrack.geometry import enrich

# Altitude sanity limits. ADS-B occasionally emits a single corrupt alt_baro frame
# (e.g. a 30k->114k jump) that would otherwise poison the live readout and the
# all-time max. We reject readings that are physically impossible and carry the
# last good altitude forward instead.
_ALT_CEILING_FT = 60000.0          # civilian/bizjet traffic tops out ~45-51k
_ALT_FLOOR_FT = -2000.0
_MAX_VERTICAL_FPM = 20000.0        # generous; real climb/descent is ~6-12k fpm
_MIN_SPIKE_FT = 5000.0             # ignore the rate test for small jumps


class Tracker:
    def __init__(self, receiver: Receiver, stale_timeout_s: float = 30.0):
        self.rx = receiver
        self.stale = stale_timeout_s
        self._live: dict[str, tuple[float, AircraftView]] = {}
        self._last_alt: dict[str, tuple[float, float]] = {}   # icao -> (ts, accepted alt)
        self._now = 0.0

    def _accept_alt(self, icao: str, alt: float | None, now: float) -> float | None:
        """Return the altitude to use for this frame, rejecting implausible spikes.

        A rejected frame carries the last good altitude forward (or None if there
        is no prior good reading). Accepted readings update the per-aircraft memory.
        """
        prev = self._last_alt.get(icao)
        if alt is None:
            return prev[1] if prev else None
        if alt > _ALT_CEILING_FT or alt < _ALT_FLOOR_FT:
            return prev[1] if prev else None
        if prev is not None:
            dt = now - prev[0]
            jump = abs(alt - prev[1])
            if dt > 0 and jump > _MIN_SPIKE_FT and jump / (dt / 60.0) > _MAX_VERTICAL_FPM:
                return prev[1]
        self._last_alt[icao] = (now, alt)
        return alt

    def update(self, raw: list[RawAircraft], now: float) -> None:
        self._now = now
        for r in raw:
            alt = self._accept_alt(r.icao, r.alt_ft, now)
            if alt != r.alt_ft:
                r = replace(r, alt_ft=alt)        # sanitize before enrich (elevation uses alt)
            self._live[r.icao] = (now, enrich(r, self.rx))
        cutoff = now - self.stale
        self._live = {k: v for k, v in self._live.items() if v[0] >= cutoff}
        self._last_alt = {k: v for k, v in self._last_alt.items() if k in self._live}

    def snapshot(self) -> list[AircraftView]:
        views = [v for _, v in self._live.values()]
        positioned = [v for v in views if v.distance_km is not None]
        positionless = [v for v in views if v.distance_km is None]
        positioned.sort(key=lambda v: v.distance_km)  # type: ignore[arg-type]
        return positioned + positionless

    def to_json(self) -> dict:
        def lean(v):
            return {k: val for k, val in asdict(v).items() if k != "raw"}   # keep the full WS stream small
        return {
            "now": self._now,
            "receiver": {"lat": self.rx.lat, "lon": self.rx.lon, "alt_m": self.rx.alt_m},
            "aircraft": [lean(v) for v in self.snapshot() if v.lat is not None],
        }

    def raw_for(self, icao: str) -> dict | None:
        entry = self._live.get(icao)
        return entry[1].raw if entry else None
