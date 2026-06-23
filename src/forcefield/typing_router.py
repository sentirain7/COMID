"""Shared SSOT for typing/charge strategy routing.

This module is the single decision authority for which force-field assignment
strategy applies to a given molecule. Both the structure builder (build path)
and the precompute endpoint (precompute path) call into here so the two paths
cannot drift apart.

Routing decisions:
    organic_curated_artifact → GAFF2 curated artifact (sole organic FF route).
                               Used when a molecule has a repo-tracked JSON
                               artifact produced by the admin curation workflow.
    inorganic_profile → CLAYFF charges + INTERFACE FF LJ + Emami silica
                        bonded params (InorganicParameterService). Used
                        for inorganic additives whose ``ff_assignment.route``
                        is ``inorganic_profile`` and status != blocked.
    ionic_profile → Curated ionic force field (Wave 3). The route is
                    present in the enum so that ionic species in
                    single_moles cannot silently misroute through the
                    organic path. Currently always BLOCKed because the
                    ionic profile SSOT has not been curated yet.
    blocked → Build/precompute must reject. Used for any molecule whose
              ``ff_assignment.status`` is ``blocked_placeholder``, or for
              additives whose metadata is missing ``parameterization.mode``
              but declare ``category: inorganic``.

Phase 6: the legacy ``ORGANIC_RDKIT_LEGACY`` / ``ORGANIC_TYPING`` routes
have been removed. Any serialized string value ``"organic_rdkit_legacy"``
or ``"organic_typing"`` is now mapped to ``BLOCKED`` by ``_missing_()``
so that stale data does not silently route to a deleted code path.

References (rationale only — actual params live in the SSOT yaml files):
    - GAFF2:          Wang et al., J. Comput. Chem. 2004, 25, 1157
    - CLAYFF:         Cygan et al., J. Phys. Chem. B 2004, 108, 1255
    - INTERFACE FF:   Heinz et al., Langmuir 2013, 29, 1754
    - Silica surface: Emami et al., Chem. Mater. 2014, 26, 2647
    - JC ion params:  Joung & Cheatham, J. Phys. Chem. B 2008, 112, 9020

The routing logic intentionally does NOT call into any external library or
service — it only inspects metadata. This keeps the router cheap and
dependency-free, so it can be invoked from any code path including
async API handlers and test fixtures.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class TypingStrategy(StrEnum):
    """Decision result from the typing router.

    Phase 6: the legacy ``ORGANIC_RDKIT_LEGACY`` and ``ORGANIC_TYPING``
    members have been removed. Any serialized/stale string referencing
    the old routes is caught by ``_missing_()`` and mapped to ``BLOCKED``.
    """

    ORGANIC_CURATED_ARTIFACT = "organic_curated_artifact"  # GAFF2 curated
    INORGANIC_PROFILE = "inorganic_profile"
    IONIC_PROFILE = "ionic_profile"
    WATER_MODEL = "water_model"  # Explicit water model (TIP3P etc.)
    BLOCKED = "blocked"

    @classmethod
    def _missing_(cls, value: object) -> TypingStrategy | None:
        # Stale legacy route strings are mapped to BLOCKED so deserialized
        # data from older DB rows / caches does not crash but also cannot
        # silently route to a code path that no longer exists.
        _LEGACY_ROUTES = {
            "organic_rdkit_legacy",
            "organic_typing",
            "organic_opls_artifact",
        }
        if isinstance(value, str) and value in _LEGACY_ROUTES:
            return cls.BLOCKED
        return None


class TypingRouterDecision:
    """Routing decision plus contextual metadata.

    Lightweight value object so callers can branch on ``.strategy`` and
    surface ``.blocked_reason`` / ``.source_id`` to logs and API responses
    without re-running the same metadata inspection.
    """

    __slots__ = ("strategy", "blocked_reason", "profile_id", "source_id", "status")

    def __init__(
        self,
        strategy: TypingStrategy,
        blocked_reason: str | None = None,
        profile_id: str | None = None,
        source_id: str | None = None,
        status: str | None = None,
    ) -> None:
        self.strategy = strategy
        self.blocked_reason = blocked_reason
        # profile_id is kept as a first-class field for legacy callers that
        # read it from the inorganic path. source_id carries the same value
        # for the router's broader notion of "which curated artifact/profile
        # backs this assignment" (organic artifact filename, inorganic
        # profile_id, ionic profile_id, etc.).
        self.profile_id = profile_id
        self.source_id = source_id
        self.status = status

    def __repr__(self) -> str:
        return (
            f"TypingRouterDecision(strategy={self.strategy.value!r}, "
            f"blocked_reason={self.blocked_reason!r}, "
            f"profile_id={self.profile_id!r}, "
            f"source_id={self.source_id!r}, "
            f"status={self.status!r})"
        )


_VALID_ROUTES = {
    "organic_curated_artifact",
    "inorganic_profile",
    "ionic_profile",
    "water_model",
    "blocked",
}
# Legacy routes that are recognized but mapped to BLOCKED with an
# informative reason so stale ff_assignment entries surface clearly.
_RETIRED_ROUTES = {"organic_rdkit_legacy", "organic_opls_artifact"}
_VALID_STATUSES = {"active", "draft", "blocked_placeholder"}


def resolve_typing_strategy(
    mol_id: str,
    additive_def: dict[str, Any] | None,
    ff_assignment: dict[str, Any] | None = None,
) -> TypingRouterDecision:
    """Resolve which typing/charge strategy applies to a molecule.

    Decision order (strictly applied):

    1. If ``ff_assignment`` is present, it is authoritative.
        a. ``status == blocked_placeholder`` → BLOCKED (with reason).
        b. ``route == blocked`` → BLOCKED (with reason).
        c. ``route == organic_rdkit_legacy`` → BLOCKED (retired route).
        d. ``route == organic_curated_artifact``
           → ORGANIC_CURATED_ARTIFACT.
        e. ``route == inorganic_profile`` → INORGANIC_PROFILE.
        f. ``route == ionic_profile`` → BLOCKED until Wave 3 activates.
        g. Unknown route → BLOCKED (fail-closed).
    2. If ``ff_assignment`` is absent the router falls back to the
       ``additive_def``-based routing for inorganic detection.
    3. Molecules with neither ``ff_assignment`` nor an additive definition
       are BLOCKED (all molecules must have ff_assignment post-Phase 6).

    Args:
        mol_id: Molecule identifier (used for error messages only).
        additive_def: Raw additive definition from
            :meth:`builder.molecule_db.MoleculeDB.get_additive_definition`.
            ``None`` for SARA / single_moles molecules that are not present
            in ``additives.yaml``.
        ff_assignment: Canonical ff_assignment SSOT record from
            :meth:`builder.molecule_db.MoleculeDB.get_ff_assignment`.
            Expected shape:
            ``{route, status, source_id, formal_charge, canonical_smiles}``.

    Returns:
        :class:`TypingRouterDecision` describing the routing outcome.
    """
    # --- Branch 1: ff_assignment SSOT takes precedence ------------------------
    if ff_assignment is not None:
        route = str(ff_assignment.get("route") or "").strip()
        status = str(ff_assignment.get("status") or "").strip()
        source_id = ff_assignment.get("source_id")
        source_id_str = str(source_id) if source_id else None
        profile_id_raw = ff_assignment.get("profile_id")
        profile_id_str = str(profile_id_raw) if profile_id_raw else None

        if route and route not in _VALID_ROUTES and route not in _RETIRED_ROUTES:
            return TypingRouterDecision(
                strategy=TypingStrategy.BLOCKED,
                blocked_reason=(f"Molecule '{mol_id}' has unknown ff_assignment.route={route!r}"),
                status=status or None,
            )

        # Phase 6: retired routes are blocked with an informative message.
        if route in _RETIRED_ROUTES:
            return TypingRouterDecision(
                strategy=TypingStrategy.BLOCKED,
                blocked_reason=(
                    f"Molecule '{mol_id}' uses retired route '{route}'. "
                    "This route has been retired. Please update the "
                    "ff_assignment to use 'organic_curated_artifact' "
                    "with a curated GAFF2 source_id."
                ),
                source_id=source_id_str,
                status=status or None,
            )

        if status == "blocked_placeholder":
            # Organic routes: no longer blocked_placeholder — artifact
            # existence is checked at orchestration time by
            # ensure_organic_artifact(), not here. If an organic entry
            # still has blocked_placeholder it is treated as an authoring
            # error (fall through to the route-specific branches below).
            #
            # Inorganic / ionic routes remain fail-closed until their
            # curation tracks reach active status.
            if route == "ionic_profile":
                reason = (
                    f"Ionic species '{mol_id}' is not yet supported. The ionic "
                    "force-field profile is curated under Wave 3 of the FF SSOT "
                    "rollout; until then, this molecule must be excluded from "
                    "submissions. Please use an organic surrogate or wait for "
                    "the Wave 3 release."
                )
                return TypingRouterDecision(
                    strategy=TypingStrategy.BLOCKED,
                    blocked_reason=reason,
                    profile_id=profile_id_str or source_id_str,
                    source_id=source_id_str,
                    status=status,
                )
            elif route == "inorganic_profile":
                reason = (
                    f"Inorganic additive '{mol_id}' uses a profile "
                    f"({source_id_str or 'unknown'}) that is still being curated "
                    "(blocked_placeholder). The build path will reject this "
                    "molecule until the profile reaches active status."
                )
                return TypingRouterDecision(
                    strategy=TypingStrategy.BLOCKED,
                    blocked_reason=reason,
                    profile_id=source_id_str,
                    source_id=source_id_str,
                    status=status,
                )
            elif route != "organic_curated_artifact":
                reason = (
                    f"Molecule '{mol_id}' is blocked_placeholder "
                    f"(route={route or 'unknown'}, not ready for production)."
                )
                return TypingRouterDecision(
                    strategy=TypingStrategy.BLOCKED,
                    blocked_reason=reason,
                    profile_id=source_id_str,
                    source_id=source_id_str,
                    status=status,
                )
            # else: organic routes fall through to the route-specific
            # branches below (artifact existence checked at orchestration time)

        if route == "blocked":
            return TypingRouterDecision(
                strategy=TypingStrategy.BLOCKED,
                blocked_reason=(f"Molecule '{mol_id}' is explicitly blocked in ff_assignment."),
                status=status or None,
            )

        if route == "organic_curated_artifact":
            # GAFF2 curated artifact route (sole organic FF path).
            #
            # Phase 2 (v00.99.41) — Passthrough additives (e.g. CNT, Graphene,
            # which share source_id ``carbon_sp2_passthrough_v1``) carry
            # ``parameterization.mode == "organic_gaff2_passthrough"`` at the
            # entry top-level. There is no AM1-BCC executor for these
            # entries today and shared source_id means batch/delete cannot
            # be safe per consumer. Block them at the typing layer so
            # preview / build / submit all surface a consistent reason
            # (catalog, runtime, and admin all read this decision).
            param_mode = ""
            if additive_def is not None:
                _entry_param = additive_def.get("parameterization") or {}
                if isinstance(_entry_param, dict):
                    param_mode = str(_entry_param.get("mode") or "")
            if param_mode == "organic_gaff2_passthrough":
                return TypingRouterDecision(
                    strategy=TypingStrategy.BLOCKED,
                    blocked_reason=(
                        f"Molecule '{mol_id}' uses parameterization.mode="
                        "organic_gaff2_passthrough; AM1-BCC artifact "
                        "generation is not supported and the source_id is "
                        "shared across consumers. Use the admin FF "
                        "Parameters page (capability-gated) to inspect or "
                        "remediate manually."
                    ),
                    source_id=source_id_str,
                    status=status or None,
                )

            # source_id must be present — missing means an authoring error.
            # Artifact existence is NOT checked here; the orchestration
            # layer (ensure_organic_artifact) validates artifact presence.
            if not source_id_str:
                return TypingRouterDecision(
                    strategy=TypingStrategy.BLOCKED,
                    blocked_reason=(
                        f"Molecule '{mol_id}' route={route} but "
                        "ff_assignment.source_id is missing (authoring error). "
                        "Set source_id to the molecule's base_id or '_variant_' "
                        "for binder aging variants."
                    ),
                    status=status or None,
                )
            return TypingRouterDecision(
                strategy=TypingStrategy.ORGANIC_CURATED_ARTIFACT,
                source_id=source_id_str,
                status=status or "active",
            )

        if route == "inorganic_profile":
            # ff_assignment.source_id holds the profile_id; if an additive_def
            # is also present, fall back to its parameterization.profile_id.
            profile_id = source_id_str
            if profile_id is None and additive_def is not None:
                param = additive_def.get("parameterization") or {}
                candidate = param.get("profile_id")
                profile_id = str(candidate) if candidate else None
            if profile_id is None:
                return TypingRouterDecision(
                    strategy=TypingStrategy.BLOCKED,
                    blocked_reason=(
                        f"Molecule '{mol_id}' route=inorganic_profile but "
                        "ff_assignment.source_id is missing."
                    ),
                    status=status or None,
                )
            return TypingRouterDecision(
                strategy=TypingStrategy.INORGANIC_PROFILE,
                profile_id=profile_id,
                source_id=profile_id,
                status=status or "active",
            )

        if route == "water_model":
            return TypingRouterDecision(
                strategy=TypingStrategy.WATER_MODEL,
                source_id=source_id_str or mol_id,
                status=status or "active",
            )

        if route == "ionic_profile":
            # Check if an ionic artifact exists on disk and YAML status is
            # active. If so, allow through as IONIC_PROFILE. Otherwise
            # remain BLOCKED (fail-closed).
            from pathlib import Path

            ionic_art_dir = (
                Path(__file__).resolve().parents[1].parent
                / "data"
                / "forcefield_artifacts"
                / "ionic_jc_tip3p"
            )
            ionic_art = ionic_art_dir / f"{mol_id}.json"

            if ionic_art.exists() and status == "active":
                return TypingRouterDecision(
                    strategy=TypingStrategy.IONIC_PROFILE,
                    source_id=source_id_str or mol_id,
                    profile_id=profile_id_str or source_id_str or mol_id,
                    status=status,
                )
            else:
                return TypingRouterDecision(
                    strategy=TypingStrategy.BLOCKED,
                    blocked_reason=(
                        f"Ionic species '{mol_id}' artifact not yet generated. "
                        "Generate via Single Molecule -> GAFF2 Artifacts panel."
                    ),
                    source_id=source_id_str,
                    status=status or None,
                )

        # ff_assignment is present but route is empty (or missing).
        # Fail-closed because a partial SSOT entry is exactly the kind
        # of silent-default the migration is meant to eliminate.
        return TypingRouterDecision(
            strategy=TypingStrategy.BLOCKED,
            blocked_reason=(
                f"Molecule '{mol_id}' has an ff_assignment block but route is "
                "empty. SSOT entries must declare an explicit route."
            ),
            source_id=source_id_str,
            status=status or None,
        )

    # --- Branch 2: legacy additive_def-based routing --------------------------
    if additive_def is None:
        # Non-additive, no ff_assignment. Post-Phase 6 all molecules must
        # have ff_assignment. BLOCKED so stale fixtures surface clearly.
        return TypingRouterDecision(
            strategy=TypingStrategy.BLOCKED,
            blocked_reason=(
                f"Molecule '{mol_id}' has no ff_assignment. All molecules must "
                "declare an ff_assignment block with an explicit route after "
                "Phase 6 (GAFF2 transition)."
            ),
        )

    param = additive_def.get("parameterization") or {}
    mode = param.get("mode")
    status = param.get("status")
    profile_id = param.get("profile_id")
    profile_id_str = str(profile_id) if profile_id else None
    category = additive_def.get("category", "organic")

    if status == "blocked_placeholder":
        return TypingRouterDecision(
            strategy=TypingStrategy.BLOCKED,
            blocked_reason=(
                f"Additive '{mol_id}' is blocked_placeholder (parameterization not ready)."
            ),
            profile_id=profile_id_str,
            source_id=profile_id_str,
            status=status,
        )

    if mode == "inorganic_profile":
        return TypingRouterDecision(
            strategy=TypingStrategy.INORGANIC_PROFILE,
            profile_id=profile_id_str,
            source_id=profile_id_str,
            status=status or "active",
        )

    if category == "inorganic" and mode is None:
        return TypingRouterDecision(
            strategy=TypingStrategy.BLOCKED,
            blocked_reason=(
                f"Inorganic additive '{mol_id}' is missing parameterization.mode in additives.yaml."
            ),
        )

    # Organic additive with legacy additive_def but no ff_assignment.
    # Block so that the molecule gets a proper ff_assignment entry.
    return TypingRouterDecision(
        strategy=TypingStrategy.BLOCKED,
        blocked_reason=(
            f"Organic additive '{mol_id}' has no ff_assignment. "
            "Please add an ff_assignment block with route='organic_curated_artifact' "
            "and the appropriate source_id."
        ),
        status=status or None,
    )
