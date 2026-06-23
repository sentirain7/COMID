"""System feature package.

Keep package import lightweight so service/tests do not pull FastAPI unless the
router is explicitly imported.
"""

__all__: list[str] = []
