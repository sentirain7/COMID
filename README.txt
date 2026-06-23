================================================================================
        COMID - COmplex Multiphase Integrated Dynamics
                              v0.99.01
================================================================================

(Korean version: README.ko.txt)


OVERVIEW
--------------------------------------------------------------------------------
COMID is an open-source platform that automates the molecular dynamics (MD)
simulation of complex multiphase materials — its reference application is
asphalt binders — into a single reproducible pipeline. It unifies a
previously hand-assembled tool chain (Packmol / antechamber / LAMMPS / parsers /
analysis) under one single-source-of-truth (SSOT) architecture, so that a
composition specification (SARA + additives) deterministically yields bulk
physical properties. Every decision is hash-pinned for reproducibility and
auditability.

Two-tier reproducibility boundary:
  - Reviewable Core (LAMMPS-free): force-field assignment, topology assembly,
    protocol generation, and metric calculation run in minutes without GPU or
    LAMMPS. The entire decision logic is verifiable without special hardware.
  - Execution Backend (optional): GPU LAMMPS runs, Packmol packing, and
    antechamber charge derivation are isolated as subprocesses; not required
    for evaluation/review.

(COMID builds on the asphalt-binder MD/ML agent previously developed as NACMID.)


CURRENT FEATURES (Stable Core - Bulk MD Automation)
--------------------------------------------------------------------------------
[Structure Generation]
  - SARA molecular library: reference binders AAA1 / AAK1 / AAM1, system sizes
    X1 / X2 / X3 = 72 / 144 / 216 molecules (Li & Greenfield 2014)
  - Aging states: non_aging (U-) / short_aging (S-) / long_aging (L-)
    (Saturate has no aged structure -> non_aging fallback)
  - 12 SARA molecules (Saturate 2, Aromatic 2, Resin 5, Asphaltene 3) +
    additive library (SBS, SiO2, NanoClay, Lignin, PPA, Sasobit, CRM,
    Graphine, CNT, Polyethylene, etc.)
  - Packmol packing + convergence gate (ring-threading detection, sparse
    low-density initialization) + retry-on-failure

[Force Field - Deterministic Routing (not a user choice)]
  - typing_router maps each molecule, by metadata, to one of five routes:
      organic_curated_artifact : GAFF2 + AM1-BCC (antechamber) -- the only
                                 active organic route; baseline -> sqm_robust
                                 auto-escalation; fail-closed on permanent
                                 failure
      inorganic_profile        : INTERFACE FF Lennard-Jones (Heinz 2013) +
                                 per-material literature charges (CLAYFF family
                                 / Raiteri-Gale / formal-ionic),
                                 Lorentz-Berthelot mixing
      water_model              : TIP3P
      ionic_profile            : Joung-Cheatham / Li-Merz (operator-gated)
      blocked                  : fail-closed (immediate block)
  - fragment_fallback (tertiary): parameterizes AM1-SCF-nonconvergent neutral
    CHONS molecules (e.g. curved CNT) with canonical GAFF2 bonded terms
    (incl. dihedrals) + AM1-BCC reference charges; governance research_only
    (firewalled out of ML datasets / submission)
  - FF governance: ValidationLevel = validated / research_only / blocked
  - Per-molecule FF artifacts and E_intra are shared across machines via
    git-tracked sidecars

[Simulation / Protocol]
  - Jinja2-based LAMMPS input-script generation
  - pair_style lj/cut/coul/long + PPPM long-range electrostatics (kspace pppm)
  - Study type BULK ("p p p", NPT iso)
  - Run tiers (conditional selection, not a linear ladder):
    screening / confirm / viscosity
  - Stabilization chain: minimize -> NVT -> NPT (-> NEMD for viscosity)
  - Policy-driven failure recovery: overlap -> change_seed,
    pressure/energy blow-up -> reduce_dt

[Metrics - 7 bulk properties]
  - density                          (NPT average)
  - cohesive_energy_density          (single-molecule vacuum E_intra
                                      subtraction)
  - bulk_modulus                     (NPT volume fluctuation)
  - glass_transition_temperature_k   (bilinear fit + bootstrap CI)
  - viscosity                        (NEMD)
  - rdf_first_peak / coordination_number (RDF)
  - msd_diffusion_coefficient        (MSD)
  - Array metrics (Parquet): rdf_curve, msd_curve, density_profile, thermo_log
  - All metrics validated against DEFAULT_METRICS_REGISTRY (SSOT)

