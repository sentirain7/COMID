"""Composition/build helpers for molecule-based submission."""

from dataclasses import dataclass


@dataclass
class MoleculeCompositionBuildResult:
    mol_composition: dict[str, float]
    sara_composition: dict[str, float]
    estimated_atoms: int
    total_molecules: int


def _get_full_mol_id(db, config: dict, base_id: str, aging: str, temp_code: str) -> str:
    """Get full mol_id with aging prefix and temperature code."""
    aging_categories = config.get("aging_categories", {})
    aging_info = aging_categories.get(aging, {})
    prefix = aging_info.get("prefix", "U")
    fallback_to = aging_info.get("fallback_to")

    mol_def = db._find_molecule_def(config, base_id)
    if mol_def:
        # structure_file이 있는 단독 분자(single_moles)는
        # MoleculeDB에서 base_id로 인덱싱됨 — prefix/temp_code 불필요.
        if str(mol_def.get("structure_file", "")).strip():
            return base_id

        available = mol_def.get("available_aging", ["non_aging"])
        if aging in available:
            return f"{prefix}-{base_id}-{temp_code}"
        if fallback_to and fallback_to in available:
            fb_prefix = config["aging_categories"][fallback_to]["prefix"]
            return f"{fb_prefix}-{base_id}-{temp_code}"

    return f"U-{base_id}-{temp_code}"


def _fallback_estimated_atoms(request) -> int:
    atom_estimates = {
        "SA-Squalane": 62,
        "SA-Hopane": 54,
        "AR-PHPN": 60,
        "AR-DOCHN": 50,
        "RE-Quin": 65,
        "RE-Pyrid": 55,
        "RE-Thio": 50,
        "RE-Benzo": 45,
        "RE-Trim": 40,
        "AS-Pyrrole": 100,
        "AS-Phenol": 90,
        "AS-Thio": 95,
        "SiO2": 500,
        "Lignin": 150,
    }
    estimated_atoms = sum(
        mc.count * atom_estimates.get(mc.mol_id, 50) for mc in request.molecule_counts
    )
    if request.additives:
        estimated_atoms += sum(
            a.count * atom_estimates.get(a.mol_id, 100) for a in request.additives
        )
    return estimated_atoms


def build_molecule_composition(
    request, config, db, temp_code: str, aging_state: str
) -> MoleculeCompositionBuildResult:
    """Build mol_count composition and derived SARA/atom estimates."""
    mol_composition: dict[str, float] = {}
    sara_weights = {"asphaltene": 0.0, "resin": 0.0, "aromatic": 0.0, "saturate": 0.0}
    total_weight = 0.0
    estimated_atoms = 0

    for mc in request.molecule_counts:
        full_mol_id = (
            _get_full_mol_id(db, config, mc.mol_id, aging_state, temp_code)
            if config
            else f"U-{mc.mol_id}-{temp_code}"
        )
        mol_composition[full_mol_id] = float(mc.count)

        spec = db.get(full_mol_id)
        if spec:
            weight = mc.count * spec.molecular_weight
            sara_weights[spec.category.value] += weight
            total_weight += weight
            estimated_atoms += mc.count * spec.atom_count
        else:
            if config:
                atom_count = db.get_molecule_atom_count(config, mc.mol_id, default=50)
                mw = db.get_molecule_molecular_weight(config, mc.mol_id, default=400.0)
            else:
                atom_count = 50
                mw = 400.0
            estimated_atoms += mc.count * atom_count
            total_weight += mc.count * mw

    if request.additives:
        for add in request.additives:
            additive_mol_id = add.mol_id
            mol_composition[additive_mol_id] = float(add.count)
            spec = db.get(additive_mol_id)
            if spec:
                total_weight += add.count * spec.molecular_weight
                estimated_atoms += add.count * spec.atom_count
            else:
                atom_count = (
                    db.get_additive_atom_count(config, add.mol_id, default=100) if config else 100
                )
                estimated_atoms += add.count * atom_count
                total_weight += add.count * 500.0

    if total_weight > 0:
        sara_composition = {k: v / total_weight for k, v in sara_weights.items()}
    else:
        sara_composition = {"asphaltene": 0.2, "resin": 0.3, "aromatic": 0.35, "saturate": 0.15}

    if estimated_atoms == 0:
        estimated_atoms = _fallback_estimated_atoms(request)

    total_molecules = sum(mc.count for mc in request.molecule_counts)
    if request.additives:
        total_molecules += sum(a.count for a in request.additives)

    return MoleculeCompositionBuildResult(
        mol_composition=mol_composition,
        sara_composition=sara_composition,
        estimated_atoms=estimated_atoms,
        total_molecules=total_molecules,
    )
