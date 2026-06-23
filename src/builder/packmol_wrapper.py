"""
Packmol wrapper for molecular packing.

Provides a Python interface to Packmol for generating
initial molecular configurations.
"""

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from common.logging import get_logger

logger = get_logger("builder.packmol")


@dataclass
class PackmolMolecule:
    """Molecule specification for Packmol input."""

    structure_file: Path
    count: int
    mol_id: str
    original_mol_file: Path | None = None  # Original MOL file path for topology


@dataclass
class PackmolResult:
    """Result from Packmol execution."""

    success: bool
    output_file: Path
    log: str
    error_message: str | None = None
    box_dimensions: tuple[float, float, float] | None = None  # Packmol box for LAMMPS
    containment_feasible: bool = True  # False when molecule too large for strict containment
    # Packmol 자기 보고 — 거리 제약을 실제 달성했는지(수렴). success(출력 생성)와
    # 구분: 비수렴 출력은 분자 겹침/관통을 품으므로 빌드 게이트가 거부해야 함.
    converged: bool = True
    max_constraint_violation: float | None = None  # Packmol 최종 제약 위반량(0=청정)


def _parse_packmol_convergence(stdout: str) -> tuple[bool, float | None]:
    """Parse Packmol's self-reported convergence from stdout.

    Packmol reports ``Success!`` and ``Maximum violation of the constraints``
    when all inter-molecular atom pairs satisfy the distance ``tolerance``.
    A non-converged run prints ``STOP`` (GENCAN loops exhausted) without
    ``Success!`` and a non-zero violation.

    Because a bond can only pierce an aromatic ring (radius < tolerance) by
    bringing atoms closer than ``tolerance``, convergence here is a
    molecule-agnostic, tuning-free guarantee of "no inter-molecular overlap
    or threading" — provided ``tolerance`` >= max ring radius (~1.5 Å).

    Args:
        stdout: Packmol process stdout.

    Returns:
        ``(converged, max_constraint_violation)``. The violation is the last
        reported value (final state); ``None`` if not parseable.
    """
    max_viol: float | None = None
    for line in stdout.splitlines():
        if "Maximum violation of the constraints" in line:
            try:
                max_viol = float(line.split(":")[-1].strip())
            except ValueError:
                continue
    # ``Success!`` 토큰이 1차 신호이나, 수렴했는데도(위반량→0) loop 소진으로 exit≠0/
    # 토큰 누락인 경우가 있다 — 정량 위반량(≈0)도 수렴으로 인정(보수적 epsilon).
    converged = ("Success!" in stdout) or (
        max_viol is not None and max_viol < 1e-4
    )
    return converged, max_viol


