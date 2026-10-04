from __future__ import annotations
import os
import sys
from typing import Literal
import yaml
from pydantic import BaseModel, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Receiver(BaseModel):
    lat: float
    lon: float
    alt_m: float = 0.0


class SyntheticConfig(BaseModel):
    num_aircraft: int = 4
    seed: int = 1


class ReplayConfig(BaseModel):
    path: str
    loop: bool = True


class Dump1090Config(BaseModel):
    url: str = "http://127.0.0.1:8080/data/aircraft.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FLIGHTTRACK_", env_nested_delimiter="__")

    source: Literal["synthetic", "replay", "dump1090"] = "synthetic"
    receiver: Receiver
    synthetic: SyntheticConfig = SyntheticConfig()
    replay: ReplayConfig | None = None
    dump1090: Dump1090Config = Dump1090Config()
    poll_interval_s: float = 1.0
    stale_timeout_s: float = 30.0
    host: str = "127.0.0.1"
    port: int = 8000


def load_settings(config_path: str | None = None) -> Settings:
    path = config_path or os.environ.get("FLIGHTTRACK_CONFIG") or "config.yaml"
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        sys.exit(
            f"Config file not found: {path}\n"
            f"Copy config.example.yaml to config.yaml and set your receiver location."
        )
    try:
        return Settings(**data)
    except ValidationError as e:
        sys.exit(f"Invalid config in {path}:\n{e}")
