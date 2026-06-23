"""Force-field atom-type descriptors — interpretable ML feature channel.

Benchmarked against the TU Delft / Scymol line of work (Assaf, Liu, Erkens),
which trains ML models on **force-field atom types** as descriptors. The key
theoretical property: the non-bonded parameters (epsilon, sigma, charge) that
drive the MD are assigned *per GAFF2 atom type*, so an atom-type histogram is a
summary of the exact non-bonded character the simulation used — a descriptor
with zero representation mismatch against the labels it predicts.

This module derives, from the curated GAFF2 typing artifacts we already
produce (``forcefield.organic_curated_artifact``), a small **chemically
interpretable** histogram by bucketing the ~70 GAFF2 atom types into chemical
groups (aromatic carbon, carbonyl oxygen, sulfur, ...). Oxidative aging is
captured for free in dedicated buckets: aged molecules carry carbonyl (``o`` →
``carbonyl_o``) and oxidized-sulfur (``s4``/``s6``/``sy`` → ``oxidized_sulfur``)
types, kept separate from reduced sulfur so the aging signal is learnable.

Scope: this is an interpretable / low-cost **baseline channel** (good for
near-additive thermodynamic properties like density, thermal expansion, and as
a SHAP-friendly diagnostic). It is intentionally decoupled from the trained
V1-V6 predict vectors so it never causes a dimension mismatch in serving;
consumers opt in explicitly.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache

from common.logging import get_logger

logger = get_logger("ml.ff_atom_type_features")

# ── GAFF2 atom type → chemical group buckets ──────────────────────────────
# Explicit sets for carbon/hydrogen/oxygen (prefix overlaps make prefix rules
# unsafe for these); nitrogen and sulfur are matched by element prefix.
#
# Carbon: ``ca/cp/cq`` pure aromatic, ``cc/cd`` aromatic/conjugated ring sp2.
# ``ce/cf`` (non-ring conjugated sp2) and ``cz`` (sp2 guanidinium) are grouped
# with aromatic as "sp2-conjugated carbon". ``cg/ch`` are *sp* (alkyne) carbons
# — NOT aromatic — and fall through to "other" (P1-8 fix: previously mislabelled
# aromatic).
_AROMATIC_C = {"ca", "cp", "cq", "cc", "cd", "ce", "cf", "cz"}
_ALIPHATIC_C = {"c3", "c5", "c6", "cx", "cy", "cu", "cv", "c1", "c2"}
_CARBONYL_C = {"c"}
_AROMATIC_H = {"ha", "h4", "h5"}
_ALIPHATIC_H = {"hc", "h1", "h2", "h3"}
_POLAR_H = {"ho", "hn", "hs", "hp", "hw"}
_HYDROXYL_O = {"oh"}
_ETHER_ESTER_O = {"os"}
_CARBONYL_O = {"o"}
# Oxidative-aging sulfur products: sulfoxide (s4), sulfone/sulfonic (s6),
# conjugated sulfone (sy). Reduced sulfur (s/s2/sh/ss/sx — thiol, thioether,
# thiophene) stays in "sulfur" (P1-8: makes the aging signal separable).
_OXIDIZED_S = {"s4", "s6", "sy"}

# Stable, ordered feature vocabulary. Each entry becomes a fraction feature
# ``ff_atomtype_frac_<group>`` summing to 1.0 across a non-empty system.
FF_ATOM_TYPE_GROUPS: tuple[str, ...] = (
    "aromatic_carbon",
    "aliphatic_carbon",
    "carbonyl_carbon",
    "aromatic_h",
    "aliphatic_h",
    "polar_h",
    "hydroxyl_o",
    "ether_ester_o",
    "carbonyl_o",
    "nitrogen",
    "sulfur",
    "oxidized_sulfur",
    "other",
)

FF_ATOM_TYPE_FEATURE_NAMES: tuple[str, ...] = tuple(
    f"ff_atomtype_frac_{g}" for g in FF_ATOM_TYPE_GROUPS
)


def classify_ff_atom_type(ff_type: str) -> str:
    """Map a single GAFF2 atom type to its chemical-group bucket."""
    t = (ff_type or "").strip().lower()
    if t in _AROMATIC_C:
        return "aromatic_carbon"
    if t in _ALIPHATIC_C:
        return "aliphatic_carbon"
    if t in _CARBONYL_C:
        return "carbonyl_carbon"
    if t in _AROMATIC_H:
        return "aromatic_h"
    if t in _ALIPHATIC_H:
        return "aliphatic_h"
    if t in _POLAR_H:
        return "polar_h"
    if t in _HYDROXYL_O:
        return "hydroxyl_o"
    if t in _ETHER_ESTER_O:
        return "ether_ester_o"
    if t in _CARBONYL_O:
        return "carbonyl_o"
    if t in _OXIDIZED_S:
        return "oxidized_sulfur"
    if t.startswith("n"):
        return "nitrogen"
    if t.startswith("s"):
        return "sulfur"
    return "other"


def molecule_ff_atom_type_counts(mol_id: str) -> dict[str, int]:
    """Raw GAFF2 atom-type counts for one molecule (full granularity).

    Returns an empty dict if the curated artifact is missing/unreadable, so
    callers degrade gracefully rather than failing the whole feature build.
    """
    from forcefield.organic_curated_artifact import ArtifactError, load_artifact

    try:
        artifact = load_artifact(mol_id)
    except ArtifactError as exc:
        logger.debug("No GAFF2 artifact for %s: %s", mol_id, exc)
        return {}

    counts: dict[str, int] = {}
    for atom in artifact.atoms:
        counts[atom.ff_type] = counts.get(atom.ff_type, 0) + 1
    return counts


@lru_cache(maxsize=2048)
def molecule_ff_atom_group_counts(mol_id: str) -> dict[str, int]:
    """Chemical-group bucketed atom counts for one molecule.

    Cached: the per-molecule typing artifact is immutable, so a mixture-level
    histogram over many compositions (e.g. a BO loop) reuses the bucketed
    counts instead of re-reading the artifact from disk each time. Callers must
    not mutate the returned dict (it is shared across cache hits).
    """
    group_counts: dict[str, int] = dict.fromkeys(FF_ATOM_TYPE_GROUPS, 0)
    for ff_type, n in molecule_ff_atom_type_counts(mol_id).items():
        group_counts[classify_ff_atom_type(ff_type)] += n
    return group_counts


def build_ff_atom_type_histogram(mol_counts: Mapping[str, float]) -> dict[str, float]:
    """Composition-weighted, normalized FF-atom-type histogram for a mixture.

    Args:
        mol_counts: Mapping of ``mol_id -> molecule count`` in the mixture.
            Counts may be integer molecule counts or fractional weights.

    Returns:
        Dict keyed by :data:`FF_ATOM_TYPE_FEATURE_NAMES`, each value the fraction
        of atoms in the mixture belonging to that chemical group (summing to 1.0
        when at least one artifact is resolved; all zeros otherwise).
    """
    totals: dict[str, float] = dict.fromkeys(FF_ATOM_TYPE_GROUPS, 0.0)

    for mol_id, count in mol_counts.items():
        weight = float(count)
        if weight <= 0.0:
            continue
        group_counts = molecule_ff_atom_group_counts(mol_id)
        for group, n in group_counts.items():
            totals[group] += weight * n

    total_atoms = sum(totals.values())
    if total_atoms <= 0.0:
        return dict.fromkeys(FF_ATOM_TYPE_FEATURE_NAMES, 0.0)

    return {
        f"ff_atomtype_frac_{group}": totals[group] / total_atoms
        for group in FF_ATOM_TYPE_GROUPS
    }
