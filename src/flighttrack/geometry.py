from __future__ import annotations
import math
from flighttrack.config import Receiver
from flighttrack.models import RawAircraft, AircraftView

_EARTH_KM = 6371.0088
_FT_TO_M = 0.3048


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * _EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def elevation_deg(ground_distance_km: float, observer_alt_m: float, target_alt_m: float) -> float:
    dh = target_alt_m - observer_alt_m
    d_m = ground_distance_km * 1000.0
    if d_m == 0.0:
        return 90.0 if dh > 0 else (-90.0 if dh < 0 else 0.0)
    return math.degrees(math.atan2(dh, d_m))


def enrich(raw: RawAircraft, receiver: Receiver, horizon=None) -> AircraftView:
    v = AircraftView(**raw.__dict__)
    if raw.lat is None or raw.lon is None:
        return v
    v.distance_km = haversine_km(receiver.lat, receiver.lon, raw.lat, raw.lon)
    v.bearing_deg = initial_bearing_deg(receiver.lat, receiver.lon, raw.lat, raw.lon)
    if raw.alt_ft is not None:
        v.elevation_deg = elevation_deg(v.distance_km, receiver.alt_m, raw.alt_ft * _FT_TO_M)
        if horizon is not None and v.elevation_deg > 0 \
                and v.elevation_deg > horizon.obstruction_deg(v.bearing_deg):
            v.visible = True
    return v
