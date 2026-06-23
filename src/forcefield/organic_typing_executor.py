"""Dispatcher for organic typing/charge routes (GAFF2 curated artifact).

This module is the single integration point for organic
``TypingStrategy`` values:

* ``ORGANIC_CURATED_ARTIFACT`` → loads a curated artifact via
  :mod:`forcefield.organic_curated_artifact` and applies it to the
  topology. A missing or malformed artifact must fail the
  build/precompute hard.

The executor exists so that ``builder.structure_builder`` and
``features.experiments.submission`` (precompute) can call into one
function and never have to know which sub-path is in use. This mirrors
how :func:`forcefield.inorganic_executor.assign_inorganic_with_cache`
serves the inorganic_profile route.

Result contract:

.. code-block:: python

    @dataclass(frozen=True)
    class OrganicAssignmentResult:
        cache_hit: bool         # True iff the in-memory artifact cache
                                # already had the entry.
        charge_model: str       # honest label, see below
        cache_key: str | None
        artifact: OrganicCuratedArtifact | None  # populated for artifact path
        bonded_overrides: dict | None  # from apply_artifact_to_topology

The ``charge_model`` label is ``{ff_family}_artifact`` (e.g.
``organic_gaff2_artifact``).

The router decides which sub-path applies; this module trusts the
router's decision and refuses to silently switch.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common.logging import get_logger
from forcefield.organic_curated_artifact import (
    ArtifactError,
    ArtifactMissingError,
    OrganicCuratedArtifact,
    apply_artifact_to_topology,
    load_artifact,
)
from forcefield.typing_router import TypingStrategy

logger = get_logger("forcefield.organic_typing_executor")


# ---------------------------------------------------------------------------
# Portable helpers migrated from the deleted typing_charge_assigner module.
# These are re-exported so existing callers can import from here or from the
# backward-compat shim in forcefield.__init__.
# ---------------------------------------------------------------------------

_FF_NAME_ALIASES: dict[str, str] = {
    "reaxff": "reaxff",
    "trappe-ua": "trappe-ua",
    "trappe_ua": "trappe-ua",
    "gaff2": "gaff2",
    "gaff-2": "gaff2",
    "gaff_2": "gaff2",
}


def normalize_ff_name(ff_name: str) -> str:
    """Normalize user-facing force field names to registry keys.

    Standalone replacement for the deleted
    ``TypingChargeAssigner.normalize_ff_name`` class method.
    """
    key = ff_name.strip().lower()
    return _FF_NAME_ALIASES.get(key, key)


@dataclass
class TypingChargeAssignmentError(RuntimeError):
    """Raised when atom typing or charge assignment fails.

    Migrated from the deleted ``forcefield.typing_charge_assigner`` module so
    that callers that catch this exception type keep working.
    """

    message: str
    details: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        super().__init__(self.message)
        if self.details is None:
            self.details = {}


@dataclass(frozen=True)
class OrganicAssignmentResult:
    """Result of an organic typing/charge assignment.

    Mirrors the field set of
    :class:`forcefield.typing_charge_assigner.TypingChargeAssignmentResult`
    so existing call sites can swap one for the other without rewriting
    response construction. The extra ``artifact`` field is populated only
    when the molecule was routed through the curated artifact path.
    """

    cache_hit: bool
    charge_model: str
    cache_key: str | None = None
    artifact: OrganicCuratedArtifact | None = None
    bonded_overrides: dict | None = None


class OrganicAssignmentError(RuntimeError):
    """Raised when an organic route fails to assign types/charges."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


