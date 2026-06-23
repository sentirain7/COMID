# TIP3P water viscosity validation (Fix B)

Validate the Muller-Plathe RNEMD viscosity pipeline (generate_viscosity +
ViscosityCalculator, with the v01.06.25 profile-unbiased thermostat) on a KNOWN
liquid before trusting asphalt viscosity.

## System
- 1983 TIP3P water molecules, 39.00 A cubic box, rho = 1.0 g/cm^3
- target T = 300.0 K, P = 1 atm
- FF: TIP3P (OW q=-0.834 eps=0.1521 sig=3.1507; HW q=+0.417; OH k=450 r0=0.9572;
  HOH k=55 theta=104.52), flexible bonds/angles
- data file: water.data   |   input: in.lammps

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
    cd <repo-root>/validation/water_viscosity
    ${LAMMPS_EXECUTABLE:-lmp} -k on g 1 t 8 -sf kk -in in.lammps
  (or CPU: ${LAMMPS_EXECUTABLE:-lmp} -in in.lammps)

## Evaluate (after the run completes)
    python scripts/eval_water_viscosity.py <repo-root>/validation/water_viscosity

Notes:
- Uses the full production viscosity tier (minimize -> 500K NVT -> 500K/100atm NPT
  -> 300K NVT equil -> 300K/1atm NPT prod -> 300K viscosity NEMD).
  Water is robust to the 500 K equilibration excursion (subcritical liquid).
- To shorten for a quick check, reduce the STAGE 5 `run` steps in in.lammps.
