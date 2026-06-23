"""Backward-compatible import shim for submission-time E_intra method resolution.

The canonical implementation lives in ``config.dashboard_settings`` because the
submission default is sourced from ``settings.json``.  Keep this module as a
thin alias so older call sites do not fork the precedence logic again.
"""

from config.dashboard_settings import resolve_submission_e_intra_method

__all__ = ["resolve_submission_e_intra_method"]
