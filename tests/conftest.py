import pytest
from flighttrack.config import Settings, Receiver


@pytest.fixture
def settings() -> Settings:
    return Settings(source="synthetic", receiver=Receiver(lat=40.0, lon=-105.0, alt_m=1600.0))
