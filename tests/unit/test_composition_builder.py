from types import SimpleNamespace

from features.experiments.composition_builder import build_molecule_composition


class _FakeCategory:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeDB:
    def __init__(self) -> None:
        self._specs = {
            "U-SA-Squalane-0293": SimpleNamespace(
                molecular_weight=100.0,
                atom_count=10,
                category=_FakeCategory("saturate"),
            ),
            "SiO2": SimpleNamespace(
                molecular_weight=200.0,
                atom_count=20,
                category=_FakeCategory("additive"),
            ),
        }

    def _find_molecule_def(self, config, base_id):
        for mol_def in config.get("molecules", []):
            if mol_def.get("base_id") == base_id:
                return mol_def
        return None

    def get(self, mol_id):
        return self._specs.get(mol_id)

    def get_molecule_atom_count(self, _config, _mol_id, default=50):
        return default

    def get_molecule_molecular_weight(self, _config, _mol_id, default=400.0):
        return default

    def get_additive_atom_count(self, _config, _mol_id, default=100):
        return default


def test_build_molecule_composition_keeps_additive_canonical_mol_id() -> None:
    request = SimpleNamespace(
        molecule_counts=[SimpleNamespace(mol_id="SA-Squalane", count=3)],
        additives=[SimpleNamespace(mol_id="SiO2", count=2)],
    )
    config = {
        "aging_categories": {"non_aging": {"prefix": "U"}},
        "molecules": [{"base_id": "SA-Squalane", "available_aging": ["non_aging"]}],
    }

    result = build_molecule_composition(
        request=request,
        config=config,
        db=_FakeDB(),
        temp_code="0293",
        aging_state="non_aging",
    )

    assert result.mol_composition["U-SA-Squalane-0293"] == 3.0
    assert result.mol_composition["SiO2"] == 2.0
    assert "U-SiO2-0293" not in result.mol_composition


def test_explicit_structure_file_molecules_use_bare_base_id() -> None:
    """single_moles의 structure_file 분자(H2O 등)는 base_id 그대로 사용."""
    db = _FakeDB()
    db._specs["H2O"] = SimpleNamespace(
        molecular_weight=18.015,
        atom_count=3,
        category=_FakeCategory("aromatic"),
    )

    request = SimpleNamespace(
        molecule_counts=[
            SimpleNamespace(mol_id="SA-Squalane", count=3),
            SimpleNamespace(mol_id="H2O", count=535),
        ],
        additives=None,
    )
    config = {
        "aging_categories": {"non_aging": {"prefix": "U"}},
        "molecules": [
            {"base_id": "SA-Squalane", "available_aging": ["non_aging"]},
            {
                "base_id": "H2O",
                "available_aging": [],
                "structure_file": "single_moles/H2O.mol",
            },
        ],
    }

    result = build_molecule_composition(
        request=request,
        config=config,
        db=db,
        temp_code="0293",
        aging_state="non_aging",
    )

    # H2O: structure_file이 있으므로 base_id 그대로
    assert "H2O" in result.mol_composition
    assert result.mol_composition["H2O"] == 535.0
    assert "U-H2O-0293" not in result.mol_composition

    # SA-Squalane: 기존 aging prefix 유지
    assert "U-SA-Squalane-0293" in result.mol_composition
