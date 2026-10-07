from __future__ import annotations
from dataclasses import dataclass


@dataclass
class RawAircraft:
    icao: str
    callsign: str | None
    lat: float | None
    lon: float | None
    alt_ft: float | None
    ground_speed_kt: float | None
    track_deg: float | None
    seen_s: float
    rssi: float | None
    baro_rate: float | None = None   # vertical rate, ft/min (+ climb / - descent)
    squawk: str | None = None        # transponder code
    raw: dict | None = None          # the full source record (for the "more info" dialog)


@dataclass
class AircraftView:
    icao: str
    callsign: str | None
    lat: float | None
    lon: float | None
    alt_ft: float | None
    ground_speed_kt: float | None
    track_deg: float | None
    seen_s: float
    rssi: float | None
    baro_rate: float | None = None
    squawk: str | None = None
    raw: dict | None = None
    distance_km: float | None = None
    bearing_deg: float | None = None
    elevation_deg: float | None = None
    visible: bool = False       # above the local terrain skyline (if a profile is loaded)