[Orchestration / GPU]
  - Celery + Redis distributed job queue
  - GPUService: atomic global lock (fcntl) + single transaction serialize GPU
    allocation (1 job = 1 slot invariant)
  - MPS multi-job co-location: 3 slots per GPU
  - Hardware-UUID routing (non-contiguous indices allowed); ineligible GPUs
    (< 32 GB, e.g. RTX 3050) are hard-excluded from allocation
  - 3-pool worker separation: gpu@ (GPU simulation jobs) / control@ (scheduler,
    recovery, control plane) / cpu(build)@ (Packmol build + metrics + CPU
    post-processing)
  - Hash-pinned reproducibility: plan_hash, provenance, deterministic seeding
  - Result sidecar write-through/import for cross-machine result-DB sharing
    (curve Parquet tracked in git)

[Interfaces]
  - FastAPI REST API (REST-only; no GraphQL)
  - React + Vite web dashboard, React Query polling (no WebSocket subscription)
  - English-only UI


FUTURE DEVELOPMENT (Roadmap)
--------------------------------------------------------------------------------
The capabilities below exist in the codebase but are treated as forward-looking
development tracks; their quantitative validation and/or default activation is
ongoing. They are not part of the stable bulk-MD core above.

[Layered / Interface Structures]
  - binder-crystal interface generation (study type LAYER_BULKFF, "p p f")
  - INTERFACE FF (Heinz 2013) + mineral charge catalog (CLAYFF / Raiteri-Gale /
    formal-ionic); long-range Coulomb restoration via CPU rerun
  - Interface / mechanical metrics: work_of_separation,
    interfacial_tensile_strength, tensile_strength, elastic_modulus
    (replicate mean +/- SE)
  - Status: implemented; quantitative interface-property validation in progress

[Machine-Learning Property Prediction]
  - V7 structural feature set: 32 features = 10 RDKit descriptors aggregated by
    composition-weighted mean/sum/std (30) + 2 system features (fragment count,
    temperature)
  - Per-property XGBoost vs RandomForest competitive training (winner per
    property)
  - Group-aware holdout (additive_mol_id -> additive-leakage prevention)
  - log transform for viscosity / MSD; evaluation on the original scale
  - OOD / uncertainty flags; champion-challenger model registry
  - Internal-data-only (GAFF2) training by default; Parquet feature store
  - Opt-in online retraining (default OFF)

[Inverse Design - composition recommendation (ML-driven)]
  - Bayesian optimization: acquisition EI / UCB / EHVI / PI (default auto)
  - Pareto-front extraction, FeasibilityScout pre-diagnosis (opt-in),
    deterministic closed loop (opt-in, default OFF)
  - Property-target-only objectives (viscosity / density / CED /
    work_of_separation specified directly)
  - Candidate = (binder_type, additive_type, additive_wt) with structure_size
    input; reuses the forward batch binder-cell path as SSOT
  - Stateless pipeline: plan (plan_hash) -> approve -> progress -> results
    -> loop
  - Moisture-damage track: wet/dry interface pairs + energy ratio (ER)
  - Note: depends on the ML predictor above for BO screening

[ReaxFF Validation Track]
  - Reactive force-field validation (validation tier, dt 0.5 fs, QEq)


REQUIREMENTS
--------------------------------------------------------------------------------
  Python       >= 3.11 (3.12 recommended)
  conda env    environment.yml provided

  [Reviewable Core only] Linux + Python + RDKit (no GPU)

  [Full execution, additionally]
  LAMMPS       22 Jul 2025 custom build (KOKKOS + CUDA + OpenMP + cuFFT)
               .env: LAMMPS_EXECUTABLE, LAMMPS_GPU_PACKAGE=kokkos
  Packmol      structure packing
  AmberTools   antechamber / parmchk2 / tleap (GAFF2/AM1-BCC parameterization)
  Redis        >= 6 (Celery broker)
  DB           SQLite (development / single machine) /
               PostgreSQL >= 14 (multi-machine)


