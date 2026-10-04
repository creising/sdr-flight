from __future__ import annotations
from dataclasses import dataclass
from flighttrack.models import AircraftView
from flighttrack.store import Store


@dataclass
class _Open:
    contact_id: int
    last_pos_ts: float


class Recorder:
    def __init__(self, store: Store, snapshot_interval_s: float = 15.0):
        self.store = store
        self.interval = snapshot_interval_s
        self._open: dict[str, _Open] = {}

    def on_tick(self, views: list[AircraftView], now: float) -> None:
        seen: set[str] = set()
        for v in views:
            seen.add(v.icao)
            oc = self._open.get(v.icao)
            if oc is None:
                cid = self.store.open_contact(v.icao, v.callsign, now)
                oc = _Open(contact_id=cid, last_pos_ts=float("-inf"))
                self._open[v.icao] = oc
            self.store.update_contact(oc.contact_id, now, alt_ft=v.alt_ft,
                                      distance_km=v.distance_km,
                                      elevation_deg=v.elevation_deg, callsign=v.callsign)
            if v.lat is not None and v.lon is not None and (now - oc.last_pos_ts) >= self.interval:
                self.store.add_position(oc.contact_id, now, v.lat, v.lon, v.alt_ft,
                                        v.ground_speed_kt, v.track_deg, v.rssi)
                oc.last_pos_ts = now
        for icao in list(self._open):
            if icao not in seen:
                self.store.close_contact(self._open[icao].contact_id)
                del self._open[icao]
