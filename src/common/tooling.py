"""Shared external-tool executable resolution helpers."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from common.pathing import get_project_root


def resolve_executable(
    *,
    env_var: str,
    project_relative_path: str,
    command_candidates: tuple[str, ...] = (),
) -> str | None:
    """Resolve an executable using env override, project bin, then PATH candidates."""
    env_value = os.environ.get(env_var)
    if env_value:
        env_path = Path(env_value)
        if env_path.exists():
            return str(env_path)
        resolved = shutil.which(env_value)
        if resolved:
            return resolved

    project_candidate = get_project_root() / project_relative_path
    if project_candidate.exists():
        return str(project_candidate)

    for command in command_candidates:
        resolved = shutil.which(command)
        if resolved:
            return resolved

    return None


def resolve_lammps_executable() -> str | None:
    """Resolve LAMMPS executable path."""
    return resolve_executable(
        env_var="LAMMPS_EXE",
        project_relative_path="bin/lmp",
        command_candidates=("lmp", "lmp_serial", "lmp_mpi", "lammps"),
    )


def resolve_packmol_executable() -> str | None:
    """Resolve Packmol executable path."""
    return resolve_executable(
        env_var="PACKMOL_EXE",
        project_relative_path="bin/packmol",
        command_candidates=("packmol",),
    )
