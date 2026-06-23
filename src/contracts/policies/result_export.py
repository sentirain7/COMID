"""SSOT policy for write-through export of experiment RESULTS to git-tracked sidecars.

The large LAMMPS raw outputs (dumps, restarts, ``log.lammps``, ``data.lammps``,
trajectories) live under ``database/`` and are **never** shared (gitignored,
~GB). What IS worth sharing across machines is the *distilled scientific result*
that the dashboard/analysis graphs read: each experiment's composition/conditions
metadata + its scalar metrics (density, CED, Tg, RDF peaks, MSD diffusion, …) +
its array-metric curves (RDF/MSD/stress, the small ``data/arrays`` parquets).

Mirrors the proven E_intra sidecar pattern (``e_intra_export.py``): the DB is a
*runtime cache*; per-experiment JSON sidecars under ``data/result_sidecars/`` are
the *git-tracked, diffable, machine-independent source of truth*. Write-through
keeps each completed experiment's sidecar in sync automatically; a separate
import step applies the sidecars into another machine's DB after ``git pull`` so
the frontend graphs light up — WITHOUT shipping the binary SQLite DB (which is
git-hostile: no diffs, unmergeable, diverges per machine).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResultExportPolicy:
    """Configuration for experiment-result sidecar write-through and sharing.

    Attributes:
        enabled: When ``True`` (default), completing an experiment also writes
            its result sidecar (metadata + scalar metrics + array-curve refs).
            When ``False``, only the DB is written — byte-identical to the
            pre-feature behaviour; for ephemeral workspaces that must not touch
            git-tracked files.
        sidecar_subdir: Project-root-relative directory holding the sidecars
            (one JSON per ``exp_id``).
        array_subdir: Project-root-relative directory holding the shared
            array-metric parquet curves (RDF/MSD/stress). These are tracked in
            git (un-ignored) so curve graphs render after a pull.
        filename_suffix: Sidecar filename suffix appended to ``exp_id``.
        schema_version: Sidecar JSON schema version (forward-migration guard).
    """

    enabled: bool = True
    sidecar_subdir: str = "data/result_sidecars"
    array_subdir: str = "data/arrays"
    filename_suffix: str = ".json"
    schema_version: int = 1


DEFAULT_RESULT_EXPORT_POLICY = ResultExportPolicy()

# Machine-INDEPENDENT, scientific experiment columns to share. Explicit allowlist
# (safer than a denylist): runtime/scheduler/path/timestamp columns (id,
# gpu_id_allocated, celery_task_id, *_file_path, lammps_*, error_*, *_at,
# prepared_artifact_json, metadata_json, …) are intentionally EXCLUDED so the
# sidecar carries no machine state and diffs/merges cleanly across machines.
SHARED_EXPERIMENT_FIELDS: tuple[str, ...] = (
    "exp_id",
    "status",
    "run_tier",
    "ff_type",
    "study_type",
    "material_id",
    "binder_type",
    "structure_size",
    "aging_state",
    "force_field_name",
    "comp_asphaltene_wt",
    "comp_resin_wt",
    "comp_aromatic_wt",
    "comp_saturate_wt",
    "composition_error_l1",
    "additive_type",
    "additive_wt",
    "additive_mol_id",
    "temperature_K",
    "pressure_atm",
    "target_atoms",
    "actual_atoms",
    "seed",
    "box_lx",
    "box_ly",
    "box_lz",
    "topology_hash",
    "protocol_hash",
)
