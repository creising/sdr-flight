from __future__ import annotations
import json
import logging

log = logging.getLogger(__name__)


class Horizon:
    """Terrain skyline: the max blocking elevation angle (deg) per azimuth,
    sampled every ``az_step_deg`` degrees starting at due north (0°)."""

    def __init__(self, az_step_deg: float, horizon_deg: list[float]):
        self._step = az_step_deg
        self._h = horizon_deg
        self._n = len(horizon_deg)

    @classmethod
    def load(cls, path: str | None) -> "Horizon | None":
        if not path:
            return None
        try:
            with open(path) as f:
                data = json.load(f)
            h = data["horizon_deg"]
            step = float(data["az_step_deg"])
            if not isinstance(h, list) or len(h) == 0 or step <= 0:
                raise ValueError("empty or invalid horizon profile")
            return cls(step, [float(x) for x in h])
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            log.warning("Horizon profile not loaded from %s: %s", path, e)
            return None

    def obstruction_deg(self, bearing_deg: float) -> float:
        """Linearly-interpolated skyline angle for a compass bearing, wrapping
        across the 0°/360° seam."""
        az = (bearing_deg % 360.0) / self._step
        i = int(az) % self._n
        j = (i + 1) % self._n
        frac = az - int(az)
        return self._h[i] + (self._h[j] - self._h[i]) * frac
