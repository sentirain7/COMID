"""
Molecule-level feature extractor for V3 feature set.

Extracts 16 features from per-category weighted statistics of molecules
in an experiment's composition.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# SARA categories in canonical order
_CATEGORIES = ["saturate", "aromatic", "resin", "asphaltene"]

# 16 molecule-level features (4 categories x 4 statistics)
MOLECULE_FEATURE_NAMES: list[str] = []
for _cat in _CATEGORIES:
    MOLECULE_FEATURE_NAMES.extend(
        [
            f"{_cat}_avg_mw",
            f"{_cat}_avg_atoms",
            f"{_cat}_mw_std",
            f"{_cat}_n_species",
        ]
    )

assert len(MOLECULE_FEATURE_NAMES) == 16  # noqa: S101


class MoleculeFeatureExtractor:
    """Extract molecule-level features from experiment composition.

    For each SARA category, computes:
        - Weighted average molecular weight
        - Weighted average atom count
        - Molecular weight standard deviation (diversity)
        - Number of distinct species
    """

    def extract_from_db(
        self,
        session: Any,
        experiment_id: int,
    ) -> dict[str, float]:
        """Extract molecule features from DB for training.

        Args:
            session: SQLAlchemy session.
            experiment_id: ExperimentModel.id (PK).

        Returns:
            Dict of 16 feature name -> value.
        """
        from database.models import ExperimentMoleculeModel, MoleculeModel

        rows = (
            session.query(
                MoleculeModel.sara_type,
                MoleculeModel.molecular_weight,
                MoleculeModel.num_atoms,
                MoleculeModel.metadata_json,
                ExperimentMoleculeModel.count,
                ExperimentMoleculeModel.weight_fraction,
            )
            .join(
                ExperimentMoleculeModel,
                MoleculeModel.id == ExperimentMoleculeModel.molecule_id,
            )
            .filter(ExperimentMoleculeModel.experiment_id == experiment_id)
            .all()
        )

        # Group by category
        cat_data: dict[str, list[dict[str, Any]]] = {c: [] for c in _CATEGORIES}
        for sara_type, mw, n_atoms, meta, count, wf in rows:
            # Skip autocreated placeholders (no real molecular data)
            if meta and isinstance(meta, dict) and meta.get("autocreated"):
                continue
            cat = self._normalize_sara(sara_type)
            if cat not in cat_data:
                continue
            # Training path: weight_fraction 우선, 없으면 count fallback
            weight = wf if wf is not None else float(count or 1)
            cat_data[cat].append({"mw": mw or 0.0, "atoms": n_atoms or 0, "weight": weight})

        return self._compute_features(cat_data)

    def extract_from_composition(
        self,
        mol_counts: dict[str, int],
        molecule_db: Any,
    ) -> dict[str, float]:
        """Extract molecule features from composition for inference.

        Args:
            mol_counts: {mol_id: count} dict.
            molecule_db: MoleculeDB instance with molecule info.

        Returns:
            Dict of 16 feature name -> value.
        """
        cat_data: dict[str, list[dict[str, Any]]] = {c: [] for c in _CATEGORIES}
        for mol_id, count in mol_counts.items():
            info = molecule_db.get(mol_id) if molecule_db else None
            if info is None:
                continue
            cat = self._normalize_sara(
                getattr(info, "category", None) or getattr(info, "sara_type", None) or ""
            )
            if cat not in cat_data:
                continue
            mw = getattr(info, "molecular_weight", 0.0) or 0.0
            atoms = getattr(info, "atom_count", 0) or getattr(info, "num_atoms", 0) or 0
            # mass-based weight when MW available, count-based fallback
            weight = count * mw if mw > 0 else float(count)
            cat_data[cat].append(
                {
                    "mw": mw,
                    "atoms": atoms,
                    "weight": weight,
                }
            )

        return self._compute_features(cat_data)

    def _compute_features(
        self,
        cat_data: dict[str, list[dict[str, Any]]],
    ) -> dict[str, float]:
        """Compute 16 features from categorized molecule data."""
        features: dict[str, float] = {}
        for cat in _CATEGORIES:
            entries = cat_data.get(cat, [])
            if not entries:
                features[f"{cat}_avg_mw"] = 0.0
                features[f"{cat}_avg_atoms"] = 0.0
                features[f"{cat}_mw_std"] = 0.0
                features[f"{cat}_n_species"] = 0.0
                continue

            raw_weights = np.array([e["weight"] for e in entries], dtype=float)
            mws = np.array([e["mw"] for e in entries], dtype=float)
            atoms = np.array([e["atoms"] for e in entries], dtype=float)

            total_w = raw_weights.sum()
            if total_w > 0:
                weights = raw_weights / total_w
            else:
                weights = np.ones_like(raw_weights) / len(raw_weights)

            features[f"{cat}_avg_mw"] = float(np.dot(weights, mws))
            features[f"{cat}_avg_atoms"] = float(np.dot(weights, atoms))
            features[f"{cat}_mw_std"] = float(
                np.sqrt(np.dot(weights, (mws - np.dot(weights, mws)) ** 2))
            )
            features[f"{cat}_n_species"] = float(len(entries))

        return features

    @staticmethod
    def _normalize_sara(sara_type: str | None) -> str:
        """Normalize SARA type string to canonical form."""
        if not sara_type:
            return ""
        s = sara_type.strip().lower()
        # Map common prefixes
        for cat in _CATEGORIES:
            if s.startswith(cat[:3]):
                return cat
        return s
