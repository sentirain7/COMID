"""External tool settings (Packmol/LAMMPS)."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ToolSettings(BaseSettings):
    """Executable resolution settings for external simulation tools."""

    lammps_exe: str = Field(default=str(_PROJECT_ROOT / "bin" / "lmp"))
    packmol_exe: str = Field(default=str(_PROJECT_ROOT / "bin" / "packmol"))

    class Config:
        env_prefix = "TOOLS_"
