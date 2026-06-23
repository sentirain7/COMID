"""Seed generation helpers."""

from datetime import datetime


def today_seed() -> int:
    """Return today's local date as an integer seed (YYYYMMDD)."""
    return int(datetime.now().strftime("%Y%m%d"))


def generate_seed(provided_seed: int | None = None) -> int:
    """Resolve seed from optional user input."""
    if provided_seed is not None:
        return provided_seed
    return today_seed()
