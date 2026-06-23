"""Unit tests for InorganicParameterService.

Tests site-specific parameterization for inorganic additives (SiO2, etc.)
with 1-based atom indices and profile-based charge/LJ assignment.
"""

from collections import Counter
from unittest.mock import MagicMock

import pytest


class TestInorganicParameterService:
    """Tests for InorganicParameterService."""

    @pytest.fixture
    def service(self):
        """Create InorganicParameterService with default profiles."""
        from forcefield.inorganic_parameter_service import InorganicParameterService

        return InorganicParameterService()

    @pytest.fixture
    def mock_sio2_topology(self):
        """Create mock SiO2 topology with 1-based indices."""
        from builder.mol_types import MolAtom, MolBond, MolTopology

        # Simplified SiO2 cluster: 1 Si, 4 O (2 bridging, 2 hydroxyl), 2 H
        # Total: 7 atoms for this minimal test
        atoms = [
            MolAtom(index=1, element="Si", x=0, y=0, z=0),  # Si_tet
            MolAtom(index=2, element="O", x=1.62, y=0, z=0),  # O_br (2 Si neighbors)
            MolAtom(index=3, element="O", x=-1.62, y=0, z=0),  # O_h (1 Si, 1 H)
            MolAtom(index=4, element="H", x=-2.5, y=0, z=0),  # H_oh
        ]

        # Bonds: Si-O_br, Si-O_h, O_h-H_oh
        bonds = [
            MolBond(atom1=1, atom2=2, order=1),  # Si-O_br
            MolBond(atom1=1, atom2=3, order=1),  # Si-O_h
            MolBond(atom1=3, atom2=4, order=1),  # O_h-H_oh
        ]

        # For O_br to have 2 Si neighbors, we need another Si
        # Let's simplify: just test that site inference works
        return MolTopology(mol_id="test_SiO2", atoms=atoms, bonds=bonds)

    def test_service_loads_profiles(self, service):
        """Service should load profiles from YAML."""
        profile = service.get_profile("silica_hydroxylated_v1")
        assert profile is not None
        assert profile["status"] == "active"
        assert "site_rules" in profile
        assert "atom_types" in profile

    def test_is_profile_active(self, service):
        """is_profile_active should return correct status."""
        assert service.is_profile_active("silica_hydroxylated_v1") is True
        assert service.is_profile_active("montmorillonite_v1") is False  # draft
        assert service.is_profile_active("nonexistent") is False

    def test_blocked_placeholder_raises(self, service, mock_sio2_topology):
        """blocked_placeholder status should raise InorganicParameterizationError."""
        from forcefield.inorganic_parameter_service import InorganicParameterizationError

        additive_def = {
            "short_name": "NanoClay",
            "parameterization": {"status": "blocked_placeholder"},
        }

        with pytest.raises(InorganicParameterizationError, match="blocked_placeholder"):
            service.assign(mock_sio2_topology, additive_def)

    def test_organic_passthrough_raises(self, service, mock_sio2_topology):
        """organic_gaff2_passthrough mode should raise (use standard path instead)."""
        from forcefield.inorganic_parameter_service import InorganicParameterizationError

        additive_def = {
            "short_name": "CNT",
            "parameterization": {
                "mode": "organic_gaff2_passthrough",
                "status": "active",
            },
        }

        with pytest.raises(InorganicParameterizationError, match="organic_gaff2_passthrough"):
            service.assign(mock_sio2_topology, additive_def)

    def test_draft_profile_raises(self, service, mock_sio2_topology):
        """draft status profile should raise InorganicParameterizationError."""
        from forcefield.inorganic_parameter_service import InorganicParameterizationError

        additive_def = {
            "short_name": "NanoClay",
            "parameterization": {
                "mode": "inorganic_profile",
                "profile_id": "montmorillonite_v1",
                "status": "active",
            },
        }

        with pytest.raises(InorganicParameterizationError, match="not active"):
            service.assign(mock_sio2_topology, additive_def)

    def test_missing_profile_raises(self, service, mock_sio2_topology):
        """Nonexistent profile should raise error."""
        from forcefield.inorganic_parameter_service import InorganicParameterizationError

        additive_def = {
            "short_name": "Unknown",
            "parameterization": {
                "mode": "inorganic_profile",
                "profile_id": "nonexistent_profile_v1",
                "status": "active",
            },
        }

        with pytest.raises(InorganicParameterizationError, match="not found"):
            service.assign(mock_sio2_topology, additive_def)

    def test_site_assignment_mutates_topology_with_real_sio2(self, service):
        """assign() should mutate topology atoms with ff_type and charge using real SiO2.mol."""

        from builder.mol_parser import parse_mol_topology
        from common.pathing import get_project_root

        # Use actual SiO2.mol file for realistic test
        mol_file = get_project_root() / "data" / "molecules" / "additives" / "SiO2.mol"
        if not mol_file.exists():
            pytest.skip("SiO2.mol not found")

        topo = parse_mol_topology(mol_file, "SiO2")

        additive_def = {
            "short_name": "SiO2",
            "parameterization": {
                "mode": "inorganic_profile",
                "profile_id": "silica_hydroxylated_v1",
                "status": "active",
            },
        }

        result = service.assign(topo, additive_def)

        # Si atoms should have ff_type and charge set
        si_atoms = [a for a in topo.atoms if a.element == "Si"]
        assert len(si_atoms) > 0
        for si_atom in si_atoms:
            assert si_atom.ff_type == "Si_tet"
            assert si_atom.charge == 2.1
            assert si_atom.charge_defined is True

        # Check total charge is approximately neutral
        assert abs(result.total_charge) < 0.01

    def test_assignment_result_has_coefficients_with_real_sio2(self, service):
        """InorganicAssignmentResult should contain FF coefficients using real SiO2.mol."""

        from builder.mol_parser import parse_mol_topology
        from common.pathing import get_project_root

        # Use actual SiO2.mol file for realistic test
        mol_file = get_project_root() / "data" / "molecules" / "additives" / "SiO2.mol"
        if not mol_file.exists():
            pytest.skip("SiO2.mol not found")

        topo = parse_mol_topology(mol_file, "SiO2")

        additive_def = {
            "short_name": "SiO2",
            "parameterization": {
                "mode": "inorganic_profile",
                "profile_id": "silica_hydroxylated_v1",
                "status": "active",
            },
        }

        result = service.assign(topo, additive_def)

        assert result.profile_id == "silica_hydroxylated_v1"
        assert "Si_tet" in result.atom_type_coeffs
        assert result.atom_type_coeffs["Si_tet"]["epsilon"] == pytest.approx(0.00040)
        assert result.atom_type_coeffs["Si_tet"]["sigma"] == pytest.approx(3.302)

    def test_get_element_lj_from_profile(self, service):
        """get_element_lj_from_profile should return LJ for element."""
        lj = service.get_element_lj_from_profile("silica_hydroxylated_v1", "Si")
        assert lj is not None
        assert lj["epsilon"] == pytest.approx(0.00040)
        assert lj["sigma"] == pytest.approx(3.302)

        # O should also work (first O site type found)
        lj_o = service.get_element_lj_from_profile("silica_hydroxylated_v1", "O")
        assert lj_o is not None
        assert lj_o["epsilon"] == pytest.approx(0.15540)

        # Nonexistent element should return None
        assert service.get_element_lj_from_profile("silica_hydroxylated_v1", "Fe") is None

    def test_get_all_element_lj_from_active_profiles(self, service):
        """get_all_element_lj_from_active_profiles should return element -> LJ mapping."""
        elem_lj = service.get_all_element_lj_from_active_profiles()

        # Should have Si, O, H from silica profile
        assert "Si" in elem_lj
        assert "O" in elem_lj
        assert "H" in elem_lj

        assert elem_lj["Si"]["epsilon"] == pytest.approx(0.00040)


