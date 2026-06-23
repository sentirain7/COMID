# COMID User Manual

**COMID — COmplex Multiphase Integrated Dynamics**
Version 0.99.01

A practical guide to running automated molecular-dynamics (MD) simulations of
asphalt binders and computing their bulk physical properties.

> Scope: this manual covers the **current (Stable Core)** capability — bulk MD
> automation. Forward-looking tracks (layered/interface structures, ML property
> prediction, inverse design, ReaxFF) are part of the roadmap and are **not**
> covered here.

---

## Table of Contents

1. [What COMID does](#1-what-comid-does)
2. [Installation and first run](#2-installation-and-first-run)
3. [Core concepts](#3-core-concepts)
4. [The molecule library](#4-the-molecule-library)
5. [Workflow A — single-molecule force field and E_intra](#5-workflow-a--single-molecule-force-field-and-e_intra)
6. [Workflow B — a single binder-cell simulation](#6-workflow-b--a-single-binder-cell-simulation)
7. [Workflow C — batch binder-cell jobs](#7-workflow-c--batch-binder-cell-jobs)
8. [Force-field determination](#8-force-field-determination)
9. [Simulation protocol](#9-simulation-protocol)
10. [Metrics](#10-metrics)
11. [Viewing and analyzing results](#11-viewing-and-analyzing-results)
12. [Orchestration and GPU](#12-orchestration-and-gpu)
13. [Cross-machine result sharing](#13-cross-machine-result-sharing)
14. [REST API reference (core)](#14-rest-api-reference-core)
15. [Command-line tools](#15-command-line-tools)
16. [Troubleshooting](#16-troubleshooting)

---

## 1. What COMID does

COMID turns a **composition specification** (a binder + optional additives) into
**bulk physical properties** through a fully automated, reproducible pipeline:

```
composition  ->  structure (Packmol)  ->  force field (GAFF2/AM1-BCC)
             ->  LAMMPS protocol  ->  GPU MD run  ->  parsed metrics  ->  database
```

Every step is hash-pinned (topology hash, protocol hash) so the same input always
produces the same plan, and results are auditable end to end. You drive the whole
thing from a web dashboard or the REST API; no manual editing of LAMMPS input
files is required.

---

## 2. Installation and first run

### 2.1 One-command install

```bash
git clone https://github.com/sentirain7/COMID.git
cd COMID
./install.sh           # Reviewable Core (no GPU / no LAMMPS)
./install.sh --full    # + build the GPU LAMMPS execution backend
conda activate asphalt_env
```

`./install.sh` performs, in dependency order: install conda (Miniforge) if
missing → create the conda env from `environment.yml` → `pip install -e ".[all]"`
→ scaffold `.env` from `.env.example` → verify the core imports. With `--full` it
also builds a pinned GPU LAMMPS via `scripts/install_lammps.sh`.

### 2.2 Configure `.env`

Edit `.env` (created from `.env.example`). Key entries for full execution:

| Variable | Example |
|----------|---------|
| `LAMMPS_EXECUTABLE` | `/home/you/lammps/build/lmp` (set automatically by `install.sh --full`) |
| `LAMMPS_GPU_PACKAGE` | `kokkos` |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` |
| `DATABASE_URL` | SQLite by default; PostgreSQL for multi-machine |

### 2.3 Start the stack

```bash
./start_all.sh            # Redis + API(:8000) + dashboard(:5173) + workers + MPS
./start_all.sh --status   # service status
./start_all.sh --stop     # stop everything
```

Open the dashboard at **http://localhost:5173** and the API docs at
**http://localhost:8000/docs**.

### 2.4 Verify without a GPU

The Reviewable Core (force-field assignment, topology assembly, protocol
generation, metric calculation) runs without LAMMPS or a GPU:

```bash
PYTHONPATH=src:packages python scripts/run_inverse_pipeline_smoke.py
pytest tests/unit/ -v        # 3,000+ unit tests, no LAMMPS required
```

---

## 3. Core concepts

**Two-tier reproducibility boundary.**
- *Reviewable Core* (no GPU/LAMMPS): the entire decision logic — which force
  field, what topology, which protocol, how metrics are computed — is executable
  and reviewable in minutes on any Linux machine.
- *Execution Backend* (optional): GPU LAMMPS runs, Packmol packing, and
  antechamber charge derivation are isolated as subprocesses.

**Single source of truth (SSOT).** Schemas, policies, the molecule library, and
the metric registry live in `src/contracts/` and `data/`. Modules never hardcode
constants — they read them from these SSOT locations.

**Deterministic, not configurable.** The force field for each molecule is
*decided* by a router from molecule metadata; it is not a user choice (see §8).

**Hash pinning.** A topology hash and a protocol hash identify each run.
Identical inputs reuse identical plans, which makes duplicate detection and
provenance automatic.

---

## 4. The molecule library

The library (`data/molecules/`) is the SSOT for all chemistry.

**Reference binders** (Li & Greenfield 2014): `AAA1`, `AAK1`, `AAM1`. Each is a
SARA mixture available in three system sizes:

| Size | Molecules |
|------|-----------|
| X1 | 72 |
| X2 | 144 |
| X3 | 216 |

**SARA fractions** are made of 12 molecule types: Saturate (2), Aromatic (2),
Resin (5), Asphaltene (3).

**Aging states:** `non_aging` (`U-`), `short_aging` (`S-`), `long_aging` (`L-`).
Saturates have no aged structure and fall back to `non_aging`.

**Additives:** SBS, SiO2, NanoClay, Lignin, PPA, Sasobit, CRM, Graphine, CNT,
Polyethylene, and others. Each additive carries a force-field route and a
submittability flag.

Browse the library in the dashboard under **Database → Single Molecule & FF**, or
via the API:

```bash
curl http://localhost:8000/binder-types
curl http://localhost:8000/binder-types/AAA1/composition
curl http://localhost:8000/additives
```

---

## 5. Workflow A — single-molecule force field and E_intra

Cohesive energy density (CED) is computed by subtracting each molecule's
**intramolecular energy in vacuum** (`E_intra`) from the bulk potential energy.
So before binder CED is available, each molecule's `E_intra` must be measured.

The procedure has two stages:

1. **Force-field parameterization ("Generate").** In **Database → Single Molecule
   & FF**, generating a molecule produces its GAFF2/AM1-BCC force-field artifact
   (the antechamber step). The artifact is cached and git-trackable.
2. **Per-temperature E_intra batch.** A *single-molecule vacuum* batch job runs a
   short MD per temperature (the standard 12-point grid spans 213–433 K) and
   records `E_intra(T)`. Use **Batch Job → Single Molecule** for this.

Once both stages are done, the per-temperature E_intra matrix is visible in the
molecule view, and binder CED becomes computable automatically (§10).

```bash
# inspect a molecule's stored E_intra matrix
curl http://localhost:8000/e_intra/U-AS-Thio-0293
```

> If a binder's CED is missing, the usual cause is that one of its components
> (often an additive) has no E_intra yet. Run its single-molecule batch first.

---

## 6. Workflow B — a single binder-cell simulation

Use **Single Job → Binder Cell** in the dashboard.

1. Pick a **binder type** (AAA1/AAK1/AAM1), **system size** (X1/X2/X3),
   **aging state**, and **temperature**.
2. Optionally add an **additive** (type and wt%). Additives that are not
   submittable are shown disabled with the blocking reason.
3. The applied force field is shown read-only (it is decided automatically, §8).
4. Submit. The job is built (Packmol), assigned a GPU slot, and run through the
   protocol (§9). Progress appears in **Jobs** and **Experiments**.

Equivalent API call:

```bash
curl -X POST http://localhost:8000/experiments \
  -H 'Content-Type: application/json' \
  -d '{ "binder_type": "AAA1", "structure_size": "X1",
        "aging_state": "non_aging", "temperature_K": 298 }'
```

When the run completes, its metrics (density, CED, …) are parsed and stored, and
the result appears under **Analysis** and **Recent Results**.

---

## 7. Workflow C — batch binder-cell jobs

For sweeps (multiple binders × aging × additive × temperature), use **Batch Job →
Binder Cell**. The batch screen offers the same choices as the single job, plus
multi-select over binders, aging states, additive amounts, and a temperature
list. A *campaign* groups the resulting experiments so you can track them
together.

```bash
curl http://localhost:8000/campaigns
curl http://localhost:8000/campaigns/progress
```

Batch validation builds and topology-checks every requested cell *without* a GPU,
so invalid combinations are rejected before any compute is spent.

---

## 8. Force-field determination

The force field is **decided deterministically** from molecule metadata by a
typing router. There are five routes:

| Route | Applied to | Force field |
|-------|------------|-------------|
| `organic_curated_artifact` | organic binder molecules | **GAFF2 + AM1-BCC** (antechamber) — the only active organic route |
| `inorganic_profile` | mineral / inorganic | INTERFACE FF Lennard-Jones + literature charges, Lorentz-Berthelot mixing |
| `water_model` | water | TIP3P |
| `ionic_profile` | ions | Joung-Cheatham / Li-Merz (operator-gated) |
| `blocked` | unsupported | fail-closed (immediate block) |

**Organic escalation ladder.** For the organic route, charge derivation tries
`baseline` antechamber first, then auto-escalates to `sqm_robust` if the AM1 SCF
does not converge, and otherwise fails closed. As a tertiary fallback,
`fragment_fallback` parameterizes AM1-SCF-nonconvergent **neutral CHONS**
molecules (e.g. curved CNT) with canonical GAFF2 bonded terms plus AM1-BCC
reference charges; such artifacts are governed as `research_only`.

**Governance.** Each force-field stack carries a `ValidationLevel` of
`validated`, `research_only`, or `blocked`. `research_only` artifacts are
firewalled out of any downstream dataset/submission gates.

You do not select any of this; the dashboard shows the resulting label
read-only (e.g. *"Applied FF: GAFF2 + AM1-BCC"*).

---

## 9. Simulation protocol

LAMMPS input scripts are generated from Jinja2 templates. For bulk binders:

- **Pair style:** `lj/cut/coul/long` with PPPM long-range electrostatics
  (`kspace pppm`).
- **Study type BULK:** periodic boundaries `p p p`, isotropic NPT pressure
  coupling.
- **Stabilization chain:** `minimize → NVT → NPT` (→ NEMD for viscosity).

**Run tiers** select the protocol by intent (a conditional selection, not a
linear ladder):

| Tier | Purpose |
|------|---------|
| `screening` | default bulk properties (density, CED, …) |
| `confirm` | longer NPT for candidates / outliers |
| `viscosity` | adds a Müller-Plathe NEMD stage |

**Failure recovery** is policy-driven: overlap/instability → change the random
seed and rebuild; pressure or energy blow-up → reduce the timestep. Packmol
packing is gated for convergence (ring-threading detection, sparse low-density
initialization) and retried on failure.

---

## 10. Metrics

Seven bulk properties are computed and validated against the metric registry
(`DEFAULT_METRICS_REGISTRY`, the SSOT):

| Metric | Unit | How it is computed |
|--------|------|--------------------|
| `density` | g/cm³ | NPT-average density |
| `cohesive_energy_density` | MJ/m³ | bulk PE minus per-molecule vacuum `E_intra` (§5) |
| `bulk_modulus` | GPa | NPT volume-fluctuation |
| `glass_transition_temperature_k` | K | bilinear density–temperature fit + bootstrap CI |
| `viscosity` | mPa·s | Müller-Plathe reverse NEMD |
| `rdf_first_peak_r` / `rdf_coordination_number` | Å / – | radial distribution function |
| `msd_diffusion_coefficient` | cm²/s | mean-squared displacement |

Array metrics are stored as Parquet: `rdf_curve`, `msd_curve`, `density_profile`,
`thermo_log`.

> CED and Tg are cross-temperature properties: CED needs each component's
> `E_intra` (§5); Tg needs density measured across the temperature grid.

---

## 11. Viewing and analyzing results

- **Dashboard → Analysis.** 3D scatter of any metric across compositions, a
  molecule-impact view, and an explorer catalog of available axes. Metric axes
  are populated dynamically from the registry.
- **Recent Results / Thermo charts.** Per-experiment thermodynamic traces
  (temperature, pressure, density) and protocol-stage timelines.
- **Database browser.** Inspect binder cells, single molecules / FF artifacts,
  and per-molecule E_intra matrices.

Useful API calls:

```bash
curl "http://localhost:8000/experiments?status=completed"
curl "http://localhost:8000/analysis/scatter3d?x=density&y=cohesive_energy_density&z=temperature_K"
curl "http://localhost:8000/analysis/explorer/catalog"
curl "http://localhost:8000/experiments/export"
```

---

## 12. Orchestration and GPU

- **Queue.** Celery + Redis distribute jobs across three worker pools: `gpu@`
  (GPU simulations), `control@` (scheduler / recovery / control plane), and
  `cpu(build)@` (Packmol builds, metric post-processing).
- **GPU allocation.** `GPUService` serializes allocation under an atomic global
  lock in a single transaction (the *1 job = 1 slot* invariant). With MPS,
  multiple jobs co-locate per GPU (default 3 slots/GPU).
- **Routing.** GPUs are addressed by hardware UUID (non-contiguous indices are
  fine). GPUs below the memory threshold (e.g. a small display GPU) are hard-
  excluded from allocation.
- **Monitoring.** GPU utilization and slot occupancy are shown on the Dashboard;
  the data comes from `nvidia-smi` via the GPU collector.

Check service health any time with `./start_all.sh --status`.

---

## 13. Cross-machine result sharing

Large LAMMPS raw outputs (dumps, restarts, trajectories) stay local. The
**distilled results** that drive the graphs are shared as **git-tracked text
sidecars** instead of the binary database:

- Scalar metrics + experiment metadata → `data/result_sidecars/`
- Per-molecule `E_intra` → force-field-artifact sidecars
- Curve Parquet → `data/arrays/`

On another machine:

```bash
git pull
python scripts/import_result_sidecars.py   # upserts results into the local DB
python scripts/import_e_intra_sidecars.py   # E_intra matrices
```

The dashboard then shows the imported results — without ever transferring the
binary database.

---

## 14. REST API reference (core)

Interactive docs: **http://localhost:8000/docs**. Core endpoints:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/binder-types`, `/binder-types/{type}/composition` | binder definitions |
| GET | `/additives` | additive catalog (with submittability) |
| GET | `/e_intra/{mol_id}` | per-molecule E_intra matrix |
| GET/POST/DELETE | `/experiments`, `/experiments/{id}` | submit / list / remove experiments |
| GET | `/experiments/defaults`, `/experiments/export` | defaults, bulk export |
| GET | `/artifacts/status`, `/artifacts/admin/capabilities` | FF artifact + backend status |
| GET | `/campaigns`, `/campaigns/progress` | batch campaign tracking |
| GET | `/binder-studies`, `/binder-studies/{id}/results` | saved binder studies |
| GET | `/analysis/scatter3d`, `/analysis/explorer/catalog`, `/analysis/molecule-impact` | analysis views |
| GET/DELETE | `/jobs`, `/jobs/{id}`, `/jobs/completed` | job management |
| GET | `/benchmark/validate`, `/benchmark/expected-ids` | benchmark checks |

---

## 15. Command-line tools

| Command | What it does |
|---------|--------------|
| `./start_all.sh [--dev\|--status\|--stop\|--check]` | run / manage the stack |
| `./run_tests.sh` | full test suite |
| `pytest tests/unit/ -v` | unit tests (no LAMMPS) |
| `scripts/install_lammps.sh` | build pinned GPU LAMMPS, set `LAMMPS_EXECUTABLE` |
| `scripts/import_result_sidecars.py` | import shared results into the DB |
| `scripts/import_e_intra_sidecars.py` | import E_intra matrices |
| `scripts/backfill_ced.py` | recompute CED for completed binders from existing logs |
| `ruff check . && ruff format .` | lint / format |

Most maintenance scripts default to a dry run; pass `--commit` to write.

---

## 16. Troubleshooting

**A binder's CED is empty.** One of its components lacks `E_intra`. Run the
single-molecule vacuum batch for that molecule/additive (§5), or backfill from
existing logs with `scripts/backfill_ced.py`.

**An additive cannot be selected.** It is not submittable; the dashboard shows
the blocking reason. This is the fail-closed force-field gate (§8).

**A job stays queued.** Check `./start_all.sh --status`. GPU jobs need an
eligible GPU (above the memory threshold) and a free slot; the dashboard GPU
panel shows slot occupancy.

**LAMMPS is not found.** Set `LAMMPS_EXECUTABLE` in `.env`, or run
`scripts/install_lammps.sh` (or `./install.sh --full`) to build it.

**Results don't appear after `git pull`.** Run the sidecar import scripts (§13);
the binary database is intentionally not shared.

---

*COMID v0.99.01 — current (Stable Core) capability. Roadmap tracks
(layered/interface, ML, inverse design, ReaxFF) are described in README.txt.*
