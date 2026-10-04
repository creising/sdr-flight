from __future__ import annotations
from typing import Protocol
from flighttrack.models import RawAircraft


class AircraftSource(Protocol):
    async def poll(self) -> list[RawAircraft]: ...