class TestMolTopologyBuilderOverrides:
    """Tests for MolTopologyBuilder with inorganic overrides."""

    def test_override_only_types_work_without_registry(self):
        """Override-only types (Si_tet, O_br) should work without registry entry."""
        from forcefield.topology import MolTopologyBuilder

        builder = MolTopologyBuilder(
            atom_param_overrides={
                "Si_tet": {"mass": 28.085, "epsilon": 0.00040, "sigma": 3.302},
            }
        )

        # Should not raise - override takes priority
        params = builder._get_ff_atom_params_from_type("Si_tet", "Si")
        assert params["epsilon"] == pytest.approx(0.00040)
        assert params["sigma"] == pytest.approx(3.302)

    def test_bond_override_priority(self):
        """Bond override should take priority over registry."""
        from forcefield.topology import MolTopologyBuilder

        builder = MolTopologyBuilder(
            bond_param_overrides={
                "Si_tet-O_br": {"k": 285.0, "r0": 1.62},
            }
        )

        params, label = builder._get_bond_interaction_params(("Si_tet", "O_br"), ("Si", "O"))
        assert params["k"] == pytest.approx(285.0)
        assert params["r0"] == pytest.approx(1.62)
        assert label == "Si_tet-O_br"

    def test_angle_override_priority(self):
        """Angle override should take priority over registry."""
        from forcefield.topology import MolTopologyBuilder

        builder = MolTopologyBuilder(
            angle_param_overrides={
                "O_br-Si_tet-O_br": {"k": 100.0, "theta0": 109.47},
            }
        )

        params, label = builder._get_angle_interaction_params(
            ("O_br", "Si_tet", "O_br"), ("O", "Si", "O")
        )
        assert params["k"] == pytest.approx(100.0)
        assert params["theta0"] == pytest.approx(109.47)

    def test_dihedral_override_priority(self):
        """Dihedral override should take priority over registry."""
        from forcefield.topology import MolTopologyBuilder

        builder = MolTopologyBuilder(
            dihedral_param_overrides={
                "O_br-Si_tet-O_h-H_oh": {"k1": 0.0, "k2": 0.0, "k3": 0.25, "k4": 0.0},
            }
        )

        params, label = builder._get_dihedral_interaction_params(
            ("O_br", "Si_tet", "O_h", "H_oh"), ("O", "Si", "O", "H")
        )
        assert params["k3"] == pytest.approx(0.25)
        assert label == "O_br-Si_tet-O_h-H_oh"

    def test_dihedral_fallback_policy_allow_default_inorganic_only(self):
        """dihedral_fallback_policy=allow_default_fallback should only apply to inorganic dihedrals."""
        from forcefield.topology import MolTopologyBuilder

        builder = MolTopologyBuilder(
            strict_param_coverage=True,  # Would normally raise
            dihedral_fallback_policy="allow_default_fallback",
            inorganic_ff_types={"Si_tet", "O_br", "O_h", "H_oh"},
        )

        # Inorganic dihedral - should NOT raise and use inorganic-default (fourier format)
        params, label = builder._get_dihedral_interaction_params(
            ("Si_tet", "O_br", "Si_tet", "O_br"), ("Si", "O", "Si", "O")
        )
        assert params["style"] == "fourier"
        assert params["coeffs"] == (0.0, 1, 1)  # single fourier term, zero barrier
        assert "(inorganic-default)" in label

        # Purely organic dihedral - should still raise ValueError with strict mode
        with pytest.raises(ValueError, match="Missing dihedral parameters"):
            builder._get_dihedral_interaction_params(("Xx", "Yy", "Zz", "Ww"), ("X", "Y", "Z", "W"))

    def test_dihedral_fallback_without_inorganic_types_raises(self):
        """allow_default_fallback without inorganic_ff_types should not allow fallback."""
        from forcefield.topology import MolTopologyBuilder

        builder = MolTopologyBuilder(
            strict_param_coverage=True,
            dihedral_fallback_policy="allow_default_fallback",
            # No inorganic_ff_types set
        )

        # Unknown dihedral type - should raise because no inorganic types defined
        with pytest.raises(ValueError, match="Missing dihedral parameters"):
            builder._get_dihedral_interaction_params(("Xx", "Yy", "Zz", "Ww"), ("X", "Y", "Z", "W"))

    def test_mixed_organic_inorganic_dihedral_fallback(self):
        """Mixed organic-inorganic dihedral should use fallback if any type is inorganic."""
        from forcefield.topology import MolTopologyBuilder

        builder = MolTopologyBuilder(
            strict_param_coverage=True,
            dihedral_fallback_policy="allow_default_fallback",
            inorganic_ff_types={"Si_tet", "O_br"},
        )

        # Mixed dihedral with one inorganic type - should use fallback (fourier)
        params, label = builder._get_dihedral_interaction_params(
            ("C", "O_br", "Si_tet", "C"), ("C", "O", "Si", "C")
        )
        assert params["style"] == "fourier"
        assert params["coeffs"] == (0.0, 1, 1)
        assert "(inorganic-default)" in label

    def test_registry_dihedral_takes_priority_over_inorganic_fallback(self):
        """Explicit dihedral override should take priority over inorganic fallback."""
        from forcefield.topology import MolTopologyBuilder

        # Supply an explicit dihedral override for CA-CA-CA-CA so it takes
        # priority over the inorganic default fallback path.
        builder = MolTopologyBuilder(
            strict_param_coverage=True,
            dihedral_fallback_policy="allow_default_fallback",
            inorganic_ff_types={"CA"},  # Even if CA is in inorganic set
            dihedral_param_overrides={
                "CA-CA-CA-CA": {"k1": 0.0, "k2": 7.25, "k3": 0.0, "k4": 0.0},
            },
        )

        # CA-CA-CA-CA override should be used, not inorganic fallback
        params, label = builder._get_dihedral_interaction_params(
            ("CA", "CA", "CA", "CA"), ("C", "C", "C", "C")
        )
        # Should have override values, not inorganic-default
        assert "(inorganic-default)" not in label
        assert "(default)" not in label

    def test_dihedral_fallback_policy_strict_raises(self):
        """dihedral_fallback_policy=strict with strict_param_coverage should raise."""
        from forcefield.topology import MolTopologyBuilder

        builder = MolTopologyBuilder(
            strict_param_coverage=True,
            dihedral_fallback_policy="strict",
        )

        # Unknown dihedral type - should raise
        with pytest.raises(ValueError, match="Missing dihedral parameters"):
            builder._get_dihedral_interaction_params(("Xx", "Yy", "Zz", "Ww"), ("X", "Y", "Z", "W"))


