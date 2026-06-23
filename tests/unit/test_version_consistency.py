"""Version SSOT consistency checks."""

import json
import tomllib
from pathlib import Path

from config import get_settings, reset_settings
from contracts import __version__


def test_contract_version_file_matches_package_version():
    version_file = Path("src/contracts/VERSION")
    assert version_file.exists()
    assert version_file.read_text().strip() == __version__


def test_settings_version_matches_contract_version():
    reset_settings()
    settings = get_settings()
    assert settings.app_version == __version__


def test_api_version_matches_contract_version():
    from api.application import app

    assert app.version == __version__


def test_pyproject_version_matches_contract_version():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    assert pyproject["project"]["version"] == __version__


def test_frontend_package_versions_match_contract_version():
    package_json = json.loads(Path("frontend/package.json").read_text())
    package_lock = json.loads(Path("frontend/package-lock.json").read_text())

    assert package_json["version"] == __version__
    assert package_lock["version"] == __version__
    assert package_lock["packages"][""]["version"] == __version__
