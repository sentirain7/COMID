"""SSOT policy for organic FF artifact generation routing + efficiency layer.

Failure-history skip (logic ②): AM1 SCF (non-)convergence is *deterministic*
for a fixed molecular structure — the same molecule fails (or converges) the
same way every time.  So once a molecule has been observed to exhaust
antechamber's AM1 SCF (baseline + sqm_robust) or to be resolved via
fragment_fallback, re-running the doomed antechamber attempts is pure waste.
This policy lets the generation chain route such molecules straight to
fragment_fallback.  The *outcome* (a fragment_fallback_gaff2 artifact) is
unchanged — only faster — so there is no quality trade-off.

Efficiency layer (v01.06.20) — bound the first-encounter cost of a genuinely
non-convergent molecule (baseline 600s + sqm_robust, then fragment):

  1. **Timeout externalisation** — ``baseline_timeout_s`` / ``sqm_robust_timeout_s``
     are policy values (sqm_robust cut 7200s -> 1800s). A structure that cannot
     converge grinds to the timeout no matter how long it runs, so a shorter
     robust cap turns a ~2h13m worst case into ~40m without losing any molecule
     that converges within the cap.
  2. **Size pre-screen** — molecules above ``prescreen_max_atoms`` skip straight
     to fragment_fallback on the FIRST encounter (AM1-BCC is impractical /
     unreliable at that scale).  Deliberately **size-only**: ring-density or
     "fused aromatic" heuristics are NOT used because they would mis-route
     convergent systems (e.g. flat graphene converges while curved CNT of the
     same size does not — the discriminator is geometry, not topology).  The
     threshold sits above the largest molecule that converges in this project
     (Polymer_PolyEthylene, 212 atoms), so it never degrades a known-good FF.

Everything below is opt-out via the policy fields; the failure-history skip
(logic ②) remains the zero-false-positive path for repeat encounters.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FFGenerationPolicy:
    """Routing + efficiency policy for the organic FF generation chain.

    Attributes:
        skip_to_fragment_on_prior_scf_failure: When ``True`` (default), a
            molecule whose admin-status history shows a prior fragment_fallback
            resolution OR a terminal AM1-SCF failure at the sqm_robust profile
            is routed directly to fragment_fallback, skipping baseline +
            sqm_robust.  Falls through to the normal chain if the fast attempt
            fails (stale verdict).
        scf_failure_codes: Admin failure codes that mean "AM1 SCF will not
            converge for this structure".
        baseline_timeout_s: antechamber AM1-BCC (baseline profile) wall-clock cap.
        sqm_robust_timeout_s: antechamber AM1-BCC (sqm_robust profile) wall-clock
            cap. Cut from 7200s to 1800s — a non-convergent structure grinds to
            the cap regardless, and molecules that converge do so well inside it.
        prescreen_to_fragment_enabled: When ``True`` (default), route molecules
            larger than ``prescreen_max_atoms`` straight to fragment_fallback on
            first encounter (size-only screen — see module docstring).
        prescreen_max_atoms: Atom-count threshold for the size pre-screen. Set
            above the largest convergent molecule in the project (212) so no
            known-good FF is degraded.
    """

    skip_to_fragment_on_prior_scf_failure: bool = True
    scf_failure_codes: tuple[str, ...] = ("sqm_timeout", "sqm_nonconverged")
    baseline_timeout_s: int = 600
    sqm_robust_timeout_s: int = 1800
    prescreen_to_fragment_enabled: bool = True
    prescreen_max_atoms: int = 300


DEFAULT_FF_GENERATION_POLICY = FFGenerationPolicy()
"""Module-level singleton — import this rather than constructing the dataclass."""