class TestMoleculeDBAdditiveMethods:
    """Tests for MoleculeDB additive definition methods."""

    @pytest.fixture
    def molecule_db(self):
        """Create MoleculeDB with additives loaded."""
        from builder.molecule_db import MoleculeDB

        return MoleculeDB()

    def test_get_additive_definition_sio2(self, molecule_db):
        """get_additive_definition should return SiO2 definition."""
        defn = molecule_db.get_additive_definition("SiO2")
        assert defn is not None
        assert defn.get("parameterization", {}).get("mode") == "inorganic_profile"
        assert defn.get("parameterization", {}).get("profile_id") == "silica_hydroxylated_v1"

    def test_get_additive_definition_nanoclay(self, molecule_db):
        """get_additive_definition should return NanoClay definition."""
        defn = molecule_db.get_additive_definition("NanoClay")
        assert defn is not None
        assert defn.get("parameterization", {}).get("status") == "blocked_placeholder"

    def test_is_additive_blocked_nanoclay(self, molecule_db):
        """is_additive_blocked should return True for NanoClay."""
        assert molecule_db.is_additive_blocked("NanoClay") is True

    def test_is_additive_blocked_sio2(self, molecule_db):
        """is_additive_blocked should return False for SiO2."""
        assert molecule_db.is_additive_blocked("SiO2") is False

    def test_is_additive_blocked_nonexistent(self, molecule_db):
        """is_additive_blocked should return False for nonexistent additive."""
        assert molecule_db.is_additive_blocked("NonexistentAdditive") is False

    def test_get_additive_definition_cnt(self, molecule_db):
        """CNT should have organic_gaff2 mode (v01.01.00: no longer passthrough)."""
        defn = molecule_db.get_additive_definition("Carbon_Nano_Tube")
        assert defn is not None
        assert defn.get("parameterization", {}).get("mode") == "organic_gaff2"


