# COMID

**COmplex Multiphase Integrated Dynamics**
Version 0.99.01 · [한국어 README](README.ko.txt)

COMID is an open-source platform that automates the molecular-dynamics (MD)
simulation of **complex multiphase materials** — its reference application is
asphalt binders — into a single reproducible, hash-pinned pipeline. It unifies a
previously hand-assembled tool chain (Packmol / antechamber / LAMMPS / parsers /
analysis) under one single-source-of-truth (SSOT) architecture, so that a
composition specification deterministically yields bulk physical properties, with
every decision auditable end to end.

```
composition  ->  structure (Packmol)  ->  force field (GAFF2/AM1-BCC)
             ->  LAMMPS protocol  ->  GPU MD run  ->  parsed metrics  ->  database
```

> **Two-tier reproducibility.**
> *Reviewable Core* (no GPU/LAMMPS) — force-field assignment, topology assembly,
> protocol generation, and metric calculation run in minutes on any Linux
> machine. *Execution Backend* (optional) — GPU LAMMPS runs, Packmol packing, and
> antechamber charge derivation are isolated as subprocesses.

---

## Quick start

```bash
git clone https://github.com/sentirain7/COMID.git
cd COMID
./install.sh           # Reviewable Core (no GPU / no LAMMPS)
./install.sh --full    # + build the GPU LAMMPS execution backend
conda activate asphalt_env
./start_all.sh         # Redis + API(:8000) + dashboard(:5173) + workers
```

`./install.sh` runs, in dependency order: install conda (Miniforge) if missing →
create the env from `environment.yml` (conda-forge resolves the scientific-stack
ordering/ABI) → `pip install -e ".[all]"` → scaffold `.env` → verify the core
imports. With `--full` it also builds a pinned GPU LAMMPS via
`scripts/install_lammps.sh`.

Full instructions, workflows, and the REST API are in
**[docs/USER_MANUAL.md](docs/USER_MANUAL.md)**.

---

## Current features (Stable Core)

- **Structure generation** — SARA molecular library (reference binders
  AAA1/AAK1/AAM1; sizes X1/X2/X3 = 72/144/216 molecules; aging states; additive
  library), Packmol packing with a convergence gate (ring-threading detection,
  sparse low-density initialization) and retry-on-failure.
- **Deterministic force-field routing** — a typing router maps each molecule by
  metadata to one of five routes: `organic_curated_artifact` (GAFF2 + AM1-BCC,
  the only active organic route), `inorganic_profile` (INTERFACE FF +
  literature charges, Lorentz-Berthelot mixing), `water_model` (TIP3P),
  `ionic_profile`, or `blocked` (fail-closed). Charge derivation escalates
  `baseline → sqm_robust → fragment_fallback`; stacks carry a `ValidationLevel`
  of `validated`/`research_only`/`blocked`.
- **Simulation protocol** — Jinja2-generated LAMMPS input, `lj/cut/coul/long`
  with PPPM long-range electrostatics, BULK study type (`p p p`, NPT iso),
  `minimize → NVT → NPT (→ NEMD)` stabilization, policy-driven failure recovery.
- **Metrics (7 bulk properties)** — density, cohesive energy density, bulk
  modulus, glass-transition temperature, viscosity, RDF peak/coordination, and
  MSD diffusion coefficient, all validated against an SSOT metric registry; curve
  metrics stored as Parquet.
- **Orchestration & GPU** — Celery + Redis with three worker pools
  (`gpu@`/`control@`/`cpu(build)@`); atomic GPU allocation (1 job = 1 slot), MPS
  multi-job co-location, hardware-UUID routing, memory-threshold eligibility.
- **Interfaces** — FastAPI REST API (REST-only) and a React + Vite dashboard.
- **Reproducibility** — hash-pinned plans/provenance and git-tracked text
  sidecars for cross-machine result sharing (no binary database transfer).

## Roadmap (future development)

These tracks exist in the codebase but are forward-looking; their quantitative
validation and/or default activation is ongoing, and they are **not** part of the
Stable Core above:

- **Layered / interface structures** — binder–crystal interfaces (LAYER_BULKFF),
  INTERFACE FF + mineral charge catalog, interface/mechanical metrics.
- **Machine-learning property prediction** — V7 structural feature set,
  per-property XGBoost vs RandomForest, champion–challenger registry.
- **Inverse design** — ML-driven Bayesian optimization, Pareto front, stateless
  plan → approve → results pipeline.
- **ReaxFF validation track.**

---

## Requirements

- Python ≥ 3.11 (3.12 recommended); conda environment provided
  (`environment.yml`).
- **Reviewable Core only:** Linux + Python + RDKit (no GPU).
- **Full execution (additionally):** a custom GPU LAMMPS build
  (22 Jul 2025, KOKKOS + CUDA + OpenMP + cuFFT), Packmol, AmberTools
  (antechamber/parmchk2/tleap), Redis ≥ 6, and SQLite (single machine) or
  PostgreSQL ≥ 14 (multi-machine).

## Repository layout

```
src/         platform code (contracts, builder, forcefield, protocols,
             metrics, orchestrator, api, ...; ml/recommendation/validation
             belong to the roadmap)
data/        SARA + additive molecule library, mineral catalogs, FF artifacts
frontend/    React + Vite dashboard
docs/        USER_MANUAL.md
install.sh   one-command bootstrap     scripts/install_lammps.sh  pinned LAMMPS
```

## Testing

```bash
./run_tests.sh                 # full suite
pytest tests/unit/ -v          # 3,000+ unit tests, no LAMMPS
ruff check . && ruff format .  # lint / format
```

## License

[MIT](LICENSE). External GPL tools (LAMMPS, AmberTools, Packmol) are invoked only
as subprocesses; they are not linked into or redistributed with this package.
Python dependencies are permissively licensed and MIT-compatible.