class PackmolWrapper:
    """
    Wrapper for Packmol molecular packing tool.

    Generates Packmol input files and runs the packing process
    to create initial molecular configurations.
    """

    def __init__(
        self,
        packmol_path: str = "packmol",
        tolerance: float = 2.0,
        seed: int = -1,
        timeout: int = 1200,
        maxit: int = 200,
    ):
        """
        Initialize Packmol wrapper.

        Args:
            packmol_path: Path to Packmol executable
            tolerance: Minimum distance between molecules (Angstrom)
            seed: Random seed (-1 for random)
            timeout: Packmol execution timeout in seconds (default 1200 = 20 min)
            maxit: Max GENCAN iterations per optimization cycle (default 200).
                v01.05.52 introduced a convergence gate (require Packmol to
                actually satisfy the distance constraint, not just produce an
                output file). With the prior maxit=2000 that gate made Packmol
                grind the *soft* target-distance objective for ~19 min/build
                even after the *hard* overlap/threading constraint was already
                met (max constraint violation ~1e-16). The v01.05.52 packing
                sweep found the quality knee at maxit=200: it satisfies the
                constraint (no overlap/threading) in ~55s — a ~20x speedup with
                no quality loss. Systems that don't converge at 200 are caught
                by the converged gate and rebuilt via the change_seed retry
                loop (structure_builder._pack_validate_retry), so 200 is safe.
        """
        self.packmol_path = packmol_path
        self.tolerance = tolerance
        self.seed = seed
        # PACKMOL_TIMEOUT_S 환경변수로 머신별 오버라이드 — 실 E2E에서 저스레드
        # 머신은 기본 1200s가 부족함을 확인(수렴은 정상 진행, wall-clock 부족).
        env_timeout = os.environ.get("PACKMOL_TIMEOUT_S")
        self.timeout = int(env_timeout) if env_timeout else timeout
        self.maxit = maxit
        self._check_packmol()

    def _check_packmol(self) -> None:
        """Check if Packmol is available."""
        try:
            subprocess.run(
                [self.packmol_path],
                input="",
                capture_output=True,
                text=True,
                timeout=5,
            )
            # Packmol returns non-zero when run without input, but that's OK
            self._packmol_available = True
        except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
            self._packmol_available = False
            logger.warning(f"Packmol not found or not executable at {self.packmol_path}")

    def is_available(self) -> bool:
        """Check if Packmol is available."""
        return self._packmol_available

    def pack(
        self,
        molecules: list[PackmolMolecule],
        output_file: Path,
        total_mass_g_mol: float,
        box_size: float | None = None,
        box_dimensions: tuple[float, float, float] | None = None,
        density: float = 0.5,
        work_dir: Path | None = None,
        contain_entire_molecules: bool = False,
    ) -> PackmolResult:
        """
        Run Packmol to pack molecules into a box.

        Args:
            molecules: List of molecules to pack
            output_file: Output XYZ/PDB file path
            total_mass_g_mol: Total molecular mass in g/mol (required for accurate box calculation)
            box_size: Box side length (Angstrom), auto-calculated if None
            box_dimensions: Optional explicit box dimensions (lx, ly, lz) in Angstrom
            density: Target density (g/cm3) for auto box size (default 0.5 for moderate packing)
            work_dir: Working directory (temp dir if None)
            contain_entire_molecules: If True, increase Packmol box margin so that
                entire molecules (not just centers) are contained within the box.
                The margin is tolerance + max_molecular_radius + 0.5 Å safety buffer.

        Returns:
            PackmolResult with success status and output
        """
        # Calculate total atoms and max molecule size by reading XYZ files
        total_atoms = 0
        max_mol_dimension = 0.0

        for m in molecules:
            if m.structure_file.exists():
                try:
                    lines = m.structure_file.read_text().strip().split("\n")
                    atoms_in_mol = int(lines[0].strip())
                    total_atoms += atoms_in_mol * m.count

                    # Calculate molecule bounding box to ensure box is large enough
                    coords = []
                    for line in lines[2 : 2 + atoms_in_mol]:
                        parts = line.split()
                        if len(parts) >= 4:
                            coords.append([float(parts[1]), float(parts[2]), float(parts[3])])

                    if coords:
                        xs = [c[0] for c in coords]
                        ys = [c[1] for c in coords]
                        zs = [c[2] for c in coords]
                        mol_size = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
                        max_mol_dimension = max(max_mol_dimension, mol_size)
                except (ValueError, IndexError):
                    total_atoms += m.count * 20  # fallback estimate
            else:
                total_atoms += m.count * 20  # fallback estimate

        if box_dimensions is not None:
            lx, ly, lz = box_dimensions
            if lx <= 0 or ly <= 0 or lz <= 0:
                raise ValueError(f"Invalid box_dimensions: {box_dimensions}")
            box_dims = (float(lx), float(ly), float(lz))
        else:
            if box_size is None:
                # Calculate box size from total mass (accurate method)
                # mass_g = total_mass_g_mol / AVOGADRO
                # volume_cc = mass_g / density
                # volume_A3 = volume_cc / (ANGSTROM_TO_CM ** 3)
                # box_side = volume_A3 ** (1/3)
                from common.units import ANGSTROM_TO_CM, AVOGADRO

                mass_g = total_mass_g_mol / AVOGADRO
                volume_cc = mass_g / density
                volume_A3 = volume_cc / (ANGSTROM_TO_CM**3)
                box_from_density = volume_A3 ** (1.0 / 3.0)

                # Box must be large enough for density AND large enough to fit molecules
                # Add margin for molecule rotation and tolerance
                min_box_for_molecules = max_mol_dimension + self.tolerance * 4
                box_size = max(box_from_density, min_box_for_molecules)
                logger.info(
                    f"Box size: {box_size:.1f} Å (density-based: {box_from_density:.1f}, mol_min: {min_box_for_molecules:.1f}, "
                    f"target_density: {density:.3f} g/cm³)"
                )
            box_dims = (float(box_size), float(box_size), float(box_size))

        # Create working directory
        cleanup_work_dir = work_dir is None
        if work_dir is None:
            work_dir = Path(tempfile.mkdtemp(prefix="packmol_"))
        else:
            work_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Calculate effective margin for containment
            containment_feasible = True
            if contain_entire_molecules and box_dims is not None:
                max_radius = self._calc_max_molecular_radius(molecules)
                effective_margin = self.tolerance + max_radius + 0.5  # 0.5 Å safety buffer
                if all(dim - 2 * effective_margin > 0 for dim in box_dims):
                    margin_override = effective_margin
                else:
                    logger.warning(
                        f"Molecule too large for strict containment "
                        f"(max_radius={max_radius:.1f} Ang, box={box_dims}). "
                        f"Using standard margin={self.tolerance} Ang"
                    )
                    margin_override = self.tolerance
                    containment_feasible = False
            else:
                margin_override = self.tolerance
            effective_margin = margin_override

            # Generate input file
            input_file = work_dir / "packmol.inp"
            self._generate_input(
                molecules, output_file, box_dims, input_file, margin=effective_margin
            )

            # Run Packmol
            if not self._packmol_available:
                # Mock mode for testing
                mock_result = self._mock_pack(molecules, output_file, work_dir, box_dims)
                mock_result.containment_feasible = containment_feasible
                return mock_result

            # Use file descriptor instead of input= to avoid "Illegal seek" error
            # on WSL/Fortran (Packmol needs seekable stdin for rewind operations)
            # This approach works on both WSL and native Ubuntu
            with open(input_file) as f:
                result = subprocess.run(
                    [self.packmol_path],
                    stdin=f,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    cwd=work_dir,
                )

            # ``success`` = "output 파일 생성" (다운스트림 진행 가능 여부).
            # ``converged`` = Packmol이 거리 제약을 실제 달성했는지(자기 보고).
            #
            # 과거엔 "출력 파일만 있으면 returncode≠0도 acceptable"로 처리해
            # **비수렴 출력(분자 겹침/관통 포함)을 통과**시켰다. Packmol은 수렴 시
            # ``Success!`` + 위반량 0, 미수렴 시 ``STOP``(GENCAN loop 소진) +
            # 위반량>0을 보고한다. 관통은 (방향족 고리 반지름 < tolerance이므로)
            # 반드시 tolerance 위반을 동반 → ``converged``가 일반·튜닝불요 게이트다.
            if output_file.exists() and output_file.stat().st_size > 0:
                success = True
                converged, max_viol = _parse_packmol_convergence(result.stdout)
                if not converged:
                    logger.warning(
                        "Packmol did not converge (max constraint violation=%s, exit=%s); "
                        "structure likely contains inter-molecular overlaps/threading",
                        max_viol,
                        result.returncode,
                    )
            else:
                success = False
                converged = False
                max_viol = None
                logger.error("Packmol did not generate output file")

            return PackmolResult(
                success=success,
                output_file=output_file,
                log=result.stdout + result.stderr,
                error_message=None if success else result.stderr,
                box_dimensions=box_dims,
                containment_feasible=containment_feasible,
                converged=converged,
                max_constraint_violation=max_viol,
            )

        except subprocess.TimeoutExpired:
            # Timeout always fails - incomplete packing produces low-quality structures
            logger.error(f"Packmol timeout after {self.timeout} seconds - packing too dense")
            return PackmolResult(
                success=False,
                output_file=output_file,
                log="",
                error_message=f"Packmol timeout after {self.timeout}s - packing too dense",
                box_dimensions=box_dims,
                containment_feasible=containment_feasible,
                converged=False,
            )
        except Exception as e:
            return PackmolResult(
                success=False,
                output_file=output_file,
                log="",
                error_message=str(e),
                box_dimensions=box_dims,
                containment_feasible=containment_feasible,
                converged=False,
            )
        finally:
            if cleanup_work_dir and work_dir.exists():
                shutil.rmtree(work_dir, ignore_errors=True)

    def _calc_max_molecular_radius(self, molecules: list[PackmolMolecule]) -> float:
        """Calculate maximum radial extent of any molecule from its center of geometry.

        Reads XYZ structure files and computes the largest distance from any atom
        to the molecular centroid across all molecule types.

        Args:
            molecules: List of PackmolMolecule entries with structure files.

        Returns:
            Maximum molecular radius in Angstrom. Returns 0.0 if no coordinates
            can be parsed.
        """
        max_radius = 0.0
        for mol in molecules:
            if not mol.structure_file.exists():
                continue
            try:
                lines = mol.structure_file.read_text().strip().split("\n")
                n_atoms = int(lines[0].strip())
                coords: list[tuple[float, float, float]] = []
                for line in lines[2 : 2 + n_atoms]:
                    parts = line.split()
                    if len(parts) >= 4:
                        coords.append((float(parts[1]), float(parts[2]), float(parts[3])))
                if coords:
                    cx = sum(c[0] for c in coords) / len(coords)
                    cy = sum(c[1] for c in coords) / len(coords)
                    cz = sum(c[2] for c in coords) / len(coords)
                    radius = max(
                        ((x - cx) ** 2 + (y - cy) ** 2 + (z - cz) ** 2) ** 0.5 for x, y, z in coords
                    )
                    max_radius = max(max_radius, radius)
            except (ValueError, IndexError):
                continue
        return max_radius

    def _generate_input(
        self,
        molecules: list[PackmolMolecule],
        output_file: Path,
        box_dimensions: tuple[float, float, float],
        input_file: Path,
        margin: float | None = None,
    ) -> None:
        """Generate Packmol input file.

        Args:
            molecules: List of molecules to pack.
            output_file: Output XYZ/PDB file path.
            box_dimensions: Box dimensions (lx, ly, lz) in Angstrom.
            input_file: Path to write Packmol input file.
            margin: Inner margin from box edges (Angstrom). Defaults to self.tolerance.
        """
        if margin is None:
            margin = self.tolerance
        lx, ly, lz = box_dimensions

        lines = [
            f"tolerance {self.tolerance}",
            "filetype xyz",
            f"output {output_file}",
            "resnumbers 2",  # Enable random rotation per molecule
            "movebadrandom",  # Move colliding molecules randomly
            f"maxit {self.maxit}",  # Max iterations per optimization cycle
            "",
        ]

        if self.seed > 0:
            lines.insert(0, f"seed {self.seed}")

        for mol in molecules:
            lines.extend(
                [
                    f"structure {mol.structure_file}",
                    f"  number {mol.count}",
                    f"  inside box {margin} {margin} {margin} {lx - margin} {ly - margin} {lz - margin}",
                    "end structure",
                    "",
                ]
            )

        input_file.write_text("\n".join(lines))

    def _mock_pack(
        self,
        molecules: list[PackmolMolecule],
        output_file: Path,
        work_dir: Path,
        box_dimensions: tuple[float, float, float] | None = None,
    ) -> PackmolResult:
        """
        Mock packing for testing without Packmol.

        Generates an XYZ file preserving actual elements and molecular geometry.
        """
        import random

        atom_lines = []
        total_atoms = 0
        lx = box_dimensions[0] if box_dimensions else 100.0
        ly = box_dimensions[1] if box_dimensions else 100.0
        lz = box_dimensions[2] if box_dimensions else 100.0

        for mol in molecules:
            # Parse molecule structure to get actual elements and relative positions
            mol_atoms: list[tuple[str, float, float, float]] = []  # (element, rx, ry, rz)

            if mol.structure_file.exists():
                mol_lines = mol.structure_file.read_text().strip().split("\n")
                if len(mol_lines) >= 3:
                    try:
                        n_atoms = int(mol_lines[0])
                        for line in mol_lines[2 : 2 + n_atoms]:
                            parts = line.split()
                            if len(parts) >= 4:
                                mol_atoms.append(
                                    (
                                        parts[0],  # element symbol
                                        float(parts[1]),  # relative x
                                        float(parts[2]),  # relative y
                                        float(parts[3]),  # relative z
                                    )
                                )
                    except (ValueError, IndexError):
                        # Fallback to carbon atoms
                        mol_atoms = [("C", 0.0, 0.0, 0.0)] * 10
            else:
                # Default mock atoms
                mol_atoms = [("C", 0.0, 0.0, 0.0)] * 10

            # Place each molecule instance with random center position
            # Use per-axis dimensions for rectangular boxes (e.g., lz << lx for interface cells)
            margin = self.tolerance + 1.0
            for _i in range(mol.count):
                cx = random.uniform(margin, max(margin + 0.1, lx - margin))
                cy = random.uniform(margin, max(margin + 0.1, ly - margin))
                cz = random.uniform(margin, max(margin + 0.1, lz - margin))

                for element, rx, ry, rz in mol_atoms:
                    # Add small random perturbation while preserving geometry
                    x = cx + rx + random.uniform(-0.1, 0.1)
                    y = cy + ry + random.uniform(-0.1, 0.1)
                    z = cz + rz + random.uniform(-0.1, 0.1)
                    atom_lines.append(f"{element} {x:.6f} {y:.6f} {z:.6f}")
                    total_atoms += 1

        # Write XYZ file
        lines = [str(total_atoms), "Mock Packmol output (preserved elements)"]
        lines.extend(atom_lines)

        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("\n".join(lines))

        return PackmolResult(
            success=True,
            output_file=output_file,
            log="Mock Packmol execution (elements preserved)",
            error_message=None,
            box_dimensions=box_dimensions,
        )

    def get_version(self) -> str | None:
        """Get Packmol version string."""
        if not self._packmol_available:
            return None

        try:
            result = subprocess.run(
                [self.packmol_path],
                input="",
                capture_output=True,
                text=True,
                timeout=5,
            )
            # Parse version from output
            for line in result.stdout.split("\n"):
                if "version" in line.lower():
                    return line.strip()
            return "unknown"
        except Exception:
            return None
