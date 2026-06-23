#!/usr/bin/env python3
"""Prepare a TIP3P water viscosity VALIDATION (no GPU MD run).

Purpose
-------
Fix B from the viscosity accuracy plan: before trusting the Muller-Plathe RNEMD
viscosity on asphalt, validate the WHOLE pipeline (generate_viscosity protocol +
ViscosityCalculator) on a KNOWN liquid — TIP3P water. If the pipeline reproduces
TIP3P's literature viscosity with a clean velocity gradient, the method is sound
and the asphalt failure is regime-specific (glassy/low-T). If not, there is a
code/units problem.

What this script does (PREPARATION ONLY — no GPU MD)
----------------------------------------------------
  1. Packs ~N TIP3P water molecules into a cubic box at rho = 1.0 g/cm^3
     (Packmol — a quick CPU step), via the SAME builder the pipeline uses.
  2. Generates the full-topology water .data (TIP3P via the water_model route).
  3. Generates the production viscosity in.lammps via LAMMPSInputGenerator
     (so it includes the v01.06.25 profile-unbiased thermostat fix).
  4. Writes everything to ``validation/water_viscosity/`` + a README with the
     expected value, pass criteria, run command, and eval command.

It does NOT run the 5 ns GPU MD. Run command is printed for the user to launch.

Expected result (TIP3P @ ~300 K)
--------------------------------
  TIP3P water viscosity is well-characterised and LOW vs experiment:
    rigid TIP3P ~ 0.32 mPa.s, flexible TIP3P ~ 0.3-0.4 mPa.s
    (experimental water ~ 0.85 mPa.s — do NOT use as the target).
  PASS if eta in ~[0.25, 0.45] mPa.s AND velocity-gradient fit R^2 > 0.9
  (clean linear profile => the temp_profile thermostat fix works).

Usage
-----
    python scripts/prepare_water_viscosity_validation.py            # build + generate
    python scripts/prepare_water_viscosity_validation.py --box 39   # cube edge (A)
    python scripts/prepare_water_viscosity_validation.py --temp 300  # target T (K)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from common.units import AVOGADRO  # noqa: E402

MOL_ID = "H2O"
MW_WATER = 18.015  # g/mol


def _molecule_count(box_a: float, density: float) -> int:
    import math

    volume_a3 = box_a**3
    total_mass_g = density * volume_a3 * 1e-24
    return max(1, int(math.floor(total_mass_g / MW_WATER * AVOGADRO + 0.5)))


def build_water_box(out_dir: Path, box_a: float, density: float, seed: int) -> Path:
    """Pack water and write a full-topology TIP3P .data file. Returns the .data path."""
    from api.deps import get_molecule_db
    from builder.mol_parser import parse_mol_topology
    from builder.packmol_wrapper import PackmolMolecule, PackmolWrapper
    from builder.topology_helpers import convert_mol_to_xyz, generate_single_component_topology

    mol_path = _REPO_ROOT / "data" / "molecules" / "single_moles" / f"{MOL_ID}.mol"
    if not mol_path.exists():
        raise FileNotFoundError(f"water MOL file missing: {mol_path}")

    # ff_assignment SSOT (H2O -> water_model route -> TIP3P via water_executor).
    ff_assignment = get_molecule_db().get_ff_assignment(MOL_ID)
    if not ff_assignment:
        raise RuntimeError(f"no ff_assignment for {MOL_ID} in MoleculeDB")
    print(f"[prep] ff_assignment route = {ff_assignment.get('route')}")

    count = _molecule_count(box_a, density)
    print(f"[prep] box = {box_a:.2f} A cube, rho = {density} g/cm^3 -> {count} water molecules")

    mol_topology = parse_mol_topology(mol_path, MOL_ID)
    if mol_topology is None:
        raise RuntimeError("failed to parse H2O.mol topology")

    xyz = convert_mol_to_xyz(mol_topology, MOL_ID, out_dir / f"{MOL_ID}.xyz")

    packed = out_dir / "packed.xyz"
    packmol = PackmolWrapper(seed=seed)
    result = packmol.pack(
        molecules=[PackmolMolecule(structure_file=xyz, count=count, mol_id=MOL_ID)],
        output_file=packed,
        total_mass_g_mol=MW_WATER * count,
        box_dimensions=(box_a, box_a, box_a),
        work_dir=out_dir,
        contain_entire_molecules=True,
    )
    if not result.success:
        raise RuntimeError(f"Packmol failed: {result.error_message}")
    print(f"[prep] Packmol OK (converged={getattr(result, 'converged', '?')})")

    data_path = out_dir / "water.data"
    generate_single_component_topology(
        mol_path=mol_path,
        mol_id=MOL_ID,
        molecule_count=count,
        packed_xyz_path=packed,
        output_data_path=data_path,
        box_dimensions=(box_a, box_a, box_a),
        ff_name="GAFF2",
        ff_assignment=ff_assignment,
    )
    print(f"[prep] wrote topology -> {data_path}")
    return data_path


def build_input_script(out_dir: Path, data_path: Path, temp_K: float) -> Path:
    """Generate the production viscosity in.lammps for the water box."""
    from contracts.schemas import FFType, ProtocolRequest, RunTier, StudyType
    from protocols.lammps_input import LAMMPSInputGenerator

    request = ProtocolRequest(
        ff_type=FFType.BULK_FF_GAFF2,
        run_tier=RunTier.VISCOSITY,
        study_type=StudyType.BULK,
        temperature_K=temp_K,
        pressure_atm=1.0,
        data_file_path=str(data_path),
    )
    gen = LAMMPSInputGenerator(template_dir=out_dir / "templates")
    result = gen.generate(request)
    script_path = Path(result.input_script_path)
    print(f"[prep] generated viscosity in.lammps -> {script_path}")
    return script_path


def write_readme(out_dir: Path, box_a: float, temp_K: float, count: int, script_path: Path) -> None:
    lmp = "${LAMMPS_EXECUTABLE:-lmp}"
    readme = out_dir / "README.md"
    readme.write_text(
        f"""# TIP3P water viscosity validation (Fix B)

