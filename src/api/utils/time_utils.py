"""Time formatting helpers for API responses."""

from datetime import UTC, datetime


def to_utc_iso(dt: datetime | None) -> str | None:
    """Return ISO-8601 string with explicit UTC offset."""
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return dt.isoformat()


def iso_or_none(dt: datetime | None) -> str | None:
    """Return bare isoformat() string, preserving naive datetimes as-is.

    Unlike ``to_utc_iso``, this does **not** inject or convert timezone info.
    It matches the legacy ``_iso()`` helpers that existed in individual services.
    """
    return dt.isoformat() if dt is not None else None