class TestExactMatch:
    """Tests for _exact_match site matching logic."""

    @pytest.fixture
    def service(self):
        """Create InorganicParameterService."""
        from forcefield.inorganic_parameter_service import InorganicParameterService

        return InorganicParameterService()

    def test_exact_match_with_zero_count(self, service):
        """H:0 condition should mean 'H absent'."""
        # Pattern {Si: 2, H: 0} with actual {Si: 2} should match
        assert service._exact_match({"Si": 2, "H": 0}, Counter({"Si": 2})) is True

    def test_extra_neighbor_rejects_match(self, service):
        """Extra neighbor element should reject match."""
        # Pattern {Si: 2, H: 0} with actual {Si: 2, C: 1} should fail
        assert service._exact_match({"Si": 2, "H": 0}, Counter({"Si": 2, "C": 1})) is False

    def test_exact_match_all_present(self, service):
        """All pattern elements present with correct counts should match."""
        assert service._exact_match({"Si": 1, "H": 1}, Counter({"Si": 1, "H": 1})) is True

    def test_exact_match_wrong_count(self, service):
        """Wrong count should reject match."""
        assert service._exact_match({"Si": 2}, Counter({"Si": 1})) is False
        assert service._exact_match({"Si": 1}, Counter({"Si": 2})) is False

    def test_exact_match_empty_pattern(self, service):
        """Empty pattern should only match empty actual."""
        assert service._exact_match({}, Counter()) is True
        assert service._exact_match({}, Counter({"Si": 1})) is False


class TestDihedralPolicy:
    """Tests for dihedral_policy in InorganicAssignmentResult."""

    @pytest.fixture
    def service(self):
        """Create InorganicParameterService."""
        from forcefield.inorganic_parameter_service import InorganicParameterService

        return InorganicParameterService()

    def test_silica_profile_has_dihedral_policy(self, service):
        """silica_hydroxylated_v1 should have dihedral_policy set."""
        profile = service.get_profile("silica_hydroxylated_v1")
        assert profile is not None
        policy = profile.get("validation", {}).get("dihedral_policy")
        assert policy == "allow_default_fallback"

    def test_assignment_result_includes_dihedral_policy(self, service):
        """InorganicAssignmentResult should include dihedral_policy."""
        from builder.mol_parser import parse_mol_topology
        from common.pathing import get_project_root

        mol_file = get_project_root() / "data" / "molecules" / "additives" / "SiO2.mol"
        if not mol_file.exists():
            pytest.skip("SiO2.mol not found")

        topo = parse_mol_topology(mol_file, "SiO2")
        additive_def = {
            "short_name": "SiO2",
            "parameterization": {
                "mode": "inorganic_profile",
                "profile_id": "silica_hydroxylated_v1",
                "status": "active",
            },
        }

        result = service.assign(topo, additive_def)
        assert result.dihedral_policy == "allow_default_fallback"


class TestDeprecationWarnings:
    """Tests for deprecated method warnings."""

    def test_get_all_element_lj_deprecated(self):
        """get_all_element_lj_from_active_profiles should emit deprecation warning."""
        import warnings

        from forcefield.inorganic_parameter_service import InorganicParameterService

        service = InorganicParameterService()

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            service.get_all_element_lj_from_active_profiles()

            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message).lower()

    def test_get_lj_for_profile_no_warning(self):
        """get_lj_for_profile should not emit deprecation warning."""
        import warnings

        from forcefield.inorganic_parameter_service import InorganicParameterService

        service = InorganicParameterService()

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            service.get_lj_for_profile("silica_hydroxylated_v1", "Si")

            # Should not have deprecation warnings
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) == 0


class TestFailClosed:
    """Tests for fail-closed additive validation."""

    def test_molecule_db_stores_load_error(self):
        """MoleculeDB should store YAML load error for fail-closed decision."""

        from builder.molecule_db import MoleculeDB

        # Test with valid path - no error
        db = MoleculeDB()
        if db.get_additives_load_error() is None:
            # YAML loaded successfully
            assert db.get_additive_definition("SiO2") is not None
        else:
            # YAML failed to load - error should be stored
            assert isinstance(db.get_additives_load_error(), Exception)

    def test_get_additives_load_error_returns_none_on_success(self):
        """get_additives_load_error should return None when YAML loads successfully."""
        from builder.molecule_db import MoleculeDB

        db = MoleculeDB()
        # If the YAML exists and is valid, error should be None
        # (This assumes the YAML file exists in the test environment)
        if db._additive_defs:  # YAML loaded with some content
            assert db.get_additives_load_error() is None


