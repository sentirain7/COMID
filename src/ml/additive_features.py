"""
Additive feature extraction for ML V2.

Extracts one-hot encoding, molecular descriptors, and interaction features
from additive metadata for ML V2 feature set.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from contracts.schemas import AdditiveSubcategory, FunctionalTag

if TYPE_CHECKING:
    from contracts.policies.ml_policy import FeatureSetVersion
    from contracts.schemas import ExperimentRecord

logger = logging.getLogger(__name__)


# ── Molecular descriptor lookup table ──────────────────────────────────────


@dataclass(frozen=True)
class AdditiveDescriptors:
    """Molecular descriptors for a known additive."""

    mw: float = 0.0
    logp: float = 0.0
    hbd: int = 0
    hba: int = 0


ADDITIVE_DESCRIPTOR_TABLE: dict[str, AdditiveDescriptors] = {
    "ADD_001": AdditiveDescriptors(mw=115.17, logp=-0.55, hbd=1, hba=1),  # ppa_monomer
    "ADD_002": AdditiveDescriptors(mw=282.46, logp=7.64, hbd=1, hba=2),  # oleic_acid
    "ADD_003": AdditiveDescriptors(mw=104.15, logp=2.25, hbd=0, hba=0),  # sbs_unit
    "ADD_004": AdditiveDescriptors(mw=256.52, logp=0.0, hbd=0, hba=0),  # sulfur_s8
    "ADD_005": AdditiveDescriptors(mw=72.06, logp=-0.65, hbd=0, hba=2),  # maleic_anhydride
    # Phase 5-8: 6 additives matched to candidate_db_source.py ADDITIVE_CATALOG
    "ADD_SBS_001": AdditiveDescriptors(mw=1200.0, logp=4.5, hbd=0, hba=0),
    "ADD_ELVALOY_001": AdditiveDescriptors(mw=850.0, logp=2.8, hbd=0, hba=2),
    "ADD_PPA_001": AdditiveDescriptors(mw=257.95, logp=-1.2, hbd=3, hba=6),
    "ADD_SASOBIT_001": AdditiveDescriptors(mw=800.0, logp=12.0, hbd=0, hba=0),
    "ADD_NCLAY_001": AdditiveDescriptors(mw=1500.0, logp=0.0, hbd=0, hba=8),
    "ADD_CRM_001": AdditiveDescriptors(mw=1800.0, logp=5.0, hbd=0, hba=0),
    # Canonical additive catalog mol_id values (SSOT)
    "SBS": AdditiveDescriptors(mw=1200.0, logp=4.5, hbd=0, hba=0),
    "Elvaloy": AdditiveDescriptors(mw=850.0, logp=2.8, hbd=0, hba=2),
    "PPA": AdditiveDescriptors(mw=257.95, logp=-1.2, hbd=3, hba=6),
    "Sasobit": AdditiveDescriptors(mw=800.0, logp=12.0, hbd=0, hba=0),
    "NanoClay": AdditiveDescriptors(mw=1500.0, logp=0.0, hbd=0, hba=8),
    "CRM": AdditiveDescriptors(mw=1800.0, logp=5.0, hbd=0, hba=0),
}

_ADDITIVE_DESCRIPTOR_TABLE_CASEFOLD: dict[str, AdditiveDescriptors] = {
    key.casefold(): value for key, value in ADDITIVE_DESCRIPTOR_TABLE.items()
}


# ── Additive type → enum mappings ──────────────────────────────────────────

_TYPE_TO_SUBCATEGORY: dict[str, AdditiveSubcategory] = {
    # Canonical values (StrEnum values)
    "polymer": AdditiveSubcategory.POLYMER,
    "surfactant": AdditiveSubcategory.SURFACTANT,
    "nanoparticle": AdditiveSubcategory.NANOPARTICLE,
    # Normalized aliases (strip/lower/remove symbols)
    "sbs": AdditiveSubcategory.POLYMER,
    "sbsunit": AdditiveSubcategory.POLYMER,
    "ppa": AdditiveSubcategory.SURFACTANT,
    "ppamonomer": AdditiveSubcategory.SURFACTANT,
    "oleicacid": AdditiveSubcategory.SURFACTANT,
    "sio2": AdditiveSubcategory.NANOPARTICLE,
    "nano": AdditiveSubcategory.NANOPARTICLE,
    "maleicanhydride": AdditiveSubcategory.SURFACTANT,
    "sulfur": AdditiveSubcategory.POLYMER,
    "sulfurs8": AdditiveSubcategory.POLYMER,
    # Phase 5-8: new catalog additives
    "elvaloy": AdditiveSubcategory.POLYMER,
    "sasobit": AdditiveSubcategory.SURFACTANT,
    "nanoclay": AdditiveSubcategory.NANOPARTICLE,
    "crm": AdditiveSubcategory.POLYMER,
    "crumbrubber": AdditiveSubcategory.POLYMER,
}

_TYPE_TO_FUNCTIONAL_TAG: dict[str, FunctionalTag] = {
    "antiaging": FunctionalTag.ANTI_AGING,
    "anti_aging": FunctionalTag.ANTI_AGING,
    "antistripping": FunctionalTag.ANTI_STRIPPING,
    "anti_stripping": FunctionalTag.ANTI_STRIPPING,
    "modifier": FunctionalTag.MODIFIER,
    # Common additive → functional tag
    "sbs": FunctionalTag.MODIFIER,
    "sbsunit": FunctionalTag.MODIFIER,
    "ppa": FunctionalTag.ANTI_STRIPPING,
    "ppamonomer": FunctionalTag.ANTI_STRIPPING,
    "oleicacid": FunctionalTag.ANTI_STRIPPING,
    "sio2": FunctionalTag.MODIFIER,
    # Phase 5-8: new catalog additives
    "elvaloy": FunctionalTag.MODIFIER,
    "sasobit": FunctionalTag.MODIFIER,
    "nanoclay": FunctionalTag.ANTI_AGING,
    "crm": FunctionalTag.MODIFIER,
    "crumbrubber": FunctionalTag.MODIFIER,
}


# ── V2 additive feature names (13 total) ──────────────────────────────────

ADDITIVE_FEATURE_NAMES: list[str] = [
    "additive_is_polymer",
    "additive_is_surfactant",
    "additive_is_nanoparticle",
    "additive_func_anti_aging",
    "additive_func_anti_stripping",
    "additive_func_modifier",
    "additive_mw",
    "additive_logp",
    "additive_hbd",
    "additive_hba",
    "additive_wt_x_asphaltene_wt",
    "additive_wt_x_polar_fraction",
    "additive_mw_x_additive_wt",
]


# ── Normalization helper ───────────────────────────────────────────────────


def normalize_additive_type(raw: str | None) -> str | None:
    """Normalize additive type string for lookup.

    Args:
        raw: Raw additive type string (e.g. "SBS", " Sbs ", "s-b-s").

    Returns:
        Normalized string (lowercase, no spaces/hyphens/underscores) or None.
    """
    if raw is None:
        return None
    return raw.strip().lower().replace("-", "").replace("_", "").replace(" ", "")


# ── Feature extractor ─────────────────────────────────────────────────────


class AdditiveFeatureExtractor:
    """Extract V2 additive features (13 total)."""

    def extract(
        self,
        additive_type: str | None,
        additive_mol_id: str | None,
        additive_wt: float,
        asphaltene_wt: float,
        polar_fraction: float,
    ) -> dict[str, float]:
        """Extract 13 additive features.

        Args:
            additive_type: Additive subcategory or name (e.g. "polymer", "SBS").
            additive_mol_id: Molecule ID (e.g. "ADD_003").
            additive_wt: Additive weight fraction (wt%).
            asphaltene_wt: Asphaltene weight fraction (wt%).
            polar_fraction: Polar fraction (asphaltene + resin, wt%).

        Returns:
            Dict with 13 feature name→value pairs.
        """
        zeros = dict.fromkeys(ADDITIVE_FEATURE_NAMES, 0.0)

        # Guard clause: no additive → all zeros
        if additive_wt <= 0.0 or additive_type is None:
            return zeros

        result = dict(zeros)
        normalized_type = normalize_additive_type(additive_type)

        # One-hot: subcategory
        subcategory = _TYPE_TO_SUBCATEGORY.get(normalized_type) if normalized_type else None
        if subcategory is not None:
            if subcategory == AdditiveSubcategory.POLYMER:
                result["additive_is_polymer"] = 1.0
            elif subcategory == AdditiveSubcategory.SURFACTANT:
                result["additive_is_surfactant"] = 1.0
            elif subcategory == AdditiveSubcategory.NANOPARTICLE:
                result["additive_is_nanoparticle"] = 1.0
        else:
            logger.warning(
                "Unrecognized additive_type '%s' (normalized: '%s'), one-hot features set to 0.0",
                additive_type,
                normalized_type,
            )

        # One-hot: functional tag
        func_tag = _TYPE_TO_FUNCTIONAL_TAG.get(normalized_type) if normalized_type else None
        if func_tag is not None:
            if func_tag == FunctionalTag.ANTI_AGING:
                result["additive_func_anti_aging"] = 1.0
            elif func_tag == FunctionalTag.ANTI_STRIPPING:
                result["additive_func_anti_stripping"] = 1.0
            elif func_tag == FunctionalTag.MODIFIER:
                result["additive_func_modifier"] = 1.0

        # Molecular descriptors
        descriptors = (
            _ADDITIVE_DESCRIPTOR_TABLE_CASEFOLD.get(additive_mol_id.casefold())
            if additive_mol_id
            else None
        )
        if descriptors is not None:
            result["additive_mw"] = descriptors.mw
            result["additive_logp"] = descriptors.logp
            result["additive_hbd"] = float(descriptors.hbd)
            result["additive_hba"] = float(descriptors.hba)
        elif additive_mol_id:
            logger.warning(
                "Unregistered additive_mol_id '%s', molecular descriptors set to 0.0",
                additive_mol_id,
            )

        # Interaction features
        result["additive_wt_x_asphaltene_wt"] = additive_wt * asphaltene_wt
        result["additive_wt_x_polar_fraction"] = additive_wt * polar_fraction
        result["additive_mw_x_additive_wt"] = result["additive_mw"] * additive_wt

        return result

    def extract_features(self, record: ExperimentRecord) -> dict[str, float]:
        """IFeatureExtractor adapter — extract features from ExperimentRecord.

        Composition source priority:
          1. build_result.actual_composition_wt (actual packing result)
          2. record.metadata comp_* fields (DB-propagated, matches DataLoader)

        This ensures train/serve consistency: DataLoader uses comp_asphaltene_wt
        etc. from ExperimentModel columns, which are mirrored here via the
        metadata fallback when build_result is absent.

        Args:
            record: Experiment record with additive metadata.

        Returns:
            Dict with 13 feature name→value pairs.
        """
        asphaltene_wt = 0.0
        resin_wt = 0.0

        # Priority 1: build_result.actual_composition_wt (actual packing result)
        if record.build_result and record.build_result.actual_composition_wt:
            asphaltene_wt = record.build_result.actual_composition_wt.get("asphaltene", 0.0)
            resin_wt = record.build_result.actual_composition_wt.get("resin", 0.0)
        # Priority 2: record.metadata (DB-propagated comp_* fields)
        elif hasattr(record, "metadata") and record.metadata:
            asphaltene_wt = record.metadata.get("comp_asphaltene_wt", 0.0)
            resin_wt = record.metadata.get("comp_resin_wt", 0.0)

        return self.extract(
            additive_type=record.additive_type,
            additive_mol_id=record.additive_mol_id,
            additive_wt=record.additive_wt or 0.0,
            asphaltene_wt=asphaltene_wt,
            polar_fraction=asphaltene_wt + resin_wt,
        )

    def get_feature_set_version(self) -> FeatureSetVersion:
        """Return the feature set version this extractor produces."""
        from contracts.policies.ml_policy import FeatureSetVersion

        return FeatureSetVersion.V2
