"""
Artifact management utilities - SSOT for artifact storage.

All sessions must use these functions for artifact handling.
"""

import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class ArtifactType(StrEnum):
    """Types of artifacts."""

    DATA_FILE = "data_file"  # LAMMPS data file
    INPUT_SCRIPT = "input_script"  # LAMMPS input script
    LOG_FILE = "log_file"  # LAMMPS log file
    DUMP_FILE = "dump_file"  # Trajectory dump
    RESTART_FILE = "restart_file"  # Restart/checkpoint
    ARRAY_DATA = "array_data"  # Parquet/npy arrays
    METADATA = "metadata"  # JSON metadata
    TOPOLOGY = "topology"  # Topology files (mol2, etc.)
    PARAMETER = "parameter"  # Force field parameters


# Artifact directory names
ARTIFACT_DIRS = {
    ArtifactType.DATA_FILE: "input",
    ArtifactType.INPUT_SCRIPT: "input",
    ArtifactType.LOG_FILE: "output",
    ArtifactType.DUMP_FILE: "output",
    ArtifactType.RESTART_FILE: "output",
    ArtifactType.ARRAY_DATA: "analysis",
    ArtifactType.METADATA: "metadata",
    ArtifactType.TOPOLOGY: "input",
    ArtifactType.PARAMETER: "input",
}

# Artifact file extensions
ARTIFACT_EXTENSIONS = {
    ArtifactType.DATA_FILE: ".lammps",
    ArtifactType.INPUT_SCRIPT: ".in",
    ArtifactType.LOG_FILE: ".log",
    ArtifactType.DUMP_FILE: ".dump",
    ArtifactType.RESTART_FILE: ".restart",
    ArtifactType.ARRAY_DATA: ".parquet",
    ArtifactType.METADATA: ".json",
    ArtifactType.TOPOLOGY: ".mol2",
    ArtifactType.PARAMETER: ".params",
}


def get_artifact_path(
    exp_dir: str | Path, artifact_type: ArtifactType, name: str, create: bool = False
) -> Path:
    """
    Get path for an artifact.

    Args:
        exp_dir: Experiment directory
        artifact_type: Type of artifact
        name: Artifact name (without extension)
        create: Create directory if not exists

    Returns:
        Full path to artifact
    """
    base_dir = Path(exp_dir) / ARTIFACT_DIRS.get(artifact_type, "")
    extension = ARTIFACT_EXTENSIONS.get(artifact_type, "")

    if create:
        base_dir.mkdir(parents=True, exist_ok=True)

    return base_dir / f"{name}{extension}"


def save_artifact(
    exp_dir: str | Path,
    artifact_type: ArtifactType,
    name: str,
    content: str | bytes | dict,
    metadata: dict | None = None,
) -> Path:
    """
    Save an artifact to experiment directory.

    Args:
        exp_dir: Experiment directory
        artifact_type: Type of artifact
        name: Artifact name
        content: Content to save
        metadata: Optional metadata to save alongside

    Returns:
        Path to saved artifact
    """
    path = get_artifact_path(exp_dir, artifact_type, name, create=True)

    # Save based on content type
    if isinstance(content, dict):
        with open(path, "w") as f:
            json.dump(content, f, indent=2, default=str)
    elif isinstance(content, bytes):
        with open(path, "wb") as f:
            f.write(content)
    else:
        with open(path, "w") as f:
            f.write(content)

    # Save metadata if provided
    if metadata:
        meta_path = path.with_suffix(".meta.json")
        metadata["saved_at"] = datetime.now().isoformat()
        metadata["artifact_type"] = artifact_type.value
        metadata["original_name"] = name
        with open(meta_path, "w") as f:
            json.dump(metadata, f, indent=2, default=str)

    return path


def load_artifact(
    exp_dir: str | Path, artifact_type: ArtifactType, name: str, as_bytes: bool = False
) -> str | bytes | dict:
    """
    Load an artifact from experiment directory.

    Args:
        exp_dir: Experiment directory
        artifact_type: Type of artifact
        name: Artifact name
        as_bytes: Load as bytes instead of string

    Returns:
        Artifact content
    """
    path = get_artifact_path(exp_dir, artifact_type, name)

    if not path.exists():
        raise FileNotFoundError(f"Artifact not found: {path}")

    if artifact_type == ArtifactType.METADATA:
        with open(path) as f:
            result: dict = json.load(f)
            return result
    elif as_bytes:
        with open(path, "rb") as f:
            return f.read()
    else:
        with open(path) as f:
            return f.read()


def list_artifacts(exp_dir: str | Path, artifact_type: ArtifactType | None = None) -> list[dict]:
    """
    List artifacts in experiment directory.

    Args:
        exp_dir: Experiment directory
        artifact_type: Filter by type (optional)

    Returns:
        List of artifact info dicts
    """
    results = []
    exp_path = Path(exp_dir)

    if artifact_type:
        types_to_check = [artifact_type]
    else:
        types_to_check = list(ArtifactType)

    for atype in types_to_check:
        subdir = ARTIFACT_DIRS.get(atype, "")
        extension = ARTIFACT_EXTENSIONS.get(atype, "")

        dir_path = exp_path / subdir
        if not dir_path.exists():
            continue

        pattern = f"*{extension}"
        for file_path in dir_path.glob(pattern):
            if file_path.suffix == ".json" and file_path.stem.endswith(".meta"):
                continue

            info = {
                "name": file_path.stem,
                "type": atype.value,
                "path": str(file_path),
                "size": file_path.stat().st_size,
                "modified": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
            }

            # Load metadata if exists
            meta_path = file_path.with_suffix(".meta.json")
            if meta_path.exists():
                with open(meta_path) as f:
                    info["metadata"] = json.load(f)

            results.append(info)

    return results


def delete_artifact(exp_dir: str | Path, artifact_type: ArtifactType, name: str) -> bool:
    """
    Delete an artifact.

    Args:
        exp_dir: Experiment directory
        artifact_type: Type of artifact
        name: Artifact name

    Returns:
        True if deleted, False if not found
    """
    path = get_artifact_path(exp_dir, artifact_type, name)

    if not path.exists():
        return False

    path.unlink()

    # Delete metadata if exists
    meta_path = path.with_suffix(".meta.json")
    if meta_path.exists():
        meta_path.unlink()

    return True
