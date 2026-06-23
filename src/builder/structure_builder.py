"""
Main structure builder implementing IStructureBuilder interface.

Orchestrates the structure building process from composition
specification to LAMMPS data file.
"""

import hashlib
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TypeAlias

from common.hashing import compute_file_hash
from common.logging import get_logger
from common.units import volume_to_density
from config.settings import get_settings
from contracts.errors import BuildError, ErrorCode
from contracts.interfaces import AbstractStructureBuilder
from contracts.schemas import (
    BuildRequest,
    BuildResult,
    MoleculeCategory,
    MoleculeInfo,
)
from forcefield.organic_typing_executor import normalize_ff_name

from .build_throttle import build_slot
from .composition_calculator import CompositionCalculator
from .molecule_db import MoleculeDB, MolTopology
from .packing_validator import PackingValidator
from .packmol_wrapper import PackmolMolecule, PackmolWrapper
from .topology_assembly import generate_full_topology
from .topology_generator import TopologyGenerator
from .topology_helpers import (
    create_mock_molecule,
    create_mock_structure,
    create_xyz_topology,
    find_mol_file,
    parse_xyz_coordinates,
)

logger = get_logger("builder.structure_builder")

MoleculeOrderingEntry: TypeAlias = dict[str, str | int]

# 패킹 게이트 재시도 정책 — 비수렴/결함 패킹 시 seed 변경 후 재패킹(관통은 새
# 무작위 배치로만 탈출). 지속 실패 시 밀도를 낮춰(여유 공간↑) 재시도; ρ≤0.1은
# 거의 100% 청정이라 수렴 보장(docs/architecture/packmol-structure-generation-quality.md).
_PACK_SEEDS_PER_DENSITY = 3
_PACK_DENSITY_ESCALATION: tuple[float, ...] = (0.3, 0.2, 0.1)

# 스윕 실증(상동 문서 §5)의 **일반·안전한** 적용. 지배적 레버인 초기 밀도만
# 전역 적용: 패킹에만 영향(NPT가 평형 밀도로 압축 → 최종 물리 불변)하고, 낮은
# 밀도는 임의 시스템에서 packing을 feasible하게 해 maxit과 무관히 빠르게 수렴시킨다
# (고밀도 grinding의 근본 해소). tolerance/maxit은 시스템 의존적이라 전역 강제하지
# 않고 PackmolWrapper 표준 기본값(2.0/2000)을 유지 — 작은/빽빽한 시스템서 tol↑가
# 제약 과다로 미수렴(timeout)을 유발하기 때문.
_PACK_RECOMMENDED_DENSITY = 0.2