def _assign_via_artifact(
    *,
    topology: Any,
    source_id: str,
    ff_family: str = "organic_gaff2",
) -> OrganicAssignmentResult:
    """Load a curated artifact and apply it to the topology in-place."""
    if not source_id:
        raise OrganicAssignmentError(
            f"Molecule '{getattr(topology, 'mol_id', '?')}' is routed to "
            "organic_curated_artifact but ff_assignment.source_id is missing — "
            "the router should have blocked this earlier; refusing to silently "
            "fall back to the legacy path."
        )

    # Track whether the in-memory cache already had the artifact so we
    # can report cache_hit honestly. We probe the cache by attempting a
    # second load and checking identity, but it's simpler to expose a
    # private "was_cached" via the loader's existing memo. We just call
    # load_artifact twice — the second call is a dict lookup either way.
    from forcefield.organic_curated_artifact import (  # noqa: PLC2701
        _ARTIFACT_CACHE,
    )
    from forcefield.organic_curated_artifact import (  # noqa: PLC2701
        _cache_key as _ck,
    )

    pre_cached = _ck(source_id, ff_family) in _ARTIFACT_CACHE
    try:
        artifact = load_artifact(source_id, ff_family=ff_family)
    except ArtifactMissingError as exc:
        raise OrganicAssignmentError(
            f"Curated artifact missing for source_id={source_id!r} (ff_family={ff_family}): {exc}",
            details={"source_id": source_id, "stage": "artifact_load"},
        ) from exc
    except ArtifactError as exc:
        raise OrganicAssignmentError(
            f"Curated artifact failed schema validation for source_id={source_id!r} (ff_family={ff_family}): {exc}",
            details={"source_id": source_id, "stage": "artifact_parse"},
        ) from exc

    try:
        bonded_overrides = apply_artifact_to_topology(topology, artifact)
    except ArtifactError as exc:
        raise OrganicAssignmentError(
            f"Curated artifact application failed for "
            f"mol_id={getattr(topology, 'mol_id', '?')}: {exc}",
            details={
                "source_id": source_id,
                "mol_id": getattr(topology, "mol_id", "?"),
                "stage": "artifact_apply",
            },
        ) from exc

    charge_model = f"{artifact.ff_family}_artifact"

    return OrganicAssignmentResult(
        cache_hit=pre_cached,
        charge_model=charge_model,
        cache_key=f"{artifact.ff_family}_artifact:{source_id}",
        artifact=artifact,
        bonded_overrides=bonded_overrides if bonded_overrides else None,
    )


def assign_organic(
    *,
    topology: Any,
    mol_file: Path,
    strategy: TypingStrategy,
    source_id: str | None,
    ff_family: str = "organic_gaff2",
    ff_name: str = "gaff2",
    charge_model_primary: str = "am1bcc",
    charge_model_fallback: str = "am1bcc",
    total_charge_tolerance: float = 0.2,
    legacy_assigner: Any | None = None,
) -> OrganicAssignmentResult:
    """Dispatch an organic molecule to the GAFF2 curated artifact sub-path.

    Args:
        topology: live ``MolTopology`` to mutate in place.
        mol_file: path to the source MOL file (kept for API compat).
        strategy: ``TypingStrategy.ORGANIC_CURATED_ARTIFACT``. Any other
            value is a programming error and raises ``ValueError``.
        source_id: ``ff_assignment.source_id``. Required for the artifact
            path.
        ff_family: force field family (default ``"organic_gaff2"``).
        ff_name: force field name (default ``"gaff2"``).
        charge_model_primary: primary charge model (default ``"am1bcc"``).
        charge_model_fallback: fallback charge model (default ``"am1bcc"``).
        total_charge_tolerance: charge neutrality tolerance.
        legacy_assigner: **Deprecated, ignored.** Kept for call-site compat.

    Returns:
        :class:`OrganicAssignmentResult` describing the assignment.

    Raises:
        ValueError: if ``strategy`` is not an organic strategy.
        OrganicAssignmentError: on any sub-path failure.
    """
    if strategy != TypingStrategy.ORGANIC_CURATED_ARTIFACT:
        raise ValueError(
            f"organic_typing_executor refusing to handle non-organic strategy "
            f"{strategy!r}; the router should dispatch inorganic / blocked / ionic "
            "elsewhere."
        )

    result = _assign_via_artifact(topology=topology, source_id=source_id or "", ff_family=ff_family)
    logger.debug(
        "organic_curated_artifact applied: mol_id=%s source_id=%s atoms=%d cache_hit=%s",
        getattr(topology, "mol_id", "?"),
        source_id,
        len(topology.atoms),
        result.cache_hit,
    )
    return result


__all__ = [
    "OrganicAssignmentResult",
    "OrganicAssignmentError",
    "TypingChargeAssignmentError",
    "assign_organic",
    "normalize_ff_name",
]
