"""Scan database feature package.

Keep package import lightweight for worker/tests that only need detector/service
helpers. The FastAPI router is imported explicitly by API bootstrap.
"""
