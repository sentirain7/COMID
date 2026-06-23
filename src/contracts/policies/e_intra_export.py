"""SSOT policy for write-through export of E_intra to git-tracked sidecars.

The DB ``e_intra`` table is a *runtime cache*; the per-molecule JSON sidecars
under ``data/forcefield_artifacts/e_intra/`` are the *git-tracked, shareable
source of truth*.  Computation write-through keeps each molecule's sidecar in
sync with the DB automatically (no manual export step), so that a ``git push``
carries the per-temperature E_intra alongside the force-field artifacts.  A
separate explicit import step applies the sidecars into another machine's DB
(the frontend coverage matrix reads the DB, so import is what lights it up).

Mirrors the file-as-source / DB-as-cache pattern already used for the
molecule library (``molecule_library.yaml`` → DB) and FF artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EIntraExportPolicy:
    """Configuration for E_intra sidecar write-through and sharing.

    Attributes:
        enabled: When ``True`` (default), every E_intra stored via the SSOT
            helper is also upserted into its per-molecule sidecar
            (write-through), so no manual export is needed.  When ``False``,
            only the DB is written — byte-identical to the pre-feature
            behaviour; used for ephemeral workspaces that must not touch
            git-tracked files.
        sidecar_subdir: Project-root-relative directory holding the sidecars.
            Co-located under ``data/forcefield_artifacts/`` so FF parameters
            and their derived E_intra commit and pull together.
        filename_suffix: Sidecar filename suffix appended to the molecule id.
        schema_version: Sidecar JSON schema version (forward-migration guard).
    """

    enabled: bool = True
    sidecar_subdir: str = "data/forcefield_artifacts/e_intra"
    filename_suffix: str = ".json"
    schema_version: int = 1


DEFAULT_E_INTRA_EXPORT_POLICY = EIntraExportPolicy()
"""Module-level singleton — import this rather than constructing the dataclass."""