class StructureBuilder(AbstractStructureBuilder):
    """
    Main structure builder for generating molecular systems.

    Implements the IStructureBuilder interface and orchestrates
    the complete build process.
    """

    def __init__(
        self,
        molecule_db: MoleculeDB | None = None,
        packmol_path: str = "packmol",
        ff_name: str = "GAFF2",
        ff_version: str = "1.0",
        work_dir: Path | None = None,
    ):
        """
        Initialize structure builder.

        Args:
            molecule_db: Molecule database (creates default if None)
            packmol_path: Path to Packmol executable
            ff_name: Force field name
            ff_version: Force field version
            work_dir: Working directory for builds
        """
        self.molecule_db = molecule_db or MoleculeDB()
        # tolerance/maxit은 PackmolWrapper 표준 기본값(2.0/2000) 유지 — 밀도 레버 +
        # 재시도가 청정율을 책임지므로 전역 강제 불필요(시스템 의존적 위험 회피).
        self.packmol = PackmolWrapper(packmol_path=packmol_path)
        self.calculator = CompositionCalculator()
        self.topology_gen = TopologyGenerator(ff_name, ff_version)
        # 검증 임계 = 0.9×tolerance — Packmol tolerance에 묶인 튜닝불요 백업(매직넘버
        # 아님). 정상 패킹(분자간 ≥tolerance)은 통과, 관통(0.6~1.1 Å)은 거부.
        self.validator = PackingValidator(min_distance=0.9 * self.packmol.tolerance)
        self.work_dir = work_dir
        self.ff_name = ff_name
        self.ff_version = ff_version
        self._ff_registry_name = normalize_ff_name(ff_name)

        app_settings = get_settings()
        self.typing_charge_settings = app_settings.typing_charge
        self._progress_callback: Callable[[str, str | None], None] | None = None

    def set_progress_callback(self, callback: Callable[[str, str | None], None] | None) -> None:
        """Register optional progress callback.

        The callback receives ``(status, label)`` where ``status`` is a
        coarse code (e.g. ``"packing_molecules"``) and ``label`` is an
        optional fine-grained human-readable string. When ``label`` is
        ``None`` the caller should fall back to a status→label mapping.
        """
        self._progress_callback = callback

    def _emit_progress(self, status: str, label: str | None = None) -> None:
        """Emit best-effort progress update. Always calls the callback with
        ``(status, label)`` — registered callbacks must accept both args.
        """
        if self._progress_callback is None:
            return
        try:
            self._progress_callback(status, label)
        except Exception as exc:
            logger.debug(f"Progress callback failed for status={status}: {exc}")

    def build(self, request: BuildRequest) -> BuildResult:
        """
        Build molecular structure from composition specification.

        Args:
            request: Build request with composition and parameters

        Returns:
            BuildResult with data file and quality metrics
        """
        logger.info(f"Starting build: {request.target_atoms} atoms, seed={request.seed}")
        self._emit_progress("building_structure")

        # Optional fast path for layered-structure prebuilt systems.
        if request.prebuilt_data_file_path:
            return self._build_from_prebuilt_data(request)

        # Check composition mode
        composition_mode = getattr(request, "composition_mode", "wt_percent")

        if composition_mode == "mol_count":
            # New mode: mol_id → count dict (individual molecules)
            logger.info("Using mol_count mode for direct molecule counts")
            return self._build_from_mol_counts(request)

        # Legacy mode: SARA wt% → representative molecules
        # Get molecules for each category
        molecules = self._get_molecules_for_composition(request.composition)

        # Calculate molecule counts
        comp_result = self.calculator.calculate(
            target_wt=request.composition,
            molecules=molecules,
            target_atoms=request.target_atoms,
            tolerance=request.atom_count_tolerance,
        )

        logger.info(f"Composition: error_l1={comp_result.error_l1:.4f} wt%")

        # Create work directory
        work_dir = self._get_work_dir(request)
        work_dir.mkdir(parents=True, exist_ok=True)

        # Get structure files for Packmol
        packmol_molecules = self._prepare_packmol_input(comp_result.mol_counts, molecules, work_dir)

        # Pack + topology + validate with fail-close gate (Packmol 수렴 존중 +
        # change_seed/밀도 에스컬레이션 재시도).
        self._emit_progress("packing_molecules")
        self._emit_progress("assigning_types_charges")
        # Cross-process build throttle: caps concurrent Packmol builds (CPU/RAM
        # bound) so a large batch sharing the worker pool can't exhaust the host.
        with build_slot():
            data_file, topo_hash, effective_box, validation = self._pack_validate_retry(
                packmol_molecules=packmol_molecules,
                mol_counts=comp_result.mol_counts,
                molecules=molecules,
                total_mass=comp_result.total_mass,
                request=request,
                work_dir=work_dir,
            )

        # Get actual atom count and calculate density using SSOT
        actual_atoms = self.topology_gen.get_atom_count(data_file)
        box_volume = self.topology_gen.get_box_volume(data_file)
        n_molecules = sum(comp_result.mol_counts.values())
        actual_density = self._calculate_density(comp_result.total_mass, n_molecules, box_volume)

        # Build molecule ordering metadata for group assignment (Phase 4.2)
        molecule_ordering: list[MoleculeOrderingEntry] = []
        for category, count in comp_result.mol_counts.items():
            if count <= 0:
                continue
            mol_info = molecules.get(category)
            if mol_info:
                molecule_ordering.append(
                    {
                        "mol_id": mol_info.mol_id,
                        "count": count,
                        "category": mol_info.category.value,
                        "atom_count": mol_info.atom_count,
                    }
                )

        return BuildResult(
            data_file_path=str(data_file),
            actual_atoms=actual_atoms,
            actual_density=actual_density,
            topology_hash=topo_hash,
            packmol_version=self.packmol.get_version() or "unknown",
            actual_composition_wt=comp_result.actual_wt,
            composition_error_l1=comp_result.error_l1,
            target_composition_wt=comp_result.target_wt,
            min_distance_violation_count=validation.min_distance_violations,
            initial_pe_per_atom=validation.estimated_pe_per_atom,
            stability_flag=validation.stability_flag,
            molecule_ordering=molecule_ordering if molecule_ordering else None,
        )

    def _build_from_prebuilt_data(self, request: BuildRequest) -> BuildResult:
        """BuildResult adapter for externally prepared LAMMPS data files."""
        data_file = Path(str(request.prebuilt_data_file_path))
        if not data_file.exists():
            raise BuildError(
                code=ErrorCode.STRUCTURE_NOT_FOUND,
                message=f"Prebuilt data file not found: {data_file}",
            )

        try:
            actual_atoms = self.topology_gen.get_atom_count(data_file)
            box_volume = self.topology_gen.get_box_volume(data_file)
        except Exception as exc:
            raise BuildError(
                code=ErrorCode.TOPOLOGY_GENERATION_FAILED,
                message=f"Failed to parse prebuilt data file: {exc}",
                details={"data_file": str(data_file)},
            ) from exc

        density_guess = request.initial_density
        if box_volume and box_volume > 0 and request.composition:
            # Keep deterministic and simple: use request.initial_density as effective value.
            density_guess = float(request.initial_density)

        topology_hash = compute_file_hash(data_file)[:16]
        composition = request.composition or {
            "asphaltene": 20.0,
            "resin": 30.0,
            "aromatic": 35.0,
            "saturate": 15.0,
        }

        return BuildResult(
            data_file_path=str(data_file),
            actual_atoms=int(actual_atoms),
            actual_density=float(density_guess),
            topology_hash=topology_hash,
            packmol_version="prebuilt",
            actual_composition_wt={k: float(v) for k, v in composition.items()},
            composition_error_l1=0.0,
            target_composition_wt={k: float(v) for k, v in composition.items()},
            min_distance_violation_count=0,
            initial_pe_per_atom=0.0,
            stability_flag="prebuilt",
            molecule_ordering=None,
        )

    def validate_packing(self, data_file_path: str) -> dict:
        """
        Validate packing quality of a LAMMPS data file.

        Args:
            data_file_path: Path to LAMMPS data file

        Returns:
            Dictionary with validation results
        """
        result = self.validator.validate(Path(data_file_path))
        return {
            "valid": result.valid,
            "min_distance": result.min_distance,
            "min_distance_violations": result.min_distance_violations,
            "overlap_pairs": result.overlap_pairs,
            "estimated_pe_per_atom": result.estimated_pe_per_atom,
            "stability_flag": result.stability_flag,
            "message": result.message,
        }

    def _get_molecules_for_composition(
        self,
        composition: dict[str, float],
    ) -> dict[str, MoleculeInfo]:
        """Get representative molecules for each category in composition."""
        molecules = {}

        for category_name in composition:
            # Try to parse as MoleculeCategory
            try:
                category = MoleculeCategory(category_name)
            except ValueError:
                # Handle additive categories
                if category_name.startswith("additive"):
                    category = MoleculeCategory.ADDITIVE
                else:
                    logger.warning(f"Unknown category: {category_name}")
                    continue

            # Get a representative molecule for this category
            mol_spec = self.molecule_db.get_default_molecule(category)

            if mol_spec is None:
                # Create mock molecule for testing
                logger.warning(f"No molecule found for {category_name}, using mock")
                molecules[category_name] = self._create_mock_molecule(category_name)
            else:
                molecules[category_name] = MoleculeInfo(
                    mol_id=mol_spec.mol_id,
                    molecular_weight=mol_spec.molecular_weight,
                    atom_count=mol_spec.atom_count,
                    category=mol_spec.category,
                )

        return molecules

    def _create_mock_molecule(self, category_name: str) -> MoleculeInfo:
        """Create a mock molecule for testing.

        Delegates to :func:`topology_helpers.create_mock_molecule`.
        """
        return create_mock_molecule(category_name)

    def _build_from_mol_counts(self, request: BuildRequest) -> BuildResult:
        """
        Build structure using individual molecule counts (mol_count mode).

        This method uses actual mol_id → count mapping instead of SARA wt%.
        It loads real molecules from the aging library.

        Args:
            request: BuildRequest with composition as {mol_id: count}

        Returns:
            BuildResult with data file and quality metrics
        """

        # Convert composition to mol_counts (float → int)
        mol_counts = {k: int(v) for k, v in request.composition.items()}

        logger.info(f"Building from mol_counts: {len(mol_counts)} molecule types")

        # Get MoleculeInfo for each mol_id
        molecules: dict[str, MoleculeInfo] = {}
        total_mass = 0.0
        total_atoms = 0
        total_molecules = 0

        for mol_id, count in mol_counts.items():
            if count <= 0:
                continue

            mol_info = self.molecule_db.get_info(mol_id)
            if mol_info:
                molecules[mol_id] = mol_info
                total_mass += mol_info.molecular_weight * count
                total_atoms += mol_info.atom_count * count
                total_molecules += count
                logger.info(
                    f"Found molecule {mol_id}: {mol_info.atom_count} atoms, mw={mol_info.molecular_weight:.2f}"
                )
            else:
                logger.warning(f"Molecule {mol_id} not found in MoleculeDB")

        if not molecules:
            raise BuildError(
                code=ErrorCode.MOLECULE_NOT_FOUND,
                message=(
                    f"No molecules found in MoleculeDB for {list(mol_counts.keys())}. "
                    "Check if load_aging_library() was called."
                ),
                details={"requested_mol_ids": list(mol_counts.keys())},
            )

        logger.info(f"Loaded {len(molecules)} molecule types, total atoms estimate: {total_atoms}")

        # Create work directory
        work_dir = self._get_work_dir(request)
        work_dir.mkdir(parents=True, exist_ok=True)

        # Prepare Packmol input with actual structure files
        packmol_molecules = self._prepare_packmol_input_mol_count(mol_counts, molecules, work_dir)

        if not packmol_molecules:
            raise BuildError(
                code=ErrorCode.MOLECULE_NOT_FOUND,
                message="No valid molecules prepared for Packmol",
            )

        # Pack + topology + validate with fail-close gate (Packmol 수렴 존중 +
        # change_seed/밀도 에스컬레이션 재시도).
        self._emit_progress("packing_molecules")
        self._emit_progress("assigning_types_charges")
        # Cross-process build throttle (see build() — same CPU/RAM rationale).
        with build_slot():
            data_file, topo_hash, effective_box, validation = self._pack_validate_retry(
                packmol_molecules=packmol_molecules,
                mol_counts=mol_counts,
                molecules=molecules,
                total_mass=total_mass,
                request=request,
                work_dir=work_dir,
            )

        # Get actual atom count and calculate density using SSOT
        actual_atoms = self.topology_gen.get_atom_count(data_file)
        box_volume = self.topology_gen.get_box_volume(data_file)
        actual_density = self._calculate_density(total_mass, total_molecules, box_volume)

        # Calculate actual composition wt%
        actual_composition_wt = {}
        for mol_id, count in mol_counts.items():
            if mol_id in molecules:
                wt = (
                    molecules[mol_id].molecular_weight * count / total_mass * 100
                    if total_mass > 0
                    else 0.0
                )
                actual_composition_wt[mol_id] = wt

        logger.info(f"Build complete: {actual_atoms} atoms, density={actual_density:.3f} g/cm3")

        # Build molecule ordering metadata for group assignment (Phase 4.2)
        molecule_ordering: list[MoleculeOrderingEntry] = []
        for mol_id, count in mol_counts.items():
            if count <= 0 or mol_id not in molecules:
                continue
            mol_info = molecules[mol_id]
            molecule_ordering.append(
                {
                    "mol_id": mol_id,
                    "count": count,
                    "category": mol_info.category.value,
                    "atom_count": mol_info.atom_count,
                }
            )

        return BuildResult(
            data_file_path=str(data_file),
            actual_atoms=actual_atoms,
            actual_density=actual_density,
            topology_hash=topo_hash,
            packmol_version=self.packmol.get_version() or "unknown",
            actual_composition_wt=actual_composition_wt,
            composition_error_l1=0.0,  # No error for mol_count mode
            target_composition_wt=request.composition,
            min_distance_violation_count=validation.min_distance_violations,
            initial_pe_per_atom=validation.estimated_pe_per_atom,
            stability_flag=validation.stability_flag,
            molecule_ordering=molecule_ordering if molecule_ordering else None,
        )

    def _convert_mol_to_xyz(self, mol_file: Path, output_file: Path, mol_id: str) -> Path:
        """Convert MOL file to XYZ format for Packmol compatibility.

        Delegates to :func:`topology_helpers.convert_mol_to_xyz` after
        parsing the MOL file via :class:`MoleculeDB`.

        Args:
            mol_file: Source MOL file path
            output_file: Destination XYZ file path
            mol_id: Molecule ID for logging

        Returns:
            Path to converted XYZ file

        Raises:
            BuildError: If MOL file parsing fails
        """
        from .topology_helpers import convert_mol_to_xyz

        topology = self.molecule_db.parse_mol_topology(mol_file, mol_id)

        if topology is None or not topology.atoms:
            raise BuildError(
                code=ErrorCode.PACKMOL_FAILED,
                message=f"Failed to parse MOL file for {mol_id}: {mol_file}",
                details={"mol_file": str(mol_file)},
            )

        return convert_mol_to_xyz(topology, mol_id, output_file)

    def _prepare_packmol_input_mol_count(
        self,
        mol_counts: dict[str, int],
        molecules: dict[str, MoleculeInfo],
        work_dir: Path,
    ) -> list[PackmolMolecule]:
        """
        Prepare Packmol input for mol_count mode using actual structure files.

        Args:
            mol_counts: mol_id → count mapping
            molecules: mol_id → MoleculeInfo mapping
            work_dir: Working directory for temp files

        Returns:
            List of PackmolMolecule with structure files
        """
        packmol_molecules = []
        config_path = getattr(self.molecule_db, "_aging_config_path", None)

        for mol_id, count in mol_counts.items():
            if count <= 0 or mol_id not in molecules:
                continue

            mol_info = molecules[mol_id]
            structure_file = None

            # Try aging library first
            if config_path:
                aging_file = self.molecule_db.get_structure_file_aging(mol_id, config_path)
                if aging_file and aging_file.exists():
                    # Check if MOL file needs conversion to XYZ for Packmol
                    if aging_file.suffix.lower() == ".mol":
                        # Convert MOL to XYZ for Packmol compatibility
                        xyz_file = work_dir / f"{mol_id.replace('-', '_')}.xyz"
                        structure_file = self._convert_mol_to_xyz(aging_file, xyz_file, mol_id)
                        logger.info(f"Converted aging library MOL to XYZ for {mol_id}")
                    else:
                        # Already XYZ or PDB format
                        structure_file = aging_file
                        logger.info(f"Using aging library structure for {mol_id}: {structure_file}")

            # Track original MOL file for topology generation
            original_mol_file = (
                aging_file
                if (aging_file and aging_file.exists() and aging_file.suffix.lower() == ".mol")
                else None
            )

            # Fallback to standard lookup (XYZ)
            if structure_file is None or not structure_file.exists():
                structure_file = self.molecule_db.get_structure_file(mol_id, "xyz")
                if structure_file and structure_file.exists():
                    logger.info(f"Using standard structure for {mol_id}: {structure_file}")

            # Create mock if still not found (development fallback)
            if structure_file is None or not structure_file.exists():
                logger.warning(f"Creating mock structure for {mol_id} (no structure file found)")
                structure_file = self._create_mock_structure(
                    mol_info, work_dir / f"{mol_id.replace('-', '_')}.xyz"
                )

            packmol_molecules.append(
                PackmolMolecule(
                    structure_file=structure_file,
                    count=count,
                    mol_id=mol_id,
                    original_mol_file=original_mol_file,  # Preserve original MOL for topology
                )
            )

        return packmol_molecules

    def _prepare_packmol_input(
        self,
        mol_counts: dict[str, int],
        molecules: dict[str, MoleculeInfo],
        work_dir: Path,
    ) -> list[PackmolMolecule]:
        """Prepare Packmol molecule list with structure files."""
        packmol_molecules = []

        for category, count in mol_counts.items():
            if count <= 0:
                continue

            mol_info = molecules.get(category)
            if mol_info is None:
                continue

            # Try to get structure file
            structure_file = self.molecule_db.get_structure_file(mol_info.mol_id, "xyz")

            if structure_file is None or not structure_file.exists():
                # Create mock structure file
                structure_file = self._create_mock_structure(mol_info, work_dir / f"{category}.xyz")

            packmol_molecules.append(
                PackmolMolecule(
                    structure_file=structure_file,
                    count=count,
                    mol_id=mol_info.mol_id,
                )
            )

        return packmol_molecules

    def _create_mock_structure(
        self,
        mol_info: MoleculeInfo,
        output_file: Path,
    ) -> Path:
        """Create a mock XYZ structure file for testing.

        Delegates to :func:`topology_helpers.create_mock_structure`.
        """
        return create_mock_structure(mol_info.mol_id, mol_info.atom_count, output_file)

    def _get_work_dir(self, request: BuildRequest) -> Path:
        """Get working directory for build.

        If work_dir is set (permanent storage), create/use a seed-scoped
        subdirectory to prevent overwriting outputs from different seeds.
        Otherwise, create a temp directory.
        """
        if self.work_dir:
            seed_dir = self.work_dir / f"seed_{request.seed}"
            seed_dir.mkdir(parents=True, exist_ok=True)
            return seed_dir

        # Use temp directory for development/testing
        return Path(tempfile.mkdtemp(prefix=f"build_{request.seed}_"))

    def _calculate_density(
        self,
        total_mass: float,
        n_molecules: int,
        box_volume: float,
    ) -> float:
        """Calculate density from mass and volume using common/units.py (SSOT).

        Args:
            total_mass: Sum of (molecular_weight * count) in g/mol
            n_molecules: Total number of molecules
            box_volume: Volume in Angstrom^3

        Returns:
            Density in g/cm3
        """
        if box_volume <= 0:
            logger.warning("Invalid box volume, returning default density 1.0")
            return 1.0

        if n_molecules <= 0:
            logger.warning("Invalid molecule count, returning default density 1.0")
            return 1.0

        # Use SSOT function from common/units.py
        # volume_to_density expects average mass per molecule
        avg_mass_per_mol = total_mass / n_molecules
        density = volume_to_density(avg_mass_per_mol, n_molecules, box_volume)

        # Sanity check: asphalt typically 0.9-1.2 g/cm3
        if density < 0.5 or density > 2.0:
            logger.warning(f"Unusual density calculated: {density:.3f} g/cm3")

        return density

    def _derive_pack_seed(self, mol_counts: dict[str, int], attempt: int) -> int:
        """Deterministic-but-varying Packmol seed for a retry attempt.

        A fixed seed reproduces the same (possibly threaded) packing — the
        original defect's root cause. This derives a stable per-composition
        base (process-independent via hashlib) and offsets it per attempt so
        each retry re-places molecules from a different random start.

        Args:
            mol_counts: Composition, for a stable per-composition base.
            attempt: 1-based attempt index.

        Returns:
            Positive integer Packmol seed.
        """
        key = ",".join(f"{k}:{int(v)}" for k, v in sorted(mol_counts.items()))
        base = int(hashlib.md5(key.encode()).hexdigest()[:8], 16)
        return 1 + (base + attempt * 104729) % 2_000_000_000

    def _pack_validate_retry(
        self,
        *,
        packmol_molecules: list[PackmolMolecule],
        mol_counts: dict[str, int],
        molecules: dict[str, MoleculeInfo],
        total_mass: float,
        request: BuildRequest,
        work_dir: Path,
    ) -> tuple[Path, str, tuple[float, float, float] | None, object]:
        """Pack → topology → validate with a fail-close defect gate.

        Primary gate is Packmol's own convergence report (``converged``: all
        inter-molecular atom pairs >= ``tolerance``, a molecule-agnostic
        guarantee of no overlap/threading when tolerance >= ring radius). The
        molecule-aware distance validator is a tuning-free backup. On a
        defective/non-converged pack it retries with a new seed; after
        ``_PACK_SEEDS_PER_DENSITY`` failures at a density it escalates to a
        lower density (more free volume). Raises ``BuildError`` if no
        defect-free packing is found.

        Returns:
            ``(data_file, topo_hash, effective_box, validation)``.
        """
        xyz_file = work_dir / "packed.xyz"
        data_file = work_dir / "data.lammps"
        # 명시 box면 밀도 에스컬레이션 불가(box 고정) → seed만 변경.
        if request.box_dimensions is not None:
            density_schedule: list[float | None] = [None]
        else:
            # 권장 패킹 밀도로 시작(요청이 더 낮으면 존중) → 낮은 밀도로 에스컬레이션.
            start = min(request.initial_density, _PACK_RECOMMENDED_DENSITY)
            density_schedule = [start] + [d for d in _PACK_DENSITY_ESCALATION if d < start]

        attempt = 0
        last_reason = "no packing attempt made"
        for density in density_schedule:
            for _ in range(_PACK_SEEDS_PER_DENSITY):
                attempt += 1
                self.packmol.seed = self._derive_pack_seed(mol_counts, attempt)
                packmol_result = self.packmol.pack(
                    molecules=packmol_molecules,
                    output_file=xyz_file,
                    total_mass_g_mol=total_mass,
                    box_dimensions=request.box_dimensions,
                    density=(density if density is not None else request.initial_density),
                    work_dir=work_dir,
                )
                if not packmol_result.success:
                    last_reason = f"packmol failed: {packmol_result.error_message}"
                    is_timeout = "timeout" in (packmol_result.error_message or "").lower()
                    logger.warning("Pack attempt %d: %s — retrying", attempt, last_reason)
                    # timeout = 이 밀도가 grinding(infeasible) → 같은 밀도 재시도 무의미.
                    # 다음(낮은) 밀도로 즉시 에스컬레이션.
                    if is_timeout:
                        break
                    continue
                # 0순위: Packmol 자기 보고 존중 — 비수렴 = 분자 겹침/관통.
                if not packmol_result.converged:
                    last_reason = (
                        "packmol did not converge "
                        f"(violation={packmol_result.max_constraint_violation})"
                    )
                    logger.warning(
                        "Pack attempt %d (ρ=%s, seed=%d): %s — retrying",
                        attempt,
                        density,
                        self.packmol.seed,
                        last_reason,
                    )
                    continue
                effective_box = packmol_result.box_dimensions or request.box_dimensions
                data_file, topo_hash = self._generate_full_topology(
                    packmol_molecules=packmol_molecules,
                    packed_xyz=xyz_file,
                    mol_counts=mol_counts,
                    molecules=molecules,
                    output_file=data_file,
                    box_dimensions=effective_box,
                )
                # ① 백업: 분자간 거리 독립 재확인(tolerance 기준, 매직넘버 없음).
                validation = self.validator.validate(data_file)
                if validation.valid:
                    if attempt > 1:
                        logger.info("Defect-free packing on attempt %d (ρ=%s)", attempt, density)
                    return data_file, topo_hash, effective_box, validation
                last_reason = f"packing defect: {validation.message}"
                logger.warning(
                    "Pack attempt %d (ρ=%s): %s — retrying", attempt, density, last_reason
                )

        raise BuildError(
            code=ErrorCode.PACKMOL_FAILED,
            message=(
                f"Could not produce a defect-free packing after {attempt} attempts "
                f"(seed/density escalation exhausted); last: {last_reason}"
            ),
            details={"attempts": attempt, "last_reason": last_reason},
        )

    def _generate_full_topology(
        self,
        packmol_molecules: list[PackmolMolecule],
        packed_xyz: Path,
        mol_counts: dict[str, int],
        molecules: dict[str, MoleculeInfo],
        output_file: Path,
        box_dimensions: tuple[float, float, float] | None = None,
    ) -> tuple[Path, str]:
        """Generate LAMMPS data file with full topology (bonds, angles, dihedrals).

        Delegates to :func:`topology_assembly.generate_full_topology`.

        Args:
            packmol_molecules: List of PackmolMolecule with structure files
            packed_xyz: Path to Packmol output XYZ file
            mol_counts: Molecule counts by category
            molecules: Molecule info dictionary
            output_file: Output LAMMPS data file path
            box_dimensions: Optional explicit box dimensions

        Returns:
            Tuple of (output path, topology hash)
        """
        return generate_full_topology(
            packmol_molecules=packmol_molecules,
            packed_xyz=packed_xyz,
            mol_counts=mol_counts,
            molecules=molecules,
            output_file=output_file,
            box_dimensions=box_dimensions,
            molecule_db=self.molecule_db,
            ff_name=self.ff_name,
            ff_version=self.ff_version,
            ff_registry_name=self._ff_registry_name,
            typing_charge_settings=self.typing_charge_settings,
            emit_progress=self._emit_progress,
        )

    def _parse_xyz_coordinates(self, xyz_file: Path) -> list[tuple[float, float, float]]:
        """Parse coordinates from XYZ file.

        Delegates to :func:`topology_helpers.parse_xyz_coordinates`.
        """
        return parse_xyz_coordinates(xyz_file)

    def _find_mol_file(self, structure_file: Path, mol_id: str = "") -> Path | None:
        """Find corresponding MOL file for a structure file.

        Delegates to :func:`topology_helpers.find_mol_file`.

        Args:
            structure_file: Path to structure file (XYZ, PDB, etc.)
            mol_id: Molecule ID for aging library lookup

        Returns:
            Path to MOL file or None if not found
        """
        return find_mol_file(structure_file, mol_id, self.molecule_db)

    def _create_xyz_topology(self, pm_mol: PackmolMolecule, mol_id: str) -> MolTopology:
        """Create basic topology from XYZ file (no bonds).

        Delegates to :func:`topology_helpers.create_xyz_topology`.
        """
        return create_xyz_topology(pm_mol.structure_file, mol_id)


# Export main class
__all__ = ["StructureBuilder"]
