from __future__ import annotations
import math
import random
import time
from typing import Callable
from flighttrack.config import Receiver, SyntheticConfig
from flighttrack.models import RawAircraft

_AIRLINES = ["UAL", "DAL", "AAL", "SWA", "FFT", "JBU"]


class SyntheticSource:
    """Deterministic fake traffic orbiting the receiver, for hardware-free dev."""

    def __init__(self, receiver: Receiver, config: SyntheticConfig,
                 clock: Callable[[], float] = time.monotonic):
        self.rx = receiver
        self.cfg = config
        self._clock = clock
        rng = random.Random(config.seed)
        self._planes = []
        for i in range(config.num_aircraft):
            self._planes.append({
                "icao": f"{rng.randint(0, 0xFFFFFF):06x}",
                "callsign": f"{rng.choice(_AIRLINES)}{rng.randint(100, 999)}",
                "radius_km": rng.uniform(5.0, 60.0),
                "angular_speed": rng.uniform(0.01, 0.05) * rng.choice([-1, 1]),  # rad/s
                "phase": rng.uniform(0, 2 * math.pi),
                "alt_ft": rng.choice([8000, 12000, 20000, 33000, 38000]),
                "gs": rng.uniform(250, 500),
                "baro_rate": rng.choice([0, 0, 1472, -1984, 2112, -1216]),
                "squawk": f"{rng.randint(1000, 7777):04d}",
                "positionless": i == 0,  # first plane never reports a position
            })

    async def poll(self) -> list[RawAircraft]:
        t = self._clock()
        out: list[RawAircraft] = []
        for p in self._planes:
            if p["positionless"]:
                out.append(RawAircraft(
                    icao=p["icao"], callsign=p["callsign"], lat=None, lon=None,
                    alt_ft=None, ground_speed_kt=None, track_deg=None, seen_s=0.0, rssi=-20.0,
                    raw={"hex": p["icao"], "flight": p["callsign"], "seen": 0.0, "rssi": -20.0,
                         "messages": 12, "mlat": [], "tisb": []}))
                continue
            ang = p["phase"] + p["angular_speed"] * t
            dlat = (p["radius_km"] / 111.0) * math.sin(ang)
            dlon = (p["radius_km"] / (111.0 * math.cos(math.radians(self.rx.lat)))) * math.cos(ang)
            track = (math.degrees(ang) + 90.0) % 360.0
            lat, lon = self.rx.lat + dlat, self.rx.lon + dlon
            raw = {
                "hex": p["icao"], "flight": p["callsign"], "lat": lat, "lon": lon,
                "alt_baro": p["alt_ft"], "alt_geom": p["alt_ft"] + 350,
                "gs": round(p["gs"], 1), "track": round(track, 1), "baro_rate": p["baro_rate"],
                "squawk": p["squawk"], "category": "A3", "nav_altitude_mcp": 24000,
                "nav_modes": ["autopilot", "tcas"], "nav_qnh": 1013.6, "emergency": "none",
                "nic": 8, "nac_p": 10, "sil": 3, "rssi": -15.0, "seen": 0.0, "seen_pos": 0.1,
                "messages": 420, "version": 2, "mlat": [], "tisb": [],
            }
            out.append(RawAircraft(
                icao=p["icao"], callsign=p["callsign"], lat=lat, lon=lon,
                alt_ft=float(p["alt_ft"]), ground_speed_kt=float(p["gs"]),
                track_deg=track, seen_s=0.0, rssi=-15.0,
                baro_rate=p["baro_rate"], squawk=p["squawk"], raw=raw))
        return out