Validate the Muller-Plathe RNEMD viscosity pipeline (generate_viscosity +
ViscosityCalculator, with the v01.06.25 profile-unbiased thermostat) on a KNOWN
liquid before trusting asphalt viscosity.

## System
- {count} TIP3P water molecules, {box_a:.2f} A cubic box, rho = 1.0 g/cm^3
- target T = {temp_K:.1f} K, P = 1 atm
- FF: TIP3P (OW q=-0.834 eps=0.1521 sig=3.1507; HW q=+0.417; OH k=450 r0=0.9572;
  HOH k=55 theta=104.52), flexible bonds/angles
- data file: water.data   |   input: {script_path.name}

## Expected result (TIP3P @ ~300 K)
TIP3P viscosity is well-characterised and LOW vs experiment:
  rigid TIP3P ~ 0.32 mPa.s ; flexible TIP3P ~ 0.3-0.4 mPa.s
  (experimental water ~ 0.85 mPa.s -- NOT the target for TIP3P).

PASS criteria:
  (1) eta in ~[0.25, 0.45] mPa.s  (TIP3P regime), AND
  (2) velocity-gradient fit R^2 > 0.9  (clean linear profile)
      -> confirms the temp_profile thermostat fix works and the pipeline is sound.
FAIL/diagnostic:
  - eta ~ 0.005 mPa.s or grad_R2 ~ 0.3 (like the asphalt runs) -> method still
    broken even on a simple liquid -> deeper code/units bug.
  - eta clean but ~3x off -> flexible-TIP3P / dt / cutoff effect (still informative).

## Run (GPU MD -- this is the actual computation)
    cd {out_dir}
    {lmp} -k on g 1 t 8 -sf kk -in {script_path.name}
  (or CPU: {lmp} -in {script_path.name})

## Evaluate (after the run completes)
    python scripts/eval_water_viscosity.py {out_dir}

Notes:
- Uses the full production viscosity tier (minimize -> 500K NVT -> 500K/100atm NPT
  -> {temp_K:.0f}K NVT equil -> {temp_K:.0f}K/1atm NPT prod -> {temp_K:.0f}K viscosity NEMD).
  Water is robust to the 500 K equilibration excursion (subcritical liquid).
- To shorten for a quick check, reduce the STAGE 5 `run` steps in {script_path.name}.
""",
    )
    print(f"[prep] wrote {readme}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Prepare TIP3P water viscosity validation (no GPU MD).")
    ap.add_argument("--box", type=float, default=39.0, help="Cubic box edge in Angstrom (default 39).")
    ap.add_argument("--density", type=float, default=1.0, help="Target density g/cm^3 (default 1.0).")
    ap.add_argument("--temp", type=float, default=300.0, help="Target temperature K (default 300).")
    ap.add_argument("--seed", type=int, default=12345, help="Packmol seed.")
    ap.add_argument(
        "--out",
        default=str(_REPO_ROOT / "validation" / "water_viscosity"),
        help="Output directory.",
    )
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[prep] output dir: {out_dir}\n")

    data_path = build_water_box(out_dir, args.box, args.density, args.seed)
    script_path = build_input_script(out_dir, data_path, args.temp)
    write_readme(out_dir, args.box, args.temp, _molecule_count(args.box, args.density), script_path)

    print("\n[prep] DONE. Inputs ready. Run the GPU MD when instructed, then evaluate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
