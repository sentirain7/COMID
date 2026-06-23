"""Dashboard build-phase progress policy (SSOT).

Percent weights used by the dashboard to render a monotonic numeric
progress indicator during the build stage of a pipeline. Values are a UX
heuristic, not a physical wall-time ratio.
"""

from dataclasses import dataclass, field


def _default_phase_weights() -> dict[str, float]:
    return {
        "composition_validation": 2.0,
        "structure_build": 5.0,
        "building_structure": 5.0,
        "packing_molecules": 20.0,
        "loading_molecule_topologies": 30.0,
        "loading_topologies": 30.0,
        "assigning_types_charges": 35.0,
        "generating_ff_params": 35.0,
        "protocol_generation": 95.0,
        "build_complete": 100.0,
    }


@dataclass(frozen=True)
class BuildProgressPolicy:
    """Percent mapping for the build stage of a pipeline run.

    Attributes:
        phase_weights: Monotonic percent value per emitted status / stored
            phase name. Keys include both raw builder status strings and
            the ``phase`` names stored in ``metadata_json.build_phase``.
        artifact_order: Ordered artifact sub-step status strings emitted by
            ``forcefield.artifact_service`` during per-molecule FF generation.
        artifact_range: ``(start_percent, end_percent)`` inclusive bounds
            allocated to artifact sub-steps.
        default_mol_count: Fallback ``N`` for ``[i/N mol_id]`` label when
            prefix parsing fails.
    """

    phase_weights: dict[str, float] = field(default_factory=_default_phase_weights)
    artifact_order: tuple[str, ...] = (
        "artifact_antechamber",
        "artifact_parmchk2",
        "artifact_tleap",
        "artifact_parmed",
    )
    artifact_range: tuple[float, float] = (40.0, 85.0)
    default_mol_count: int = 1


DEFAULT_BUILD_PROGRESS_POLICY = BuildProgressPolicy()
