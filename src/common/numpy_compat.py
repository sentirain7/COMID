"""NumPy compatibility helpers."""

from __future__ import annotations


def _resolve_rank_warning_type() -> type[Warning]:
    """Resolve RankWarning type across NumPy versions."""
    try:
        from numpy import RankWarning as _RankWarning  # type: ignore[attr-defined]

        return _RankWarning
    except Exception:
        pass

    try:
        from numpy.exceptions import RankWarning as _RankWarning  # type: ignore[attr-defined]

        return _RankWarning
    except Exception:
        pass

    try:
        from numpy.polynomial.polyutils import (
            RankWarning as _RankWarning,  # type: ignore[attr-defined]
        )

        return _RankWarning
    except Exception:
        pass

    class _FallbackRankWarning(Warning):
        """Fallback warning type when NumPy RankWarning is unavailable."""

    return _FallbackRankWarning


RankWarning = _resolve_rank_warning_type()

__all__ = ["RankWarning"]
