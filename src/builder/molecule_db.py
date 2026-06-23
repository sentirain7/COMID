"""
Molecule database access and management.

Provides access to molecular structures for building simulations.
"""

import json
import re
from pathlib import Path
from typing import Any

import yaml

from builder import binder_catalog, mol_parser, molecule_db_indexing
from builder.mol_types import MolAtom, MolBond, MoleculeRecord, MolTopology  # noqa: F401
from common.pathing import get_project_root
from contracts.schemas import MoleculeCategory, MoleculeInfo, MoleculeSpec


class MoleculeDB:
    """
    Molecule database for accessing molecular structures.

    This class manages the molecule library and provides access
    to molecular information needed for structure building.
    """

    def __init__(self, db_path: Path | None = None):
        """
        Initialize molecule database.

        Args:
            db_path: Path to molecule database directory

        Note:
            YAML is the authoring SSOT for additives; this class loads
            definitions for parameterization lookup. Build-time validation
            should check get_additives_load_error() for fail-closed behavior.
        """
        self.db_path = db_path or (get_project_root() / "molecules")
        self._molecules: dict[str, MoleculeRecord] = {}
        self._additive_defs: dict[str, dict[str, Any]] = {}
        self._additives_load_error: Exception | None = None
        # ff_assignment SSOT (Wave 0): keyed by base_id for SARA/single_moles
        # and by additive_id for additives. get_ff_assignment() resolves full
        # mol_ids (e.g., "U-SA-Squalane-0293") by stripping prefix/temp_code.
        self._ff_assignments: dict[str, dict[str, Any]] = {}
        self._ff_assignment_load_error: Exception | None = None
        self._index_path = self.db_path / "index.json"
        self._load_index()
        self._load_additives_yaml()
        self._load_ff_assignments()

    def _load_index(self) -> None:
        """Load molecule index from disk."""
        if self._index_path.exists():
            with open(self._index_path) as f:
                data = json.load(f)
                for mol_data in data.get("molecules", []):
                    try:
                        spec = MoleculeSpec(**mol_data)
                        self._molecules[spec.mol_id] = MoleculeRecord(spec=spec)
                    except Exception:
                        pass  # Skip invalid entries

    def _load_additives_yaml(self) -> None:
        """Load additive definitions from additives.yaml for parameterization lookup.

        Errors are stored in _additives_load_error for fail-closed validation
        at build time. The builder should check get_additives_load_error()
        before proceeding with additive builds.
        """
        additives_path = get_project_root() / "data" / "molecules" / "additives.yaml"
        if not additives_path.exists():
            self._additives_load_error = FileNotFoundError(
                f"additives.yaml not found: {additives_path}"
            )
            return

        try:
            config = yaml.safe_load(additives_path.read_text())
            if config is None:
                # Empty YAML file is valid (no additives defined)
                return
            additives = config.get("additives", {})
            if additives is None:
                # additives: null is valid (no additives defined)
                return
            for additive_id, additive_def in additives.items():
                if additive_id and additive_def:
                    self._additive_defs[str(additive_id)] = dict(additive_def)
        except Exception as e:
            self._additives_load_error = e

    def _load_ff_assignments(self) -> None:
        """Load ff_assignment metadata from all three molecule SSOT files."""
        self._ff_assignment_load_error = molecule_db_indexing.load_ff_assignments(
            self._ff_assignments
        )

    def _save_index(self) -> None:
        """Save molecule index to disk."""
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"molecules": [rec.spec.model_dump(mode="json") for rec in self._molecules.values()]}
        with open(self._index_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def get(self, mol_id: str) -> MoleculeSpec | None:
        """
        Get molecule specification by ID.

        Args:
            mol_id: Molecule identifier

        Returns:
            MoleculeSpec or None if not found
        """
        record = self._molecules.get(mol_id)
        return record.spec if record else None

    def get_info(self, mol_id: str) -> MoleculeInfo | None:
        """
        Get lightweight molecule info.

        Args:
            mol_id: Molecule identifier

        Returns:
            MoleculeInfo or None if not found
        """
        spec = self.get(mol_id)
        if spec is None:
            return None
        return MoleculeInfo(
            mol_id=spec.mol_id,
            molecular_weight=spec.molecular_weight,
            atom_count=spec.atom_count,
            category=spec.category,
        )

    def get_by_category(self, category: MoleculeCategory) -> list[MoleculeSpec]:
        """
        Get all molecules in a category.

        Args:
            category: Molecule category

        Returns:
            List of matching molecules
        """
        return [rec.spec for rec in self._molecules.values() if rec.spec.category == category]

    def get_structure_file(self, mol_id: str, format: str = "xyz") -> Path | None:
        """
        Get path to structure file for a molecule.

        Args:
            mol_id: Molecule identifier
            format: File format (xyz, mol2, pdb)

        Returns:
            Path to structure file or None
        """
        spec = self.get(mol_id)
        if spec is None:
            return None

        # Check for structure file in molecule directory
        mol_dir = self.db_path / spec.category.value / mol_id

        extensions = {
            "xyz": [".xyz"],
            "mol2": [".mol2"],
            "pdb": [".pdb"],
            "mol": [".mol"],
        }

        for ext in extensions.get(format, [f".{format}"]):
            path = mol_dir / f"{mol_id}{ext}"
            if path.exists():
                return path

        # Fallback to structure_file in spec
        if spec.structure_file:
            path = Path(spec.structure_file)
            if path.exists():
                return path
            project_relative = get_project_root() / "data" / "molecules" / spec.structure_file
            if project_relative.exists():
                return project_relative
            # Try relative to db_path
            path = self.db_path / spec.structure_file
            if path.exists():
                return path

        return None

    def add(self, spec: MoleculeSpec, structure_file: Path | None = None) -> str:
        """
        Add a molecule to the database.

        Args:
            spec: Molecule specification
            structure_file: Optional path to structure file to copy

        Returns:
            Molecule ID
        """
        record = MoleculeRecord(spec=spec)

        if structure_file and structure_file.exists():
            # Copy structure file to molecule directory
            mol_dir = self.db_path / spec.category.value / spec.mol_id
            mol_dir.mkdir(parents=True, exist_ok=True)

            dest = mol_dir / structure_file.name
            import shutil

            shutil.copy2(structure_file, dest)

            # Update spec with new path
            spec.structure_file = str(dest.relative_to(self.db_path))

        self._molecules[spec.mol_id] = record
        self._save_index()
        return spec.mol_id

    def list_all(self) -> list[str]:
        """List all molecule IDs."""
        return list(self._molecules.keys())

    def count(self) -> int:
        """Count total molecules."""
        return len(self._molecules)

    def has(self, mol_id: str) -> bool:
        """Check if molecule exists."""
        return mol_id in self._molecules

    def get_default_molecule(self, category: MoleculeCategory) -> MoleculeSpec | None:
        """
        Get a default/representative molecule for a category.

        Args:
            category: Molecule category

        Returns:
            First molecule in category or None
        """
        molecules = self.get_by_category(category)
        return molecules[0] if molecules else None

    def create_mock_molecules(self) -> None:
        """
        Create mock molecules for testing.

        This creates representative molecules for each SARA category
        with realistic properties.
        """
        mock_molecules = [
            MoleculeSpec(
                mol_id="asphaltene_01",
                smiles="c1ccc2c(c1)ccc3c2ccc4c3cccc4",
                molecular_weight=278.35,
                atom_count=42,
                category=MoleculeCategory.ASPHALTENE,
                structure_file="asphaltene/asphaltene_01/asphaltene_01.xyz",
                topology_hash="mock_asp_001",
                density_ref=1.15,
            ),
            MoleculeSpec(
                mol_id="resin_01",
                smiles="c1ccc2c(c1)ccc3c2cccc3",
                molecular_weight=178.23,
                atom_count=28,
                category=MoleculeCategory.RESIN,
                structure_file="resin/resin_01/resin_01.xyz",
                topology_hash="mock_res_001",
                density_ref=1.05,
            ),
            MoleculeSpec(
                mol_id="aromatic_01",
                smiles="c1ccc2ccccc2c1",
                molecular_weight=128.17,
                atom_count=18,
                category=MoleculeCategory.AROMATIC,
                structure_file="aromatic/aromatic_01/aromatic_01.xyz",
                topology_hash="mock_aro_001",
                density_ref=0.98,
            ),
            MoleculeSpec(
                mol_id="saturate_01",
                smiles="CCCCCCCCCCCCCCCC",
                molecular_weight=226.44,
                atom_count=50,
                category=MoleculeCategory.SATURATE,
                structure_file="saturate/saturate_01/saturate_01.xyz",
                topology_hash="mock_sat_001",
                density_ref=0.78,
            ),
        ]

        for mol in mock_molecules:
            if not self.has(mol.mol_id):
                self._molecules[mol.mol_id] = MoleculeRecord(spec=mol)

        self._save_index()

    # =========================================================================
    # Aging Library Methods — delegate to molecule_db_indexing
    # =========================================================================

    def load_aging_library(self, config_path: Path) -> int:
        """
        Load aging-based molecule library from YAML configuration.

        Args:
            config_path: Path to asphalt_binder.yaml (or combined config path)

        Returns:
            Number of molecules loaded

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If config file is invalid
        """
        count, stored_path = molecule_db_indexing.load_aging_library(
            config_path=config_path,
            molecules=self._molecules,
            additive_defs=self._additive_defs,
        )
        self._aging_config_path = stored_path
        return count

    def load_aging_library_from_config(self, config: dict[str, Any], base_dir: Path) -> int:
        """Load aging/single molecule library from pre-loaded config dict."""
        return molecule_db_indexing.load_aging_library_from_config(
            config=config,
            base_dir=base_dir,
            molecules=self._molecules,
            additive_defs=self._additive_defs,
        )

    def _index_additives_from_config(self, config: dict[str, Any], base_dir: Path) -> int:
        """Index additive molecules defined under config['additives']."""
        return molecule_db_indexing._index_additives_from_config(
            config=config,
            base_dir=base_dir,
            molecules=self._molecules,
            additive_defs=self._additive_defs,
        )

    def _index_explicit_structure_file(
        self,
        mol_def: dict[str, Any],
        structure_file: Path,
        sara_category: str,
        base_dir: Path,
    ) -> int:
        """Index one explicitly configured structure file using base_id as mol_id."""
        return molecule_db_indexing._index_explicit_structure_file(
            mol_def=mol_def,
            structure_file=structure_file,
            sara_category=sara_category,
            base_dir=base_dir,
            molecules=self._molecules,
        )

    def _index_mol_directory(
        self,
        mol_dir: Path,
        mol_def: dict[str, Any],
        aging_key: str,
        prefix: str,
        sara_category: str,
        config: dict[str, Any],
    ) -> int:
        """Index all MOL files in a molecule directory."""
        return molecule_db_indexing._index_mol_directory(
            mol_dir=mol_dir,
            mol_def=mol_def,
            aging_key=aging_key,
            prefix=prefix,
            sara_category=sara_category,
            config=config,
            molecules=self._molecules,
        )

    def _index_mol_files(
        self,
        mol_files: list[Path],
        mol_def: dict[str, Any],
        prefix: str,
        sara_category: str,
        relative_root: Path,
    ) -> int:
        """Index MOL files into MoleculeSpec records."""
        return molecule_db_indexing._index_mol_files(
            mol_files=mol_files,
            mol_def=mol_def,
            prefix=prefix,
            sara_category=sara_category,
            relative_root=relative_root,
            molecules=self._molecules,
        )

    def parse_mol_topology(self, mol_path: Path, mol_id: str = "") -> MolTopology | None:
        """Delegate to mol_parser.parse_mol_topology."""
        return mol_parser.parse_mol_topology(mol_path, mol_id)

    def _parse_mol_v3000(self, lines: list[str], mol_id: str) -> MolTopology | None:
        """Delegate to mol_parser._parse_mol_v3000."""
        return mol_parser._parse_mol_v3000(lines, mol_id)

    def _parse_mol_file(self, mol_path: Path) -> tuple[int, float]:
        """Delegate to mol_parser._parse_mol_file."""
        return mol_parser._parse_mol_file(mol_path)

    def _parse_mol_file_legacy(self, mol_path: Path) -> tuple[int, float]:
        """Delegate to mol_parser._parse_mol_file_legacy."""
        return mol_parser._parse_mol_file_legacy(mol_path)

    def get_topology(self, mol_id: str) -> MolTopology | None:
        """
        Get complete topology for a molecule.

        Args:
            mol_id: Molecule identifier

        Returns:
            MolTopology or None if not found
        """
        record = self._molecules.get(mol_id)
        if record is None:
            return None

        # Check if topology is already cached
        if record.topology is not None:
            return record.topology

        # Try to find and parse MOL file
        mol_path = self.get_structure_file(mol_id, "mol")
        if mol_path is None:
            return None

        topology = self.parse_mol_topology(mol_path, mol_id)
        if topology:
            record.topology = topology

        return topology

    def get_with_fallback(
        self, base_id: str, aging: str, config: dict[str, Any], temp_code: str = "0293"
    ) -> MoleculeSpec | None:
        """
        Get molecule with fallback rules applied.

        Args:
            base_id: Base molecule ID (e.g., "SA-Hopane")
            aging: Aging category (e.g., "short_aging")
            config: Loaded YAML config dict
            temp_code: Temperature code (default: "0293" for 293K at pressure 0)

        Returns:
            MoleculeSpec if found (with fallback), None otherwise
        """
        aging_categories = config.get("aging_categories", {})
        aging_info = aging_categories.get(aging, {})
        prefix = aging_info.get("prefix", "U")

        # Primary lookup: requested aging category
        mol_id = f"{prefix}-{base_id}-{temp_code}"
        mol = self.get(mol_id)

        if mol is not None:
            return mol

        # Fallback lookup
        fallback_aging = aging_info.get("fallback_to")
        if fallback_aging:
            fallback_info = aging_categories.get(fallback_aging, {})
            fallback_prefix = fallback_info.get("prefix", "U")
            fallback_mol_id = f"{fallback_prefix}-{base_id}-{temp_code}"
            mol = self.get(fallback_mol_id)

        return mol

    def get_aging_config(self, config_path: Path) -> dict[str, Any]:
        """
        Load and return aging library configuration.

        Args:
            config_path: Path to asphalt_binder.yaml

        Returns:
            Config dictionary

        Raises:
            FileNotFoundError: If config file doesn't exist
        """
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        return dict(yaml.safe_load(config_path.read_text()))

    def list_by_aging(self, aging: str, config: dict[str, Any]) -> list[str]:
        """
        List all molecule IDs for a specific aging category.

        Args:
            aging: Aging category (non_aging, short_aging, long_aging)
            config: Loaded YAML config dict

        Returns:
            List of molecule IDs
        """
        aging_categories = config.get("aging_categories", {})
        aging_info = aging_categories.get(aging, {})
        prefix = aging_info.get("prefix", "U")

        return [mol_id for mol_id in self._molecules.keys() if mol_id.startswith(f"{prefix}-")]

    def get_structure_file_aging(self, mol_id: str, config_path: Path) -> Path | None:
        """
        Get path to structure file for aging library molecule.

        Args:
            mol_id: Molecule ID (e.g., "U-AS-Thio-0293")
            config_path: Path to asphalt_binder.yaml

        Returns:
            Path to MOL file or None if not found
        """
        spec = self.get(mol_id)
        if spec is None:
            return None

        base_dir = config_path.parent
        structure_path = base_dir / spec.structure_file

        return structure_path if structure_path.exists() else None

    # =========================================================================
    # Binder Composition Methods — delegate to binder_catalog
    # =========================================================================

    def get_binder_composition(
        self, config: dict[str, Any], binder_type: str = "AAA1", size: str = "X1"
    ) -> dict[str, int]:
        """
        Get molecule counts for a specific binder type and structure size.

        Args:
            config: Loaded YAML config dict
            binder_type: Binder type (e.g., "AAA1")
            size: Structure size ("X1", "X2", or "X3")

        Returns:
            Dict mapping mol_id (base_id) to molecule count

        Raises:
            ValueError: If binder_type or size is invalid
        """
        return binder_catalog.get_binder_composition(config, binder_type, size)

    def get_binder_composition_with_aging(
        self,
        config: dict[str, Any],
        binder_type: str = "AAA1",
        size: str = "X1",
        aging: str = "non_aging",
        temp_code: str = "0293",
    ) -> dict[str, int]:
        """
        Get molecule counts with full mol_id including aging prefix and temperature.

        Args:
            config: Loaded YAML config dict
            binder_type: Binder type (e.g., "AAA1")
            size: Structure size ("X1", "X2", or "X3")
            aging: Aging category ("non_aging", "short_aging", "long_aging")
            temp_code: Temperature code (e.g., "0293")

        Returns:
            Dict mapping full mol_id (e.g., "U-AS-Thio-0293") to molecule count
        """
        return binder_catalog.get_binder_composition_with_aging(
            config, binder_type, size, aging, temp_code
        )

    def _find_molecule_def(self, config: dict[str, Any], base_id: str) -> dict[str, Any] | None:
        """Find molecule definition in config by base_id."""
        return binder_catalog._find_molecule_def(config, base_id)

    def get_structure_sizes(self, config: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """
        Get structure size definitions from config.

        Args:
            config: Loaded YAML config dict

        Returns:
            Dict of structure size definitions
        """
        return binder_catalog.get_structure_sizes(config)

    def get_binder_types(self, config: dict[str, Any]) -> list[str]:
        """
        Get list of available binder types.

        Args:
            config: Loaded YAML config dict

        Returns:
            List of binder type names
        """
        return binder_catalog.get_binder_types(config)

    def get_binder_totals(
        self, config: dict[str, Any], binder_type: str = "AAA1"
    ) -> dict[str, int]:
        """
        Get total molecule counts for each structure size.

        Args:
            config: Loaded YAML config dict
            binder_type: Binder type (e.g., "AAA1")

        Returns:
            Dict mapping size to total molecules (e.g., {"X1": 72, "X2": 144, "X3": 216})
        """
        return binder_catalog.get_binder_totals(config, binder_type)

    def get_sara_fractions(
        self, config: dict[str, Any], binder_type: str = "AAA1"
    ) -> dict[str, float]:
        """
        Get SARA weight fractions for a binder type.

        Args:
            config: Loaded YAML config dict
            binder_type: Binder type (e.g., "AAA1")

        Returns:
            Dict mapping SARA category to weight fraction
        """
        return binder_catalog.get_sara_fractions(config, binder_type)

    # =========================================================================
    # Temperature Code Utilities — delegate to binder_catalog
    # =========================================================================

    def get_temperature_code(
        self, config: dict[str, Any], temperature_k: float, pressure_index: int = 0
    ) -> str:
        """
        Convert temperature (K) to temp_code using YAML config (SSOT).

        Args:
            config: Loaded YAML config dict containing temperature_codes
            temperature_k: Temperature in Kelvin (e.g., 298.0)
            pressure_index: Pressure index (0-5), default 0

        Returns:
            Temperature code string (e.g., "0293")
        """
        return binder_catalog.get_temperature_code(config, temperature_k, pressure_index)

    def get_valid_structure_sizes(self, config: dict[str, Any], binder_type: str) -> list[str]:
        """
        Get valid structure sizes for a binder type from YAML config (SSOT).

        Args:
            config: Loaded YAML config dict
            binder_type: Binder type name (e.g., "AAA1")

        Returns:
            List of valid size names (e.g., ["X1", "X2", "X3"])
        """
        return binder_catalog.get_valid_structure_sizes(config, binder_type)

    # =========================================================================
    # SARA Aggregation Methods — delegate to binder_catalog
    # =========================================================================

    def get_binder_composition_by_sara(
        self, config: dict[str, Any], binder_type: str = "AAA1", size: str = "X1"
    ) -> dict[str, int]:
        """
        Get molecule counts aggregated by SARA category.

        Args:
            config: Loaded YAML config dict
            binder_type: Binder type (e.g., "AAA1")
            size: Structure size ("X1", "X2", or "X3")

        Returns:
            Dict mapping SARA category to total molecule count
        """
        return binder_catalog.get_binder_composition_by_sara(config, binder_type, size)

    def get_molecule_atom_count(
        self, config: dict[str, Any], mol_id: str, default: int = 50
    ) -> int:
        """
        Get atom count for a molecule from YAML config (SSOT).

        Args:
            config: Loaded YAML config dict
            mol_id: Base molecule ID (e.g., "SA-Squalane")
            default: Default value if not found

        Returns:
            Atom count from config or default
        """
        return binder_catalog.get_molecule_atom_count(config, mol_id, default)

    def get_molecule_molecular_weight(
        self, config: dict[str, Any], mol_id: str, default: float = 500.0
    ) -> float:
        """
        Get molecular weight for a molecule from YAML config (SSOT).

        Args:
            config: Loaded YAML config dict
            mol_id: Base molecule ID (e.g., "SA-Squalane")
            default: Default value if not found

        Returns:
            Molecular weight from config or default
        """
        return binder_catalog.get_molecule_molecular_weight(config, mol_id, default)

    def get_additive_atom_count(
        self, config: dict[str, Any], additive_id: str, default: int = 50
    ) -> int:
        """
        Get atom count for an additive from YAML config (SSOT).

        Args:
            config: Loaded YAML config dict
            additive_id: Additive ID (e.g., "SiO2", "Lignin")
            default: Default value if not found

        Returns:
            Atom count from config or default
        """
        return binder_catalog.get_additive_atom_count(config, additive_id, default)

    def get_all_molecule_atom_counts(self, config: dict[str, Any]) -> dict[str, int]:
        """
        Get atom counts for all molecules as a dictionary.

        Args:
            config: Loaded YAML config dict

        Returns:
            Dict mapping base_id to atom_count
        """
        return binder_catalog.get_all_molecule_atom_counts(config)

    def calculate_total_atoms(
        self,
        config: dict[str, Any],
        binder_type: str = "AAA1",
        size: str = "X1",
        additives: list[dict[str, Any]] | None = None,
    ) -> int:
        """
        Calculate total estimated atoms for a binder composition.

        Args:
            config: Loaded YAML config dict
            binder_type: Binder type (e.g., "AAA1")
            size: Structure size ("X1", "X2", or "X3")
            additives: Optional list of additives with mol_id and count

        Returns:
            Total estimated atom count
        """
        return binder_catalog.calculate_total_atoms(config, binder_type, size, additives)

    # =========================================================================
    # Additive Parameterization Methods
    # =========================================================================

    def get_additives_load_error(self) -> Exception | None:
        """Return YAML load error if any, for fail-closed decision.

        Builder should check this before proceeding with additive builds.
        If an error exists, the additive build should fail rather than
        proceeding with potentially missing or corrupt parameterization data.

        Returns:
            Exception if YAML loading failed, None if successful.
        """
        return self._additives_load_error

    def get_additive_definition(self, mol_id: str) -> dict[str, Any] | None:
        """
        Get raw additive definition including parameterization.

        Args:
            mol_id: Additive molecule ID (e.g., "SiO2", "NanoClay")

        Returns:
            Complete additive definition dict, or None if not found.
        """
        defn = self._additive_defs.get(mol_id)
        return dict(defn) if defn else None

    def is_additive_blocked(self, mol_id: str) -> bool:
        """
        Check if additive is blocked_placeholder.

        Args:
            mol_id: Additive molecule ID

        Returns:
            True if additive status is blocked_placeholder
        """
        defn = self._additive_defs.get(mol_id, {})
        param = defn.get("parameterization", {})
        return bool(param.get("status") == "blocked_placeholder")

    def get_ff_assignment_load_error(self) -> Exception | None:
        """Return ff_assignment SSOT load error if any (fail-closed check)."""
        return self._ff_assignment_load_error

    def get_ff_assignment(self, mol_id: str) -> dict[str, Any] | None:
        """Resolve the ff_assignment SSOT record for a molecule.

        Wave 0 SSOT: every molecule in asphalt_binder.yaml, single_moles.yaml,
        and additives.yaml must have an ``ff_assignment`` block. This method
        performs three lookups in order:

        1. Direct key lookup (works for additives and single_moles where
           ``mol_id == base_id``).
        2. Stripped SARA mol_id lookup. Binder mol_ids have the form
           ``{prefix}-{base_id}-{temp_code}`` (e.g., ``U-SA-Squalane-0293``).
           The prefix is a single character ``[ULS]`` and the temperature
           code is four digits; the middle segment is the SARA base_id.
        3. ``None`` if neither form is registered.

        Args:
            mol_id: Arbitrary molecule identifier.

        Returns:
            A copy of the ff_assignment dict, or ``None`` if not registered.
        """
        if not mol_id:
            return None

        # Direct lookup for additives / single_moles
        direct = self._ff_assignments.get(mol_id)
        if direct is not None:
            result = dict(direct)
            # Variant-aware source_id derivation for a *base* SARA binder id
            # (e.g., "SA-Squalane" — no aging prefix, no temp code). The
            # "_variant_" sentinel needs an aging prefix to locate the
            # per-variant artifact file; a bare base id carries no aging
            # information, so resolve with the system-wide default aging
            # state (non_aging → "U-"). This matches the amorphous-cell
            # build path, which hardcodes aging_state="non_aging", and the
            # documented Saturate non_aging fallback (the project documentation SARA 노화
            # 상태). Without this, base-id consumers (amorphous cell
            # components) fail the artifact gate even though the U-variant
            # artifact exists.
            if result.get("source_id") == "_variant_" and re.match(
                r"^(SA|AR|RE|AS)-[A-Za-z0-9]+$", mol_id
            ):
                result["source_id"] = f"U-{mol_id}"
            return result

        # Stripped lookup for SARA binder mol_ids (U/S/L prefix + temp code)
        match = re.match(r"^([ULS])-(.+)-(\d{4})$", mol_id)
        if match:
            prefix = match.group(1)
            base_id = match.group(2)
            stripped = self._ff_assignments.get(base_id)
            if stripped is not None:
                result = dict(stripped)
                # Variant-aware source_id derivation: binder aging variants
                # (U/S/L prefix) have distinct topologies and thus distinct
                # GAFF2 artifacts. When the YAML source_id is "_variant_",
                # replace it with the variant identifier (e.g., U-SA-Squalane)
                # so the artifact loader finds the correct per-variant file.
                if result.get("source_id") == "_variant_":
                    result["source_id"] = f"{prefix}-{base_id}"
                return result

        # Also try bare mol_id without temp_code (e.g., "U-SA-Squalane")
        match_bare = re.match(r"^([ULS])-(.+)$", mol_id)
        if match_bare:
            prefix = match_bare.group(1)
            base_id = match_bare.group(2)
            stripped = self._ff_assignments.get(base_id)
            if stripped is not None:
                result = dict(stripped)
                if result.get("source_id") == "_variant_":
                    result["source_id"] = f"{prefix}-{base_id}"
                return result

        return None
