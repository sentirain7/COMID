#!/usr/bin/env python3
"""Evaluate a finished TIP3P water viscosity validation run.

Parses ``log.lammps`` + ``vprofile_*.dat`` in the given validation directory with
the PRODUCTION ``ViscosityCalculator`` and reports viscosity + fit quality, then
judges it against the TIP3P literature regime.

Usage
-----
    python scripts/eval_water_viscosity.py validation/water_viscosity
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# TIP3P literature viscosity regime @ ~300 K (NOT experimental 0.85 mPa.s).
TIP3P_LOW, TIP3P_HIGH = 0.25, 0.45  # mPa.s pass window
GRAD_R2_MIN = 0.9  # clean linear velocity profile required
_DT_FS = 1.0


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python scripts/eval_water_viscosity.py <validation_dir>")
        return 2
    vdir = Path(sys.argv[1])
    log_path = vdir / "log.lammps"
    if not log_path.exists():
        print(f"[eval] no log.lammps in {vdir} — run the MD first")
        return 1

    from metrics.viscosity import ViscosityCalculator
    from parsers.log_parser import LogParser

    td = LogParser().parse(log_path).thermo_data
    calc = ViscosityCalculator()

    f_col = ViscosityCalculator.find_f_viscosity_column(td)
    if not f_col:
        print("[eval] no f_viscosity column in log — viscosity stage did not run/complete")
        return 1
    f_values = td[f_col]
    n_visc = len(f_values)
    step_col = td.get("Step", [])
    steps_visc = step_col[-n_visc:] if len(step_col) >= n_visc else list(range(n_visc))
    time_fs = np.array(steps_visc, dtype=np.float64) * _DT_FS

    box_area = ViscosityCalculator.extract_box_area_from_log(log_path.read_text())
    if box_area is None:
        vol = td.get("Volume", td.get("Vol", []))
        box_area = ViscosityCalculator.estimate_box_area_from_volume(float(np.mean(vol[-n_visc:])))

    profile = None
    vprofiles = sorted(vdir.glob("vprofile_*.dat"))
    if vprofiles:
        profile = calc.parse_velocity_profile(vprofiles[-1])

    result = calc.compute_from_rnemd(
        f_viscosity_values=f_values,
        time_fs=time_fs,
        box_area_A2=box_area,
        velocity_profile=profile,
    )

    print("=" * 64)
    print("TIP3P water viscosity validation")
    print("=" * 64)
    print(f"  f_viscosity samples : {result.n_thermo_samples}")
    print(f"  box area (Lx*Ly)    : {result.box_area_A2:.1f} A^2")
    print(f"  momentum flux R^2   : {result.flux_fit_r_squared}")
    print(f"  velocity grad R^2   : {result.gradient_fit_r_squared}")
    print(f"  viscosity           : {result.viscosity_mPas} mPa.s")
    if result.error:
        print(f"  error               : {result.error}")
    print("-" * 64)

    v = result.viscosity_mPas
    gr2 = result.gradient_fit_r_squared or 0.0
    if v is None:
        print("  VERDICT: INCONCLUSIVE (no viscosity computed)")
        return 1
    clean = gr2 >= GRAD_R2_MIN
    in_range = TIP3P_LOW <= v <= TIP3P_HIGH
    if in_range and clean:
        print(f"  VERDICT: PASS — eta={v:.3f} mPa.s in TIP3P range [{TIP3P_LOW},{TIP3P_HIGH}] "
              f"with clean gradient (R2={gr2:.3f}). Pipeline + thermostat fix are sound.")
    elif clean and not in_range:
        print(f"  VERDICT: CLEAN BUT OFF — eta={v:.3f} mPa.s (grad R2={gr2:.3f} good) but outside "
              f"[{TIP3P_LOW},{TIP3P_HIGH}]. Gradient is real; investigate flexible-TIP3P/dt/cutoff.")
    elif not clean and v < 0.05:
        print(f"  VERDICT: FAIL — eta={v:.4g} mPa.s with NOISY gradient (R2={gr2:.3f}). Same failure "
              f"mode as asphalt -> method still broken on a simple liquid (deeper bug).")
    else:
        print(f"  VERDICT: NOISY — grad R2={gr2:.3f} < {GRAD_R2_MIN}. Longer run / shear-rate tuning "
              f"needed; viscosity not yet trustworthy.")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
