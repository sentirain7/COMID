"""Runtime settings tests for environment-driven flags."""

from config import get_settings, reset_settings


def test_tool_executable_paths_from_env(monkeypatch):
    monkeypatch.setenv("TOOLS_PACKMOL_EXE", "/tmp/custom-packmol")
    monkeypatch.setenv("TOOLS_LAMMPS_EXE", "/tmp/custom-lammps")
    reset_settings()
    settings = get_settings()
    assert settings.tools.packmol_exe == "/tmp/custom-packmol"
    assert settings.tools.lammps_exe == "/tmp/custom-lammps"
    reset_settings()
