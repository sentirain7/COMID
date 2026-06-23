"""Cradle-to-gate GHG emission factor policy and calculation."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

# Pattern for aging-wrapped IDs: U-SBS-0293, S-CRM-0313, etc.
_AGING_WRAP_RE = re.compile(r"^[USL]-([A-Za-z0-9_]+)-\d{4}$")


class GHGPolicy(BaseModel):
    """Cradle-to-gate GHG emission factors and calculation logic.

    YAML loading is NOT done here — pure schema + calculation only.
    Use ``common.library_config.load_ghg_inventory()`` to populate.
    """

    binder_molecules: dict[str, float] = Field(default_factory=dict)
    sara_fallback: dict[str, float] = Field(default_factory=dict)
    additives: dict[str, float] = Field(default_factory=dict)
    default_binder_ef: float = 0.50
    default_additive_ef: float = 0.0
    version: str = "1.0"

    def _resolve_additive(self, mol_id: str) -> float | None:
        """Try to resolve *mol_id* as an additive. Returns EF or None."""
        from common.additive_ids import canonicalize_additive_mol_id

        canonical = canonicalize_additive_mol_id(mol_id)
        if canonical and canonical in self.additives:
            return self.additives[canonical]
        if mol_id in self.additives:
            return self.additives[mol_id]
        return None

    def get_factor(self, mol_id: str) -> float:
        """Look up emission factor for *mol_id*, applying normalisation.

        Resolution order:
        1. Canonical additive match (raw mol_id)
        2. Direct additive key match
        3. Aging-unwrapped additive match (U-SBS-0293 → SBS)
        4. Binder base_id match (via parse_molecule_id)
        5. SARA fallback
        6. Default binder EF
        """
        # 1-2. Direct additive resolution
        ef = self._resolve_additive(mol_id)
        if ef is not None:
            return ef

        # 3. Strip aging wrapper and retry additive resolution.
        #    composition_builder stores additives as U-{mol_id}-{temp_code}
        #    (e.g. U-SBS-0293), which is NOT a valid SARA molecule ID.
        m = _AGING_WRAP_RE.match(mol_id)
        if m:
            inner = m.group(1)
            ef = self._resolve_additive(inner)
            if ef is not None:
                return ef

        # 4-5. Binder molecule / SARA fallback
        try:
            from common.molecule_id import parse_molecule_id

            parsed = parse_molecule_id(mol_id)
            base_id = parsed.base_id
            if base_id in self.binder_molecules:
                return self.binder_molecules[base_id]
            return self.sara_fallback.get(parsed.sara_category, self.default_binder_ef)
        except ValueError:
            pass

        # 6. Final fallback
        return self.default_binder_ef

    def calculate_ghg_from_weight_fractions(
        self,
        mol_fractions: list[tuple[str, float]],
    ) -> float:
        """GHG from per-molecule weight fractions (primary path).

        Args:
            mol_fractions: ``[(mol_id, weight_fraction), ...]``
                where *weight_fraction* is a 0-1 fraction.
        """
        return sum(wf * self.get_factor(mid) for mid, wf in mol_fractions)

    def calculate_ghg_from_sara(
        self,
        comp_saturate_wt: float,
        comp_aromatic_wt: float,
        comp_resin_wt: float,
        comp_asphaltene_wt: float,
        additive_mol_id: str | None,
        additive_wt: float,
    ) -> float:
        """GHG from SARA wt% + single additive (fallback path).

        All ``comp_*_wt`` and ``additive_wt`` are in **wt% (0-100)**.
        """
        add_frac = max(0.0, min(1.0, additive_wt / 100.0))
        binder_frac = 1.0 - add_frac

        sara_total = comp_saturate_wt + comp_aromatic_wt + comp_resin_wt + comp_asphaltene_wt
        if sara_total <= 0:
            return 0.0

        binder_ghg = binder_frac * sum(
            (w / sara_total) * self.sara_fallback.get(cat, self.default_binder_ef)
            for cat, w in [
                ("saturate", comp_saturate_wt),
                ("aromatic", comp_aromatic_wt),
                ("resin", comp_resin_wt),
                ("asphaltene", comp_asphaltene_wt),
            ]
        )

        add_ef = 0.0
        if additive_mol_id:
            from common.additive_ids import canonicalize_additive_mol_id

            canonical = canonicalize_additive_mol_id(additive_mol_id)
            add_ef = self.additives.get(canonical or additive_mol_id, self.default_additive_ef)
        additive_ghg = add_frac * add_ef

        return binder_ghg + additive_ghg