class TestStructureBuilderFailClosed:
    """Integration tests for fail-closed behavior in StructureBuilder."""

    def test_blocked_placeholder_raises_build_error(self, tmp_path):
        """blocked_placeholder additive should raise BuildError in StructureBuilder.

        This tests the full path: MoleculeDB → StructureBuilder → BuildError.
        """

        from builder.molecule_db import MoleculeDB
        from builder.structure_builder import StructureBuilder
        from contracts.errors import BuildError, ErrorCode
        from contracts.schemas import MoleculeCategory, MoleculeInfo

        # Create a fake MOL file so _find_mol_file succeeds
        fake_mol = tmp_path / "blocked.mol"
        fake_mol.write_text("fake mol content")

        # Create a mock MoleculeDB that returns a blocked_placeholder additive
        mock_db = MagicMock(spec=MoleculeDB)
        mock_db.get_info.return_value = MoleculeInfo(
            mol_id="BlockedAdditive",
            molecular_weight=100.0,
            atom_count=10,
            category=MoleculeCategory.ADDITIVE,
        )
        mock_db.get_additive_definition.return_value = {
            "short_name": "BlockedAdditive",
            "parameterization": {"status": "blocked_placeholder"},
        }
        mock_db.get_additives_load_error.return_value = None
        # Wave 0: router consults ff_assignment first. Mirror the
        # blocked_placeholder status in the SSOT record so the router
        # reaches the BLOCKED branch via the ff_assignment path.
        mock_db.get_ff_assignment.return_value = {
            "route": "inorganic_profile",
            "status": "blocked_placeholder",
            "source_id": None,
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        mock_db.get_ff_assignment_load_error.return_value = None
        mock_db.parse_mol_topology.return_value = MagicMock(
            mol_id="BlockedAdditive",
            n_atoms=10,
            n_bonds=5,
            atoms=[],
            bonds=[],
        )

        builder = StructureBuilder(molecule_db=mock_db)

        # Mock PackmolMolecule with original_mol_file set to bypass _find_mol_file
        from builder.packmol_wrapper import PackmolMolecule

        pm_mol = PackmolMolecule(
            structure_file=fake_mol,
            count=1,
            mol_id="BlockedAdditive",
            original_mol_file=fake_mol,  # Bypass _find_mol_file
        )

        # Should raise BuildError due to blocked_placeholder
        with pytest.raises(BuildError) as exc_info:
            builder._generate_full_topology(
                packmol_molecules=[pm_mol],
                packed_xyz=tmp_path / "packed.xyz",
                mol_counts={"BlockedAdditive": 1},
                molecules={"BlockedAdditive": mock_db.get_info.return_value},
                output_file=tmp_path / "output.lammps",
            )

        assert exc_info.value.code == ErrorCode.TOPOLOGY_GENERATION_FAILED
        assert "blocked_placeholder" in str(exc_info.value.details)

    def test_yaml_load_error_raises_build_error(self, tmp_path):
        """YAML load error should raise BuildError for additive builds."""

        from builder.molecule_db import MoleculeDB
        from builder.structure_builder import StructureBuilder
        from contracts.errors import BuildError, ErrorCode
        from contracts.schemas import MoleculeCategory, MoleculeInfo

        # Create a fake MOL file
        fake_mol = tmp_path / "additive.mol"
        fake_mol.write_text("fake mol content")

        # Create a mock MoleculeDB with YAML load error
        mock_db = MagicMock(spec=MoleculeDB)
        mock_db.get_info.return_value = MoleculeInfo(
            mol_id="SomeAdditive",
            molecular_weight=100.0,
            atom_count=10,
            category=MoleculeCategory.ADDITIVE,
        )
        mock_db.get_additive_definition.return_value = None  # Would be in YAML
        mock_db.get_additives_load_error.return_value = Exception("YAML parse error")
        # Wave 0: no ff_assignment either (simulates a fully-unregistered mol_id)
        mock_db.get_ff_assignment.return_value = None
        mock_db.get_ff_assignment_load_error.return_value = None
        mock_db.parse_mol_topology.return_value = MagicMock(
            mol_id="SomeAdditive",
            n_atoms=10,
            n_bonds=5,
            atoms=[],
            bonds=[],
        )

        builder = StructureBuilder(molecule_db=mock_db)

        from builder.packmol_wrapper import PackmolMolecule

        pm_mol = PackmolMolecule(
            structure_file=fake_mol,
            count=1,
            mol_id="SomeAdditive",
            original_mol_file=fake_mol,
        )

        # Should raise BuildError due to YAML load error
        with pytest.raises(BuildError) as exc_info:
            builder._generate_full_topology(
                packmol_molecules=[pm_mol],
                packed_xyz=tmp_path / "packed.xyz",
                mol_counts={"SomeAdditive": 1},
                molecules={"SomeAdditive": mock_db.get_info.return_value},
                output_file=tmp_path / "output.lammps",
            )

        assert exc_info.value.code == ErrorCode.TOPOLOGY_GENERATION_FAILED
        assert "additives.yaml" in str(exc_info.value.details).lower()

    def test_inorganic_without_mode_raises_build_error(self, tmp_path):
        """Inorganic additive without parameterization.mode should raise BuildError."""

        from builder.molecule_db import MoleculeDB
        from builder.structure_builder import StructureBuilder
        from contracts.errors import BuildError, ErrorCode
        from contracts.schemas import MoleculeCategory, MoleculeInfo

        # Create a fake MOL file
        fake_mol = tmp_path / "inorganic.mol"
        fake_mol.write_text("fake mol content")

        mock_db = MagicMock(spec=MoleculeDB)
        mock_db.get_info.return_value = MoleculeInfo(
            mol_id="InorganicNoMode",
            molecular_weight=100.0,
            atom_count=10,
            category=MoleculeCategory.ADDITIVE,
        )
        # Inorganic category but missing parameterization.mode
        mock_db.get_additive_definition.return_value = {
            "short_name": "InorganicNoMode",
            "category": "inorganic",
            "parameterization": {},  # No mode specified
        }
        mock_db.get_additives_load_error.return_value = None
        # Wave 0: no ff_assignment so the router falls back to the legacy
        # additive_def branch, which must still block inorganic-without-mode.
        mock_db.get_ff_assignment.return_value = None
        mock_db.get_ff_assignment_load_error.return_value = None
        mock_db.parse_mol_topology.return_value = MagicMock(
            mol_id="InorganicNoMode",
            n_atoms=10,
            n_bonds=5,
            atoms=[],
            bonds=[],
        )

        builder = StructureBuilder(molecule_db=mock_db)

        from builder.packmol_wrapper import PackmolMolecule

        pm_mol = PackmolMolecule(
            structure_file=fake_mol,
            count=1,
            mol_id="InorganicNoMode",
            original_mol_file=fake_mol,
        )

        # Should raise BuildError due to missing mode
        with pytest.raises(BuildError) as exc_info:
            builder._generate_full_topology(
                packmol_molecules=[pm_mol],
                packed_xyz=tmp_path / "packed.xyz",
                mol_counts={"InorganicNoMode": 1},
                molecules={"InorganicNoMode": mock_db.get_info.return_value},
                output_file=tmp_path / "output.lammps",
            )

        assert exc_info.value.code == ErrorCode.TOPOLOGY_GENERATION_FAILED
        assert "parameterization.mode" in str(exc_info.value.details).lower()


class TestAdditiveRepoSync:
    """Tests for additive_repo sync_from_yaml with parameterization."""

    def test_sync_stores_parameterization_in_metadata_json(self, tmp_path):
        """sync_from_yaml should store parameterization in metadata_json."""
        import yaml
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from database.models import Base
        from database.repositories.additive_repo import AdditiveRepository

        # Create temp YAML with SiO2 additive
        yaml_content = {
            "additives": {
                "TestSiO2": {
                    "name": "Test Silicon Dioxide",
                    "short_name": "SiO2",
                    "atom_count": 102,
                    "molecular_weight": 2044.2,
                    "category": "inorganic",
                    "parameterization": {
                        "mode": "inorganic_profile",
                        "profile_id": "silica_hydroxylated_v1",
                        "profile_version": "1.0",
                        "status": "active",
                    },
                }
            }
        }
        yaml_path = tmp_path / "test_additives.yaml"
        yaml_path.write_text(yaml.dump(yaml_content))

        # Create in-memory SQLite database
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)

        with Session(engine) as session:
            repo = AdditiveRepository(session)
            result = repo.sync_from_yaml(yaml_path)
            session.commit()

            assert result["upserted"] == 1
            assert result["skipped"] is False

            # Verify parameterization is stored in metadata_json
            row = repo.get_by_mol_id("TestSiO2")
            assert row is not None
            assert row.metadata_json is not None
            assert "parameterization" in row.metadata_json
            param = row.metadata_json["parameterization"]
            assert param["mode"] == "inorganic_profile"
            assert param["profile_id"] == "silica_hydroxylated_v1"
            assert param["status"] == "active"

    def test_sync_preserves_db_on_yaml_parse_error(self, tmp_path):
        """YAML parse error should preserve existing DB state."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from database.models import AdditiveCatalogModel, Base
        from database.repositories.additive_repo import AdditiveRepository

        # Create in-memory SQLite database and pre-populate
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)

        with Session(engine) as session:
            # Pre-populate with an additive
            existing = AdditiveCatalogModel(
                mol_id="ExistingAdditive",
                name="Existing Additive",
                short_name="Exist",
                atom_count=50,
                molecular_weight=500.0,
                category="organic",
                is_active=True,
            )
            session.add(existing)
            session.commit()

            # Create invalid YAML
            yaml_path = tmp_path / "invalid_additives.yaml"
            yaml_path.write_text("invalid: yaml: : content: {[}")

            repo = AdditiveRepository(session)
            result = repo.sync_from_yaml(yaml_path)

            # Should skip sync
            assert result["skipped"] is True

            # Existing data should be preserved
            row = repo.get_by_mol_id("ExistingAdditive")
            assert row is not None
            assert row.is_active is True

    def test_sync_deactivates_removed_additives(self, tmp_path):
        """sync_from_yaml should deactivate additives not in YAML."""
        import yaml
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from database.models import AdditiveCatalogModel, Base
        from database.repositories.additive_repo import AdditiveRepository

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)

        with Session(engine) as session:
            # Pre-populate with two additives
            session.add(
                AdditiveCatalogModel(
                    mol_id="KeepThis",
                    name="Keep This",
                    short_name="Keep",
                    atom_count=10,
                    molecular_weight=100.0,
                    category="organic",
                    is_active=True,
                )
            )
            session.add(
                AdditiveCatalogModel(
                    mol_id="RemoveThis",
                    name="Remove This",
                    short_name="Remove",
                    atom_count=20,
                    molecular_weight=200.0,
                    category="organic",
                    is_active=True,
                )
            )
            session.commit()

            # Create YAML with only KeepThis
            yaml_content = {
                "additives": {
                    "KeepThis": {
                        "name": "Keep This Updated",
                        "short_name": "Keep",
                        "atom_count": 15,
                        "category": "organic",
                    }
                }
            }
            yaml_path = tmp_path / "partial_additives.yaml"
            yaml_path.write_text(yaml.dump(yaml_content))

            repo = AdditiveRepository(session)
            result = repo.sync_from_yaml(yaml_path)
            session.commit()

            assert result["upserted"] == 1
            assert result["deactivated"] == 1

            # KeepThis should be updated and active
            keep = repo.get_by_mol_id("KeepThis")
            assert keep is not None
            assert keep.is_active is True
            assert keep.atom_count == 15

            # RemoveThis should be deactivated
            remove = repo.get_by_mol_id("RemoveThis")
            assert remove is not None
            assert remove.is_active is False


class TestInorganicProfileYAML:
    """Tests for inorganic_profiles.yaml structure."""

    @pytest.fixture
    def profiles_path(self):
        """Get path to inorganic_profiles.yaml."""
        from common.pathing import get_project_root

        return get_project_root() / "data" / "forcefields" / "inorganic_profiles.yaml"

    def test_profiles_file_exists(self, profiles_path):
        """inorganic_profiles.yaml should exist."""
        assert profiles_path.exists()

    def test_silica_profile_structure(self, profiles_path):
        """silica_hydroxylated_v1 should have required structure."""
        import yaml

        with open(profiles_path) as f:
            data = yaml.safe_load(f)

        profile = data["profiles"]["silica_hydroxylated_v1"]

        assert profile["status"] == "active"
        assert "site_rules" in profile
        assert "atom_types" in profile
        assert "bond_types" in profile
        assert "angle_types" in profile
        assert "citations" in profile

        # Check site rules
        assert "Si_tet" in profile["site_rules"]
        assert profile["site_rules"]["Si_tet"]["element"] == "Si"
        assert profile["site_rules"]["Si_tet"]["charge"] == 2.1

        # Check atom types
        assert "Si_tet" in profile["atom_types"]
        assert profile["atom_types"]["Si_tet"]["epsilon"] == pytest.approx(0.00040)

    def test_silica_profile_has_dihedral_policy(self, profiles_path):
        """silica_hydroxylated_v1 should have dihedral_policy in validation."""
        import yaml

        with open(profiles_path) as f:
            data = yaml.safe_load(f)

        profile = data["profiles"]["silica_hydroxylated_v1"]
        validation = profile.get("validation", {})

        assert "dihedral_policy" in validation
        assert validation["dihedral_policy"] == "allow_default_fallback"

    def test_calcite_assign_with_synthetic_topology(self, profiles_path):
        """CaCO3 assignment on minimal synthetic topology."""
        import sys
        from types import SimpleNamespace

        sys.path.insert(0, str(profiles_path.parent.parent.parent / "src"))
        from forcefield.inorganic_parameter_service import InorganicParameterService

        service = InorganicParameterService()

        # Minimal CaCO3 unit: Ca + C + 3*O = 5 atoms
        atoms = [
            SimpleNamespace(
                index=1, element="Ca", x=0, y=0, z=0, ff_type=None, charge=0.0, charge_defined=False
            ),
            SimpleNamespace(
                index=2, element="C", x=1, y=0, z=0, ff_type=None, charge=0.0, charge_defined=False
            ),
            SimpleNamespace(
                index=3, element="O", x=2, y=0, z=0, ff_type=None, charge=0.0, charge_defined=False
            ),
            SimpleNamespace(
                index=4, element="O", x=1, y=1, z=0, ff_type=None, charge=0.0, charge_defined=False
            ),
            SimpleNamespace(
                index=5, element="O", x=1, y=-1, z=0, ff_type=None, charge=0.0, charge_defined=False
            ),
        ]
        bonds = [
            SimpleNamespace(atom1=2, atom2=3, order=1),
            SimpleNamespace(atom1=2, atom2=4, order=1),
            SimpleNamespace(atom1=2, atom2=5, order=1),
            SimpleNamespace(atom1=1, atom2=3, order=1),
            SimpleNamespace(atom1=1, atom2=4, order=1),
            SimpleNamespace(atom1=1, atom2=5, order=1),
        ]
        topo = SimpleNamespace(mol_id="CaCO3", atoms=atoms, bonds=bonds, n_atoms=5, n_bonds=6)

        additive_def = {
            "short_name": "CaCO3",
            "parameterization": {
                "mode": "inorganic_profile",
                "profile_id": "calcite_caco3_v1",
                "status": "active",
            },
        }

        result = service.assign(topo, additive_def)

        # Ca should get Ca_carb type
        ca = [a for a in topo.atoms if a.element == "Ca"]
        assert len(ca) == 1
        assert ca[0].charge_defined is True
        assert ca[0].charge == pytest.approx(2.0)

        # C should get C_carb type
        c = [a for a in topo.atoms if a.element == "C"]
        assert len(c) == 1
        assert c[0].charge_defined is True

        # Total charge ~ neutral
        assert abs(result.total_charge) < 0.1

        # Coefficients
        assert result.atom_type_coeffs
        assert result.bond_type_coeffs

    def test_corundum_assign_with_synthetic_topology(self, profiles_path):
        """Al2O3 assignment on minimal synthetic topology."""
        import sys
        from types import SimpleNamespace

        sys.path.insert(0, str(profiles_path.parent.parent.parent / "src"))
        from forcefield.inorganic_parameter_service import InorganicParameterService

        service = InorganicParameterService()

        # Minimal Al2O3 unit: 2*Al + 3*O = 5 atoms
        atoms = [
            SimpleNamespace(
                index=1, element="Al", x=0, y=0, z=0, ff_type=None, charge=0.0, charge_defined=False
            ),
            SimpleNamespace(
                index=2, element="Al", x=2, y=0, z=0, ff_type=None, charge=0.0, charge_defined=False
            ),
            SimpleNamespace(
                index=3, element="O", x=1, y=0, z=0, ff_type=None, charge=0.0, charge_defined=False
            ),
            SimpleNamespace(
                index=4, element="O", x=0, y=1, z=0, ff_type=None, charge=0.0, charge_defined=False
            ),
            SimpleNamespace(
                index=5, element="O", x=2, y=1, z=0, ff_type=None, charge=0.0, charge_defined=False
            ),
        ]
        bonds = [
            SimpleNamespace(atom1=1, atom2=3, order=1),
            SimpleNamespace(atom1=1, atom2=4, order=1),
            SimpleNamespace(atom1=2, atom2=3, order=1),
            SimpleNamespace(atom1=2, atom2=5, order=1),
        ]
        topo = SimpleNamespace(mol_id="Al2O3", atoms=atoms, bonds=bonds, n_atoms=5, n_bonds=4)

        additive_def = {
            "short_name": "Al2O3",
            "parameterization": {
                "mode": "inorganic_profile",
                "profile_id": "corundum_al2o3_v1",
                "status": "active",
            },
        }

        result = service.assign(topo, additive_def)

        # Al should get charge assigned
        al = [a for a in topo.atoms if a.element == "Al"]
        assert len(al) == 2
        for a in al:
            assert a.charge_defined is True
            assert a.charge == pytest.approx(1.575)

        # Coefficients
        assert result.atom_type_coeffs

    def test_calcite_profile_structure(self, profiles_path):
        """calcite_caco3_v1 should have required structure and correct params."""
        import yaml

        with open(profiles_path) as f:
            data = yaml.safe_load(f)

        profile = data["profiles"]["calcite_caco3_v1"]
        assert profile["status"] == "active"
        assert "site_rules" in profile
        assert "atom_types" in profile
        assert "bond_types" in profile

        # Site rules
        assert "Ca_carb" in profile["site_rules"]
        assert profile["site_rules"]["Ca_carb"]["charge"] == 2.0
        assert "C_carb" in profile["site_rules"]
        assert "O_carb" in profile["site_rules"]

        # LJ from INTERFACE FF (Heinz 2013)
        assert profile["atom_types"]["Ca_carb"]["epsilon"] == pytest.approx(0.100)
        assert profile["atom_types"]["Ca_carb"]["sigma"] == pytest.approx(3.200)
        assert profile["atom_types"]["C_carb"]["epsilon"] == pytest.approx(0.068)

        # Charge neutrality: Ca(+2.0) + C(+1.123) + 3*O(-1.041) = 0 (Raiteri-Gale)
        q = (
            profile["site_rules"]["Ca_carb"]["charge"]
            + profile["site_rules"]["C_carb"]["charge"]
            + 3 * profile["site_rules"]["O_carb"]["charge"]
        )
        assert abs(q) < 0.01, f"CaCO3 charge neutrality failed: {q}"

    def test_corundum_profile_structure(self, profiles_path):
        """corundum_al2o3_v1 should have required structure and correct params."""
        import yaml

        with open(profiles_path) as f:
            data = yaml.safe_load(f)

        profile = data["profiles"]["corundum_al2o3_v1"]
        assert profile["status"] == "active"
        assert "site_rules" in profile
        assert "atom_types" in profile

        # Site rules
        assert "Al_oct" in profile["site_rules"]
        assert profile["site_rules"]["Al_oct"]["charge"] == pytest.approx(1.575)
        assert "O_al" in profile["site_rules"]

        # LJ from INTERFACE FF (Heinz 2013)
        assert profile["atom_types"]["Al_oct"]["epsilon"] == pytest.approx(0.005)
        assert profile["atom_types"]["Al_oct"]["sigma"] == pytest.approx(3.300)

        # Charge neutrality: 2*Al(+1.575) + 3*O(-1.050) = 0
        q = (
            2 * profile["site_rules"]["Al_oct"]["charge"]
            + 3 * profile["site_rules"]["O_al"]["charge"]
        )
        assert abs(q) < 0.01, f"Al2O3 charge neutrality failed: {q}"
