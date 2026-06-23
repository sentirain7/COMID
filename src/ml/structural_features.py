"""Structural (node/system) feature extractor for the V7 feature set.

Computes 32 structural features for a molecular system (binder cell):

- 30 node features: 10 RDKit topology descriptors per molecule species,
  aggregated over all molecule *instances* with count-weighted
  mean / sum / std (population statistics, MDML parity).
- 2 system features: total number of molecule instances and temperature.

Descriptor set, aggregation formulas, and feature naming follow the
externally validated MDML pipeline (XGBoost/RF density·CED models) so that
features computed here are numerically comparable with that corpus:

    node_{X}_sum  = sum_s count_s * X_s
    node_{X}_mean = node_{X}_sum / N          (N = sum_s count_s)
    node_{X}_std  = sqrt(sum_s count_s * (X_s - mean)^2 / N)

All 10 descriptors are topology-based (no 3D coordinates needed), so the
only structural input is the per-species ``.mol`` file from the molecule
library — LAMMPS outputs are never required (labels come from metrics).

RDKit is an optional dependency: when unavailable, extraction returns
``None`` and the V7 feature set is simply not produced (V1–V6 unaffected).
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

try:  # pragma: no cover - import guard exercised via RDKIT_AVAILABLE flag
    from rdkit import Chem, RDLogger
    from rdkit.Chem import AllChem, Crippen, Lipinski
    from rdkit.Chem import rdMolDescriptors as _rdmd

    RDLogger.DisableLog("rdApp.*")
    RDKIT_AVAILABLE = True
except ImportError:  # pragma: no cover
    RDKIT_AVAILABLE = False

# ── Feature name SSOT (order fixed — MDML pt_summary CSV parity) ──────────

NODE_DESCRIPTOR_NAMES: list[str] = [
    "MolWt",
    "TPSA",
    "MolLogP",
    "NumHeteroatoms",
    "NumRotatableBonds",
    "FractionCSP3",
    "NumAliphaticCarbocycles",
    "NumAromaticCarbocycles",
    "PartialCharge",
    "HB_Acc_Don",
]

_NODE_STATS: tuple[str, ...] = ("mean", "sum", "std")

SYSTEM_FEATURE_NAMES: list[str] = ["sys_NumFragments", "sys_Temperature"]

STRUCTURAL_FEATURE_NAMES: list[str] = [
    f"node_{name}_{stat}" for name in NODE_DESCRIPTOR_NAMES for stat in _NODE_STATS
] + SYSTEM_FEATURE_NAMES

# Count is structurally derived (10 descriptors × 3 stats + 2 system = 32).
# The SSOT for the count is this list itself; DEFAULT_ML_POLICY.v7_feature_count
# is cross-validated against it in tests (test_v7_feature_wiring).
assert len(STRUCTURAL_FEATURE_NAMES) == (  # noqa: S101
    len(NODE_DESCRIPTOR_NAMES) * len(_NODE_STATS) + len(SYSTEM_FEATURE_NAMES)
)


def _calc_partial_charge(mol: Any) -> float:
    """Sum of Gasteiger partial charges (MDML parity; ~0 for neutral mols)."""
    try:
        work = Chem.Mol(mol)
        AllChem.ComputeGasteigerCharges(work)
        charges = [
            float(atom.GetProp("_GasteigerCharge"))
            for atom in work.GetAtoms()
            if atom.HasProp("_GasteigerCharge")
        ]
        total = float(sum(charges)) if charges else 0.0
        return total if np.isfinite(total) else 0.0
    except Exception:  # noqa: BLE001 - descriptor robustness over precision
        return 0.0


def _calc_hb_acc_don(mol: Any) -> float:
    """Hydrogen-bond acceptor + donor count (MDML parity)."""
    try:
        return float(Lipinski.NumHAcceptors(mol) + Lipinski.NumHDonors(mol))
    except Exception:  # noqa: BLE001
        return 0.0


def _descriptor_funcs() -> dict[str, Any]:
    """RDKit descriptor functions keyed by NODE_DESCRIPTOR_NAMES entries."""
    return {
        "MolWt": _rdmd.CalcExactMolWt,
        "TPSA": _rdmd.CalcTPSA,
        "MolLogP": Crippen.MolLogP,
        "NumHeteroatoms": _rdmd.CalcNumHeteroatoms,
        "NumRotatableBonds": Lipinski.NumRotatableBonds,
        "FractionCSP3": _rdmd.CalcFractionCSP3,
        "NumAliphaticCarbocycles": _rdmd.CalcNumAliphaticCarbocycles,
        "NumAromaticCarbocycles": _rdmd.CalcNumAromaticCarbocycles,
        "PartialCharge": _calc_partial_charge,
        "HB_Acc_Don": _calc_hb_acc_don,
    }


def _mol_from_file(path: Path) -> Any | None:
    """Parse a .mol file, tolerating sanitize failures (kekulize fallback)."""
    mol = Chem.MolFromMolFile(str(path), removeHs=False, sanitize=True)
    if mol is not None:
        return mol
    mol = Chem.MolFromMolFile(str(path), removeHs=False, sanitize=False)
    if mol is None:
        return None
    try:
        Chem.SanitizeMol(
            mol,
            Chem.SanitizeFlags.SANITIZE_ALL ^ Chem.SanitizeFlags.SANITIZE_KEKULIZE,
        )
    except Exception:  # noqa: BLE001
        return None
    return mol


@lru_cache(maxsize=512)
def compute_molecule_descriptors(mol_path: str) -> tuple[float, ...] | None:
    """Compute the 10 node descriptors for one molecule species.

    Cached per resolved path string — each library species is computed once
    per process regardless of how many compositions reference it.

    Args:
        mol_path: Absolute path to the species ``.mol`` file.

    Returns:
        Tuple of 10 descriptor values in NODE_DESCRIPTOR_NAMES order,
        or None when RDKit is unavailable or the file cannot be parsed.
    """
    if not RDKIT_AVAILABLE:
        return None
    path = Path(mol_path)
    if not path.exists():
        logger.warning("structural_features: mol file missing: %s", mol_path)
        return None
    mol = _mol_from_file(path)
    if mol is None:
        logger.warning("structural_features: RDKit failed to parse: %s", mol_path)
        return None
    funcs = _descriptor_funcs()
    values: list[float] = []
    for name in NODE_DESCRIPTOR_NAMES:
        try:
            value = float(funcs[name](mol))
        except Exception:  # noqa: BLE001
            value = 0.0
        values.append(value if np.isfinite(value) else 0.0)
    return tuple(values)


def aggregate_structural_features(
    species_descriptors: dict[str, tuple[tuple[float, ...], int]],
    temperature_k: float,
) -> dict[str, float]:
    """Aggregate per-species descriptors into the 32-feature record.

    Args:
        species_descriptors: {mol_id: (descriptor_tuple_10, count)} with
            count = number of molecule instances of that species.
        temperature_k: System temperature (K).

    Returns:
        Dict of all 32 STRUCTURAL_FEATURE_NAMES → value.

    Raises:
        ValueError: when the instance population is empty.
    """
    counts = np.array([c for (_, c) in species_descriptors.values()], dtype=float)
    if counts.size == 0 or counts.sum() <= 0:
        raise ValueError("structural_features: empty molecule instance population")

    matrix = np.array(
        [list(desc) for (desc, _) in species_descriptors.values()], dtype=float
    )  # (n_species, 10)
    n_instances = float(counts.sum())

    record: dict[str, float] = {}
    for j, name in enumerate(NODE_DESCRIPTOR_NAMES):
        column = matrix[:, j]
        total = float(np.dot(counts, column))
        mean = total / n_instances
        std = float(np.sqrt(np.dot(counts, (column - mean) ** 2) / n_instances))
        record[f"node_{name}_mean"] = mean
        record[f"node_{name}_sum"] = total
        record[f"node_{name}_std"] = std

    record["sys_NumFragments"] = n_instances
    record["sys_Temperature"] = float(temperature_k)
    return record


def zeros() -> dict[str, float]:
    """Zero-valued structural features (V7 unavailable placeholder)."""
    return dict.fromkeys(STRUCTURAL_FEATURE_NAMES, 0.0)


class StructuralFeatureExtractor:
    """Extract 32 structural features from a composition or a DB experiment.

    The extractor resolves each species mol_id to its library ``.mol`` file
    via MoleculeDB (aging library + additives), computes RDKit descriptors
    once per species (process-level cache), and count-weight aggregates.
    """

    def __init__(self, molecule_db: Any | None = None):
        self._molecule_db = molecule_db

    def _get_molecule_db(self) -> Any:
        if self._molecule_db is None:
            from builder.molecule_db import MoleculeDB
            from common.library_config import get_asphalt_binder_config_path

            db = MoleculeDB()
            aging_yaml = get_asphalt_binder_config_path()  # 경로 SSOT (자체조립 금지)
            if aging_yaml.exists():
                db.load_aging_library(aging_yaml)
            self._molecule_db = db
        return self._molecule_db

    @staticmethod
    def _resolve_mol_path(db: Any, mol_id: str) -> Path | None:
        """Resolve a species mol_id to its ``.mol`` file path.

        Primary: ``MoleculeDB.get_structure_file``. Fallback: additives are
        stored flat at ``data/molecules/additives/{mol_id}.mol`` (the DB keys
        them by additive_type string, which MoleculeDB does not index), so
        resolve them directly without modifying the molecule DB.
        """
        path = db.get_structure_file(mol_id, format="mol")
        if path is not None:
            return path
        from common.library_config import get_molecule_data_dir

        candidate = get_molecule_data_dir() / "additives" / f"{mol_id}.mol"
        return candidate if candidate.exists() else None

    def extract_from_counts(
        self,
        mol_counts: dict[str, int | float],
        temperature_k: float,
    ) -> dict[str, float] | None:
        """Extract features from a {mol_id: count} composition.

        Args:
            mol_counts: Molecule species counts (instances per species).
            temperature_k: System temperature (K).

        Returns:
            32-feature dict, or None when RDKit is unavailable or no
            species could be resolved to a parseable ``.mol`` file.
        """
        if not RDKIT_AVAILABLE:
            return None
        db = self._get_molecule_db()
        species: dict[str, tuple[tuple[float, ...], int]] = {}
        for mol_id, count in mol_counts.items():
            n = int(round(float(count)))
            if n <= 0:
                continue
            path = self._resolve_mol_path(db, mol_id)
            if path is None:
                logger.warning(
                    "structural_features: no .mol for species %s — skipped", mol_id
                )
                continue
            descriptors = compute_molecule_descriptors(str(path))
            if descriptors is None:
                continue
            species[mol_id] = (descriptors, n)
        if not species:
            return None
        return aggregate_structural_features(species, temperature_k)

    def extract_from_db(
        self,
        session: Any,
        experiment_id: int,
        temperature_k: float,
    ) -> dict[str, float] | None:
        """Extract features for a stored experiment (training path).

        Args:
            session: SQLAlchemy session.
            experiment_id: ExperimentModel.id (PK).
            temperature_k: Experiment temperature (K).

        Returns:
            32-feature dict or None (RDKit/composition unavailable).
        """
        if not RDKIT_AVAILABLE:
            return None
        from database.models import ExperimentMoleculeModel, MoleculeModel

        rows = (
            session.query(MoleculeModel.mol_id, ExperimentMoleculeModel.count)
            .join(
                ExperimentMoleculeModel,
                MoleculeModel.id == ExperimentMoleculeModel.molecule_id,
            )
            .filter(ExperimentMoleculeModel.experiment_id == experiment_id)
            .all()
        )
        mol_counts = {mol_id: int(count or 0) for mol_id, count in rows}
        if not mol_counts:
            return None
        return self.extract_from_counts(mol_counts, temperature_k)