INSTALLATION
--------------------------------------------------------------------------------
  git clone <repository-url>
  cd COMID

  # One-command bootstrap. Installs conda if missing, builds the env, installs
  # the package, scaffolds .env, and verifies the core - in dependency order.
  ./install.sh                 # Reviewable Core (no GPU / no LAMMPS)
  ./install.sh --full          # + build GPU LAMMPS (Execution Backend)
  ./install.sh --extras ml     # choose pip extras (default: all)

  conda activate asphalt_env

  What ./install.sh does, in order:
    1. conda (Miniforge)  - auto-installed to ~/miniforge3 if missing
    2. conda env from environment.yml
       (rdkit, ambertools, numpy, scipy, xgboost, ... via conda-forge, which
        resolves the scientific-stack ordering / ABI for you)
    3. pip install -e ".[all]"        (the COMID package itself)
    4. .env scaffolded from .env.example
    5. (--full only) GPU LAMMPS build via scripts/install_lammps.sh
    6. import-level verification of the Reviewable Core

  Manual / piecemeal install (equivalent, if you prefer):
    conda env create -f environment.yml && conda activate asphalt_env
    pip install -e ".[all]"           # or ".[ml]" for reviewable core + ML
    cp .env.example .env              # then edit for your machine
    scripts/install_lammps.sh         # pinned GPU LAMMPS (stable_22Jul2025,
                                      #   KOKKOS+CUDA+cuFFT; auto-detects GPU arch,
                                      #   writes LAMMPS_EXECUTABLE into .env)

  # PYTHONPATH=src:packages is required at runtime


RUNNING
--------------------------------------------------------------------------------
  ./start_all.sh            # full stack
                            #   Redis + FastAPI(:8000) + React(:5173)
                            #   + Celery workers (gpu@/control@/build@) + MPS
  ./start_all.sh --dev      # development mode (auto-reload)
  ./start_all.sh --status   # service status
  ./start_all.sh --stop     # stop everything
  ./start_all.sh --check    # dependency check only
  ./start_all.sh --verify   # module-import verification only

  # LAMMPS-free dry run (core logic only, no GPU)
  PYTHONPATH=src:packages python scripts/run_inverse_pipeline_smoke.py


DIRECTORY STRUCTURE
--------------------------------------------------------------------------------
  src/
    contracts/      schemas + policy definitions (SSOT, do not modify)
    common/         shared utilities (pathing/hashing/logging, do not modify)
    builder/        structure generation (Packmol, molecule DB)
    forcefield/     FF parameter management (GAFF2/AM1-BCC, INTERFACE FF,
                    fragment_fallback)
    protocols/      LAMMPS input-script generation (Jinja2)
    parsers/        log / dump parsing
    metrics/        property calculation (density, CED, Tg, bulk_modulus, ...)
    database/       SQLite/PostgreSQL (SQLAlchemy ORM)
    orchestrator/   pipeline orchestration (celery_job_manager, gpu_service)
    monitoring/     GPU detection / statistics (nvidia-smi, gpu_collector)
    config/         Pydantic Settings
    api/            FastAPI REST endpoints
    templates/      LAMMPS Jinja2 templates
    ml/             structural ML prediction (V7)          [future development]
    recommendation/ inverse-design engine (BO, Pareto)     [future development]
    validation/     ReaxFF validation track               [future development]
    features/       domain feature modules (incl. inverse-design pipeline)

  data/
    molecules/      SARA + additive molecule library
    forcefields/    mineral charge / LJ catalogs
    forcefield_artifacts/  generated GAFF2 artifacts + E_intra sidecars

  frontend/
    src/            React + Vite web dashboard

  docs/
    USER_MANUAL.md  (complete user manual for the current Stable Core)


TESTING
--------------------------------------------------------------------------------
  ./run_tests.sh              # full test suite
  pytest tests/unit/ -v       # unit tests (3,000+, no LAMMPS)
  pytest tests/e2e/ -v        # E2E tests (Level 0-7; mostly LAMMPS-free,
                              #            only the real-MD smoke needs GPU LAMMPS)
  ruff check . && ruff format .   # lint / format


DOCUMENTATION
--------------------------------------------------------------------------------
  docs/USER_MANUAL.md      complete user manual — installation, the molecule
                           library, single-molecule/binder/batch workflows,
                           force-field determination, the simulation protocol,
                           metrics, the REST API, and troubleshooting.
                           (covers the current Stable Core; roadmap tracks are
                           summarized in the FUTURE DEVELOPMENT section above)


LICENSE
--------------------------------------------------------------------------------
  MIT License

  External GPL tools (LAMMPS, AmberTools, Packmol) are invoked only as
  subprocesses (command line); they are not linked into or redistributed with
  this package. Python dependencies (RDKit, scikit-learn, XGBoost, SQLAlchemy,
  FastAPI, Celery, etc.) are permissively licensed and MIT-compatible.

================================================================================
