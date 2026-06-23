# Changelog

All notable changes to the contracts will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [01.02.06] - 2026-04-25

## [01.02.07] - 2026-04-25

### Summary
**Unified header action styling and tightened settings control spacing.**
This release aligns the top-level `Data Sync`, `Scan Database`, and
`Refresh` buttons across the asset/database screens and adjusts the
`E_intra Defaults` block in Settings so its header, description, and
select control match the density of the other settings sections.

### Added
- Added a shared frontend header-action style module so database and
  asset pages reuse the same button size, border, color, and hover
  treatment.
- Added regression coverage for the Interface Molecules header action
  and the cross-screen header button visibility rules.

### Changed
- Unified the header action buttons used by Database, Interface
  Molecules, Crystal Structures, and Layered Structures.
- Removed the redundant Database header `Refresh` button while keeping
  the compact Layered Structures `Refresh` action visually consistent
  with the other header buttons.
- Adjusted the Settings `E_intra Defaults` section to use a card header
  icon, shorter explanatory copy, top-aligned spacing, and a narrower
  select width that matches the surrounding settings controls.

## [01.02.06] - 2026-04-25

### Summary
**Submit method selectors now initialize from the settings default.**
This release aligns single-molecule and FF-related submit UIs with the
settings-backed `default_e_intra_method` so the visible selector state
matches the method that will actually be submitted.

### Added
- Added a shared frontend hook for resolving the submit-time `E_intra`
  method selection from the current settings default while preserving
  user-chosen overrides during the session.
- Added regression tests that lock the initial selector value to the
  settings default across single-molecule, batch single-molecule,
  binder-cell, batch binder-cell, and layered submit screens.

### Changed
- Submit screens no longer start from a blank "Use default" state; they
  initialize to the resolved settings method directly.
- Batch binder-cell and layered submit panels now receive the same
  settings-derived initial method selection path as the other submit
  workflows.

## [01.02.05] - 2026-04-25

### Summary
**API startup hotfix for system router wiring and stale PID cleanup.**
This release fixes an API bootstrap import mismatch introduced by the
lightweight `features.system` package boundary and hardens `start_all.sh`
so failed startup attempts do not leave stale PID files behind.

### Fixed
- Fixed FastAPI bootstrap wiring to import the concrete system `router`
  object instead of the `features.system.router` module during
  `app.include_router(...)`.
- Updated `start_all.sh` to detect API startup failure immediately after
  launch, print the recent API log tail, and remove the stale PID file
  instead of reporting the service as running.
- Updated service status reporting to sweep stale PID files for API,
  frontend, and Celery before printing warnings.

## [01.02.04] - 2026-04-25

### Summary
**Layered CED profile delivery + deferred-boundary cleanup.**
This release adds the first binder-backed layered CED profile path, improves
MLOps method observability, and tightens the public `E_intra` method
boundary so deferred periodic workflows cannot leak back into submit/read
defaults.

### Added
- Added binder-backed layered CED profile provenance (`mol_counts_by_layer`,
  `layer_volumes_A3`, `layer_labels`) and the `cohesive_energy_density_profile`
  array metric path.
- Added diagnostics payload fields for champion vs submission-default
  `e_intra_method` observability and mismatch reporting.
- Added regression coverage for public request-model periodic rejection and
  layered runtime propagation of per-layer provenance fields.

### Changed
- Public submit/settings validators now reject `single_molecule_periodic`
  consistently across request models; stale settings fall back to the
  supported Method 1/1a policy.
- Read/runtime fallback no longer consults ambient env/settings when
  provenance is missing; it logs and drops to the conservative Method 1
  baseline instead.
- Read-only frontend surfaces now render stored `E_intra` methods with
  human labels, while submit/settings surfaces remain filtered to the
  supported public method set.
- LAMMPS input template fallback now prefers the checked-in `src/templates/header.j2`
  file as the canonical header source.

### Deferred
- `single_molecule_periodic` remains reserved for future internal workflow
  expansion and is still not publicly submittable.
- Inter-layer density/CED proxies, batch layered workflow expansion, and
  direct per-layer thermo extraction beyond the current binder-backed profile
  path remain deferred.

## [01.02.03] - 2026-04-25

### Summary
**Settings-backed E_intra submission default — first refinement pass.**
This release tightens the submission-time `E_intra` method SSOT around
`settings.json`, preserves method provenance across retry/layered paths,
removes worker-side env drift, and aligns frontend submit surfaces to the
current supported method set.

### Added
- Added `default_e_intra_method` to validated settings request/response
  schemas and `/settings` GET response.
- Added method-aware settings UI for submission defaults and propagated the
  resolved method through single-molecule, binder-cell, and layered submit
  requests.
- Added layered `ced_provenance_mol_counts` plumbing so wt% layered runs can
  restore `mol_counts` without relying on DB commit timing.

### Changed
- Retry paths now preserve persisted `e_intra_method` for both
  single-molecule and bulk/layer experiments.
- Worker force-field generation now treats `ProtocolChain.e_intra_method` as
  authoritative and only uses Method 1 as a conservative fallback when the
  chain is incomplete.
- Runtime/read paths no longer consult ambient env/settings when layered or
  single-molecule provenance is missing; they fail back to conservative
  Method 1 instead of silently drifting to the current submission default.
- Frontend settings/localStorage handling now uses local storage only as a
  GET-failure fallback instead of a parallel SSOT.
- Submit and coverage UIs now hide the reserved Method 2 periodic option and
  consistently expose the supported submission method set.
- Public submit/settings schemas now reject `single_molecule_periodic`; the
  value remains reserved for future internal/experimental workflows only.

### Deferred
- `single_molecule_periodic` remains an enum-reserved deferred workflow. It is
  intentionally hidden from public submit/settings surfaces and rejected at
  the API boundary.
- Layered `cohesive_energy_density_profile` is now available for binder-backed
  layers only. Inter-layer interaction density/CED proxies, batch layered
  workflow expansion, and direct per-layer thermo extraction beyond the
  current profile path remain deferred.

### Fixed
- Fixed settings response contract mismatch that broke type-safe frontend
  consumption of `default_e_intra_method`.
- Fixed layered CED provenance race that could otherwise degrade to raw
  `PE/V` when `mol_counts` had not yet been restored from the database.
- Fixed lightweight import boundaries for system/experiment/layered packages
  so service/test paths do not pull FastAPI-only dependencies by accident.

## [00.97.50] - 2026-04-10

### Summary
**Plan v3 FF SSOT initiative — Waves 0–6 complete.** A comprehensive
six-wave overhaul of the force-field / typing / charge classification
SSOT, fail-closed routing, curated organic OPLS artifact pipeline,
ionic policy, mineral element-LJ catalog split, reference fixture
validation, and an integrated cross-SSOT audit.

Cumulative regression: ~480 passing test cases (0 failing) across
the seven new SSOTs.

### Wave 0 — Molecule classification SSOT (P0)
- Added `ff_assignment` blocks to every entry in
  `data/molecules/{asphalt_binder,single_moles,additives}.yaml` —
  five required keys (`route`, `status`, `source_id`, `formal_charge`,
  `canonical_smiles`).
- Extended `forcefield.typing_router.TypingStrategy` enum:
  `ORGANIC_RDKIT_LEGACY`, `ORGANIC_OPLS_ARTIFACT`, `INORGANIC_PROFILE`,
  `IONIC_PROFILE`, `BLOCKED`. `ORGANIC_TYPING` retained as alias.
- `resolve_typing_strategy(mol_id, additive_def, ff_assignment)`
  signature extension; ff_assignment is authoritative.
- **Critical fix**: ionic species (NaCl/CaCl2/MgCl2/KCl/NaOH/H2SO4)
  no longer silently misroute through the legacy RDKit organic path.
  They now route to BLOCKED with a user-friendly Wave 3 message.
- `MoleculeDB.get_ff_assignment(mol_id)` helper with eager yaml load
  + base_id resolution for SARA mol_ids.
- `resolve_ff_hint` fail-closed on internal exceptions
  (no silent default-open).
- `list_molecules` / `list_additives` enriched with `route`,
  `status`, `is_submittable`, `blocked_reason` for the frontend
  RouteBadge.

### Wave 1 — Honest labels + route-aware strict policy (P0)
- `data/forcefields/registry.yaml`: OPLS-AA `mixing_rules.sigma`
  `arithmetic` → `geometric` (Jorgensen 1996 alignment). Header
  comments document the runtime charge model honestly.
- `TypingChargeAssigner` charge_model labels: `mmff94` →
  `rdkit_mmff94`, `gasteiger` → `rdkit_gasteiger`. Cache keys keep
  the canonical internal name so existing on-disk caches remain
  valid.
- `MolTopologyBuilder._strict_ff_types`: per-build set populated
  by 3-tuple form `(MolTopology, count, mol_strict)`.
  `INORGANIC_PROFILE` and `ORGANIC_OPLS_ARTIFACT` molecules are
  strict; `ORGANIC_RDKIT_LEGACY` stays lax.
- LAYER_BULKFF combined regression: `pair_modify mix arithmetic`,
  `kspace_modify slab 3.0`, `lj/cut/coul/long`, INTERFACE FF Si
  ε=0.00040 lockdown.
- Frontend `MoleculeChipGrid` route/status badge taxonomy with
  five labels (Legacy RDKit / OPLS Artifact / IF / Ion / Blocked).

### Wave 2 — Curated organic OPLS artifact pipeline (P1, medium risk)
- New `data/forcefield_artifacts/organic_opls/<mol_id>.json` catalog
  + Toluene reference fixture (15 atoms, electrically neutral with
  ipso CA at 0.0).
- New `forcefield.organic_opls_artifact` schema + loader (in-memory
  cache, fail-closed on missing/malformed/atom-shape mismatch).
- New `forcefield.organic_typing_executor.assign_organic` dispatcher
  unifying ORGANIC_RDKIT_LEGACY and ORGANIC_OPLS_ARTIFACT routes.
  Result label `opls_aa_artifact` for the curated path.
- `forcefield.ligpargen.LigParGenAdminGuardError`: runtime is
  forbidden from constructing the LigParGen client without
  `ASPHALT_LIGPARGEN_ADMIN=1` (admin opt-in).
- New `scripts/generate_organic_artifact.py` (admin tool, two
  modes: `--from-lammps-data` offline / `--from-ligpargen` admin).
- `structure_builder` and `submission.precompute_typing_charge`
  routed through the executor.
- **Wave 2 SSOT integration**: `topology_helpers.py` (interface
  molecule cell + structure analysis probe) also routed through
  the typing router + organic_typing_executor so single-component
  helper paths cannot silently bypass the Wave 0 fail-closed
  contract.

### Wave 3 — Ionic policy confirmation (P2, no activation)
- New `data/forcefields/ionic_profiles.yaml` (draft, NaCl + CaCl2
  placeholders, all status=draft, activation gates closed).
- New `forcefield.ionic_executor` (stub): `assign_ionic` ALWAYS
  raises `IonicNotActivatedError` even when all activation gates
  are open.
- New `docs/ionic_profile_policy.md`: four-condition activation
  contract (usage context, mixing rule compatibility, literature
  provenance, LAMMPS regression in CI) + activation procedure.
- Defense-in-depth runtime gates: env var
  `ASPHALT_IONIC_ROUTE_ACTIVATED=1` AND yaml
  `activation.global_enabled=true` AND profile in
  `enabled_profiles` AND status=active AND
  `policy_preconditions_met()`.
- End-to-end lockdown: NaCl / CaCl2 / MgCl2 / KCl / NaOH / H2SO4
  remain BLOCKED through the typing router with the friendly
  "Wave 3 / surrogate" message.

### Wave 4 — Mineral element-LJ catalog split (P2, medium risk)
- New `data/forcefields/mineral_lj_catalog.yaml` (editable SSOT,
  schema_version=1):
  - `interface_ff` section: 15 mineral elements (Heinz 2013, Emami
    2014) — Si, O, Al, Ti, Fe, Zn, C, Ca, Mg, Na, K, Cl, Cu, Ni, H
  - `uff_fallback` section: 103 elements (Rappé 1992)
- New `forcefield.mineral_lj_loader` (yaml loader with typed
  dataclasses, six fail-closed error categories).
- `forcefield.interface_ff` and `forcefield.uff_element_fallback`:
  yaml-driven adapter with hardcoded fallback safety net for
  tmp_path test environments. Caller-facing variables
  (`INTERFACE_FF_MINERAL_PARAMS`, `UFF_ELEMENT_FALLBACKS`) are
  module-level dicts populated at import time.
- Numerical equivalence regression: `yaml ≡ hardcoded fallback`
  element by element within 1e-9.
- YAML 1.1 boolean trap: element symbol `No` (Nobelium) quoted in
  yaml because PyYAML safe_load otherwise parses it as Python
  `False`. Audit test catches future drops.
- SSOT split contract: `mineral_lj_catalog` is element-only;
  site rules stay in `inorganic_profiles.yaml`. The two SSOTs
  intentionally co-exist.

### Wave 5 — Reference-based validation (P1)
- New `tests/data/ligpargen_responses/` catalog: hand-curated
  LAMMPS data fixtures for toluene (aromatic+methyl), naphthalene
  (PAH), n-pentane (saturate). Parser regression locks
  `_parse_atom_charges` against three reference molecules.
- New `tests/data/mineral_combined/silica_binder_ref.lammps_data`:
  silica slab + binder fragment combined data file. Locks
  Si_tet ε=0.00040, O_br ε=0.15540, OPLS-AA aromatic CA/HA cross
  interaction.
- End-to-end artifact round trip: Wave 2 Toluene artifact →
  MolTopology → MolTopologyBuilder → write_lammps_data → re-parse
  charges, atom-by-atom equivalence preserved.
- Wave 2 artifact ↔ Wave 5 fixture cross-consistency lockdown.
- Binder stub charge contract: intentionally non-neutral (-0.230)
  documented in fixture header, README, AND test name
  (`test_binder_stub_charge_sum_is_intentional_non_neutral`).

### Wave 6 — Integration audit + plan v3 wrap-up
- New `tests/unit/test_ff_ssot_integration_audit.py`: cross-SSOT
  audit covering all seven yaml/JSON SSOTs in one test file.
  Locks: artifact source_id ↔ JSON catalog, ionic source_id ↔
  ionic profiles, inorganic source_id ↔ inorganic profiles,
  parameterization.mode ↔ ff_assignment.route consistency, ionic
  activation gates closed, mineral catalog stays element-only,
  Wave 4 numerical equivalence anchors, Wave 5 fixtures present,
  route enum exhaustive coverage, mol_id uniqueness across yamls.
- New `docs/forcefield_ssot.md`: post-implementation operator map.
  Per-wave files + entry conditions for adding molecules /
  promoting to artifact / activating ionic / adding mineral
  elements / updating FF parameters.
- Version bump: `00.96.05` / `00.97.04` → `00.97.50`.

### Cross-cutting safety
- Library audit fail-closes on missing `ff_assignment` at startup.
- `resolve_ff_hint` fail-closes on internal exceptions.
- `topology_helpers` single-component path routes through the SSOT
  router (interface molecule cell + structure analysis probe).
- `LigParGenClient` admin guard prevents runtime regression to the
  LigParGen network path.
- Mineral LJ catalog tmp_path fallback verified by module-reimport
  regression.

### Reference papers (newly cited)
- Jorgensen, Maxwell, Tirado-Rives. JACS 1996, 118, 11225 (OPLS-AA)
- Halgren. J. Comput. Chem. 1996, 17, 490 (MMFF94)
- Cygan, Liang, Kalinichev. JPC B 2004, 108, 1255 (CLAYFF)
- Heinz, Lin, Mishra, Emami. Langmuir 2013, 29, 1754 (INTERFACE FF)
- Emami et al. Chem. Mater. 2014, 26, 2647 (silica surface)
- Heinz et al. JPC C 2008, 112, 17281 (FCC metals)
- Dodda et al. NAR 2017, 45 (W1), W331 (LigParGen)
- Joung, Cheatham. JPC B 2008, 112, 9020 (JC ion params, deferred)
- Rappé et al. JACS 1992, 114, 10024 (UFF)

## [00.97.04] - 2026-04-08

### Summary
**Merge-ready performance optimization release.** All code review issues resolved, test suite green (326/326 passed).

### Performance Improvements
- **Adaptive Dump Interval**: Frame-count based (production: 50-200, equilibration: 30 frames)
- **FF Cache**: POSIX fcntl locking + gzip compression + LRU eviction (500 max)
- **RDF Analysis**: skip_fraction 0.3 with provenance tracking (frames_total/used/skipped)
- **GPU Thread Scaling**: Actual atom count based (8/12/16 threads for ≤120k/≤175k/>175k)

### Key Changes
- SamplingConfig in TierConfig for adaptive dump intervals
- ParameterCache cross-process cache hit (reload on miss)
- ProtocolChainAdjuster tier_policy injection
- LAMMPS 2025 compliance (newton off, package kokkos before read_data)
- Complete GPU thread scaling coverage (bulk/layer/deferred paths)

## [00.97.03] - 2026-04-08

### Fixed
- **Test suite green**: Updated stale assertions in test_lammps_probe.py
  - newton "off on" → "off" (LAMMPS 2025+ KOKKOS requirement)
  - package kokkos moved to _generate_package_commands() (before read_data)
- **GPU thread scaling all paths**: Complete coverage for all execution paths
  - Immediate bulk path: passes run_tier to _get_pipeline()
  - Layer path: passes run_tier from protocol_request to _get_layer_pipeline()
  - Build phase: passes run_tier for consistency (no GPU used)

## [00.97.02] - 2026-04-08

### Summary
Performance optimization consolidation release. Combines adaptive dump interval, FF cache improvements, RDF analysis enhancements, and GPU thread scaling into a stable release.

### Highlights
- **Adaptive Dump Interval**: Frame-count based dump interval (production: 50-200 frames, equilibration: 30 frames)
- **FF Cache**: POSIX locking + gzip compression + LRU eviction (500 entries max)
- **RDF Analysis**: skip_fraction 0.3 with provenance tracking
- **GPU Thread Scaling**: Actual atom count based (8/12/16 threads for ≤120k/≤175k/>175k atoms)

## [00.97.01] - 2026-04-08

### Fixed
- **GPU thread scaling**: Use actual_atom_count from build_result instead of tier target_atoms
  - execute_ready_experiment now passes actual atom count for accurate thread scaling
  - _get_pipeline/get_layer_pipeline accept actual_atom_count parameter
- **ParameterCache cross-process cache hit**: Reload index on cache miss
  - get() and has() now reload index under lock when key not found locally
  - Ensures entries added by other workers are visible
- **ProtocolChainAdjuster tier policy injection**: Accept optional tier_policy parameter
  - apply_overrides() uses injected policy instead of hardcoded DEFAULT_TIER_POLICY
  - Ensures consistency with policy used during chain building

## [00.97.00] - 2026-04-08

### Added
- **SamplingConfig**: Adaptive dump interval policy (tier별 production/equilibration target frames)
- **TierConfig.sampling**: Sampling strategy 필드 추가
- **ProtocolChain.sampling_metadata**: Sampling provenance tracking
- **ParameterCache**: POSIX fcntl locking, gzip compression, LRU eviction (MAX_ENTRIES=500)
- **RDF provenance metadata**: skip_fraction, computation_version, frames_total/used/skipped
- **calculate_threads_per_job**: target_atoms parameter for kokkos_gpu scaling (8/12/16 threads)
- **common/pathing.py**: get_ff_cache_path() helper function

### Changed
- RDF/Pair-RDF default skip_fraction: 0.5 → 0.3 (more frames used for analysis)
- kokkos_gpu thread scaling: 8 (≤120k atoms), 12 (≤175k), 16 (>175k)
- ParameterCache: atomic gzip save + legacy JSON fallback read

### Removed
- lammps_probe: nvt_dump_interval, npt_dump_interval keys (replaced by adaptive sampling)
- lammps_input: probe dump interval override logic

## [Unreleased]

### Added
- Force field registry에 UFF 기반 element fallback 추가 (`P`, `Si`, `Al` explicit 보강 포함)
- additive MOL validator CLI 추가 및 startup warning-only prevalidation 연결
- `CrystalSourceType`, `CrystalTemplateSpec` 스키마 추가 (크리스탈 템플릿 라이브러리 도메인 지원)
- `LayerSpec.crystal_template_id` optional 필드 추가 (기존 `crystal` 스펙과 하위호환 유지)
- `CrystalCellMode` enum 추가 (`native_skew`, `orthogonalized`)
- `CrystalLayerSpec.cell_mode` 필드 추가 (기본값: `orthogonalized`)
- `CrystalMaterial` 확장: `MgO`, `Fe2O3`, `MgCO3` 추가 (문헌 기반 크리스탈 템플릿 지원)
- `CrystalMaterial` 확장: `CaO`, `TiO2`, `ZnO`, `NaCl`, `KCl`, `Al`, `Fe`, `Cu`, `Ni` 추가 (범용 결정 구조 프리셋 지원)
- `AmorphousBoundaryMode`, `AmorphousComponentSpec`, `AmorphousCellSpec` 스키마 추가 (Amorphous Cell 라이브러리/안정화 지원)
- `LayerSpec.amorphous_cell_id` optional 필드 추가 (향후 layered structure 조합 준비)
- `LayerSourceType`, `LayerStackItem`, `LayerStackSpec` 스키마 추가 (Single Job Layered Structure 조합 도메인 지원)
- `BuildRequest.prebuilt_data_file_path` optional 필드 추가 (외부/조합 데이터 기반 실행 경로)
- `CompiledStage`, `CompiledExecutionPlan` 스키마 추가 (프로토콜 스테이지 실행 계획 영속화)

### Changed
- additive `mol_id`를 canonical ID로 유지하도록 molecule composition 빌드 경로 수정
- additive `structure_file` 상대 경로를 `data/molecules` 기준으로 일관 해석
- `AmorphousCellSpec` 단일 비바인더 컴포넌트 모델로 정리: `component_mol_id` + `initial_density`를 기본으로 사용, 기존 `components`/`target_density`는 하위호환 alias로 유지
- `LayerSpec.stack_spec` optional 필드 추가 (기존 시나리오 기반 필드와 하위호환 유지)
- Batch Job Binder Cell 도메인 네이밍 정합화: `campaign` 계열 식별자를 `batch_job_binder_cell` 중심으로 정리 (API/오케스트레이터/큐/테스트/문서)
- 프로토콜 스테이지 관리 경로를 `stage_requests -> compiled_execution_plan -> progress` 기준으로 통합
- GPU/진행률 표시는 persisted plan과 기존 fallback을 함께 지원하도록 정리
- 프로토콜 stage catalog API와 프론트 렌더링을 metadata 기반으로 정리

## [0.90.01] - 2026-02-14

### Added (Phase 8: Continuous Learning / MLOps)
- **MLPolicy 확장**: `drift_detection`, `model_comparison`, `calibration`, `continuous_learning` 정책 추가
- **MLOps ErrorCode (E10xxx)**: drift/retraining/registry/promotion/rollback/calibration 오류 코드 추가
- **MLOpsError**: MLOps 전용 예외 타입 추가 (`contracts/errors.py`)

## [1.9.0] - 2026-02-14

### Added (v00.80.00 — Phase 7: Additive Debate Policy)
- **DebateConfig**: 멀티 에이전트 첨가제 토론 정책 모델 (`contracts/policies/recommendation_policy.py`)
- **AdditiveScoreWeights**: additive 4D 평가 가중치 모델 (effectiveness/cost_benefit/compatibility/scalability)
- **RecommendationPolicy.debate**: 토론 정책 전역 설정 필드 추가

## [1.8.0] - 2026-02-14

### Added (v00.79.00 — Phase 6: Core Inverse Design)
- **RecommendationPolicy**: EHVI + InverseDesign 정책 Pydantic 모델 (`contracts/policies/recommendation_policy.py`)
- **DEFAULT_RECOMMENDATION_POLICY**: 전역 추천/역설계 정책 인스턴스
- **PropertyTarget / PropertyTargetSet**: 목표 물성 정의 + PG 등급 프리셋 (`recommendation/property_targets.py`)
- **PG 프리셋**: PG_64_22, PG_76_28 + `select_pg_grade()` AASHTO M320 매핑
- **MC-EHVI**: Monte Carlo Expected Hypervolume Improvement 획득 함수 + EI fallback 3조건
- **InverseDesigner**: PG 기반 목표 물성 최적화 오케스트레이터 (`recommendation/inverse_designer.py`)
- **ML→Recommendation 통합**: `api/deps.get_ml_predictor_fn()` 어댑터 + AL workflow 연결
- **API 엔드포인트**: `GET /api/recommendations/inverse/presets`, `POST /api/recommendations/inverse/run`
- **API 스키마**: InverseDesignRequest, InverseDesignResponse, PropertyTargetItem, PGPresetListResponse

### Changed
- `api/main.py`: `_get_al_workflow()`에 ML predictor 연결
- `recommendation/bayesian_optimizer.py`: EHVI acquisition case 추가
- `recommendation/__init__.py`: InverseDesigner, PropertyTarget 등 export 추가

## [1.7.0] - 2026-02-14

### Added (v00.78.01 — Phase 5.1 + 5.2)
- **BatchJobBinderCellSpec 확장**: `additive_types`, `additive_concentrations` 필드 추가 (하위호환)
- **AdditiveBatchJobBinderCellJob**: BatchJobBinderCellJob 확장 — additive_type, additive_concentration, additive_mol_id
- **AdditiveBatchJobBinderCellRunner**: BatchJobBinderCellRunner 상속, full-factorial DOE (additive_type x concentration)
- **additive 메타데이터 전파**: Pipeline.run() → _create_experiment_record() → ExperimentRecord.additive_type/wt/mol_id
- **run_additive_batch_job_binder_cell**: Celery 태스크 (기존 tasks.py에 추가, batch_job_binder_cell 큐)
- **AdditiveEffectivenessAnalyzer**: Welch's t-test 기반 첨가제 효과 분석 (`orchestrator/additive_analyzer.py`)
- **API BatchJobBinderCellRequest 확장**: additive_types, additive_concentrations 필드 추가
- **TargetVariable 확장**: 4→13개 타겟 (viscosity, rdf, tensile, interfacial 등)
- **EnsemblePredictor.save/load**: 앙상블 영속성 구현
- **MultiTargetPredictor**: per-target EnsemblePredictor 관리 + UQ 내장 (`ml/multi_target.py`)
- **UncertaintyEstimator**: 보정 가능한 CI 계산 (`ml/uncertainty.py`)
- **OODDetector**: Mahalanobis 거리 기반 OOD 탐지 (`ml/ood_detector.py`)
- **TargetCorrelation**: 타겟 간 Pearson 상관 분석 (`ml/target_correlation.py`)
- **MLPolicy 확장**: default_ensemble_size, ood_threshold_percentile, uncertainty_ci_level, calibration_min_samples

### Changed
- CeleryJobManager.submit(): additive_type/additive_wt/additive_mol_id 파라미터 추가
- run_simulation 태스크: additive 메타데이터 전달 경로 추가
- ml/__init__.py: Phase 5.2 클래스 export 추가

## [1.6.0] - 2026-02-14

### Added (v00.78.01 — Phase 5.1-prep)
- **FeatureSetVersion enum**: `V1` (11 features), `V2` (24 features) in `contracts/policies/ml_policy.py`
- **MLPolicy**: ML 정책 Pydantic 모델 (feature set 기본값, 재훈련 트리거, additive 샘플 gate)
- **DEFAULT_ML_POLICY**: 전역 ML 정책 인스턴스
- **IFeatureExtractor**: `contracts/interfaces.py`에 ML 특성 추출 Protocol 추가
- **AdditiveFeatureExtractor**: `ml/additive_features.py` — one-hot + 분자 기술자 + 상호작용 특성 (13개)
- **FeatureRegistry**: `ml/feature_registry.py` — V1/V2 특성 목록 SSOT
- **CompositionFeaturesV2**: `ml/feature_store.py` — V1(8) + additive(13) = 21 조성 특성
- **PredictionInputV2**: `ml/predictor.py` — additive 메타데이터 포함 24-element 벡터
- **Predictor 차원 검증**: config.feature_names → _model.n_features_in_ 우선순위 체인
- **DataLoader V2 분기**: feature_set_version + strict_feature_set 파라미터, additive 샘플 gate + fallback
- **normalize_additive_type()**: strip/lower/기호정리 정규화 함수

### Changed
- DataLoader: 특성 상수를 feature_registry에서 import (deprecated alias 유지)

## [1.5.0] - 2026-02-13

### Added (v00.78.01 — Phase 4.3)
- **LayerSpec SSOT 통합**: 6 StrEnum (LayerType, CrystalMaterial, SurfaceOrientation, WaterModel, LayerScenario) + 3 중첩 Pydantic 모델 (CrystalLayerSpec, WaterLayerSpec, BinderLayerConfig) → contracts/schemas.py 단일 정의
- **CrystalMaterial.CITE/CACO3**: StrEnum 별칭으로 기존 6곳 참조 보호
- **model_validator(mode="before")**: flat dict → 구조화된 LayerSpec 역호환 마이그레이션
- **LayerSpec 시나리오 D/E/F**: aged-fresh, water-aged-fresh, binder-binder 지원
- **TensileSpec 보강**: output_interval_steps 필드 추가
- **ProtocolRequest/LAMMPSRunResult 확장**: tensile_spec, layer_spec, interface_area_nm2, original_gap_angstrom (Optional 전방참조 + model_rebuild())
- **tensile_layer 안정화 체인**: minimize → nvt → npt → tensile_pull 4단계
- **ProtocolChain 이중조건 가드**: study_type == LAYER_BULKFF AND tensile_spec.enabled
- **LAMMPS 인장 스크립트**: grip-pull 방식 (setforce + move linear + nvt + stress/strain output)
- **StressStrainParser**: stress_strain_*.dat 파서 (빈파일/1행/컬럼부족 방어)
- **TensileMetricCalculator**: interfacial_tensile_strength, tensile_strength, elastic_modulus, ductility, toughness, work_of_separation
- **W_sep 공식 수정**: `toughness * gap * 0.1` (면적 나눗셈 제거 — stress는 이미 F/A)
- **메트릭 등록**: interfacial_tensile_strength, work_of_separation, ductility, toughness
- **LayerPipelineRunner**: Layer 전용 오케스트레이션 (bulk Pipeline 무수정)
- **run_layer_simulation**: Layer/tensile Celery 태스크
- **builder/layer_spec.py**: re-export 어댑터 전환 (기존 import 호환)

### Changed
- LayerSpec: flat 구조 → 중첩 Pydantic 모델 (CrystalLayerSpec, WaterLayerSpec, BinderLayerConfig)
- LayerBuilder.build(): 시나리오별 라우팅 (A/B/C standard, D/E aged-fresh, F binder-binder)
- MetricCalculator: tensile 메트릭 호출 경로 추가

## [1.4.0] - 2026-02-13

### Added (v00.78.01 — Phase 4.2)
- `GroupPairSpec`, `GroupEnergySpec`: group/group 에너지 분해 스키마 추가
- `BuildResult.molecule_ordering`: 패킹 순서 메타데이터 (그룹 할당용)
- `ProtocolRequest.group_energy_spec`: 프로토콜 요청에 그룹 에너지 설정 (옵셔널)
- `LAMMPSRunResult.group_energy_spec`: 실행 결과에 그룹 에너지 설정 전달
- `GroupAssignmentBuilder`: molecule_ordering → GroupEnergySpec 변환 + mol-ID 검증
- LAMMPS 스크립트: group/group compute 커맨드 주입 + thermo_style 확장 + 조건부 dump mol 컬럼
- Pipeline: build_result → group_energy_spec → protocol → lammps_result 배관 연결
- MetricCalculator: pair-RDF 호출 + E_inter atom_counts 전달 + dump mol 검증 가드
- 인터페이스 메트릭 등록: `e_inter_interface_1`, `e_inter_interface_2`, `e_inter_layer_matrix`

### Changed
- `IProtocolGenerator.generate()` 시그니처 불변 유지 (ProtocolRequest에 옵셔널 필드로 해결)
- 추상 위반 방지: pipeline에서 builder.molecule_db 직접 접근 제거 → BuildResult 경유

## [1.3.0] - 2026-02-13

### Added (v00.78.01 — Phase 4.1)
- `ExperimentRecord`: additive_type, additive_wt, additive_mol_id 필드 추가
- `LayerSpec`: interface_stack_id, grip_mode, layer_boundary_z, aging_state 재현성 필드 추가
- `TensileSpec`: pull_velocity, grip_thickness, max_strain, pull_axis, layer_scenario 파라미터 추가
- `FailurePolicy`: asphalt_density_min/max, physical_density_min/max 범위 필드 추가

### Changed
- `metrics/density.py`: 하드코딩 밀도 상수 → FailurePolicy import로 교체
- `metrics/calculator.py`: 하드코딩 물리적 밀도 범위 → FailurePolicy import로 교체

## [1.2.0] - 2026-02-12

### Added (v00.77.00 ~ v00.77.05)
- **v00.77.05**: DB 경로 해결을 `__file__` 기반 프로젝트 루트로 변경 — CWD 무관 DB 접근 보장
- **v00.77.04**: 자율 실행 계획서 SM-1/SM-2 및 크로스머신 프롬프트 추가
- **v00.77.03**: P3-5 배열 메트릭 저장 연결 (Parquet → DB pointer) + P3-6 Tg 후처리기 구현
- **v00.77.02**: P3-3 메타데이터 전파 수정 + P3-4 Tg 계산기 구현 (bi-linear regression)
- **v00.77.01**: P3-3 점도 산출 파이프라인 구현 — Muller-Plathe RNEMD 기반 end-to-end
- **v00.77.00**: Phase 3 메트릭 완성 — RDF + MSD 구현 + 운영 경로 정확도 보정

### Changed
- `MetricModel.value`: `nullable=True` 적용 (array metric의 value=None 허용)
- `connection.py`: `_resolve_project_root()` 추가, `get_default_url()` 절대경로 해결
- `ArrayMetricStorage` 스키마에 `file_path`, `file_hash`, `shape`, `summary` 필드 확정

### Notes
- Phase 3 Exit Gate 테스트 120 passed (코덱스 검증 확인)
- SQLite `metrics.value` NOT NULL → NULL 마이그레이션 완료

## [1.1.0] - 2026-02-01

### Added (v00.76.00 ~ v00.76.01)
- Phase 2 완료: UI 통일성 개선, E2E Smoke Test 검증
- 코드리뷰 디버깅 + 리팩토링: 제출경로 단일화, 계약 정합성, 입력검증

## [1.0.0] - 2026-01-26

### Added
- Initial schema definitions (MoleculeSpec, MaterialSpec, BuildSpec, RunSpec, etc.)
- Interface contracts (IStructureBuilder, IProtocolGenerator, IMetricCalculator, IExperimentRepository)
- Standard error codes (ContractError, ValidationError, etc.)
- Policy definitions:
  - CompositionConstraints: wt% validation and normalization
  - TierPolicy: run tier definitions and transitions
  - JobBudgetingPolicy: GPU allocation and job limits
  - FailurePolicy: retry strategies and classification
  - StabilizationChain: protocol step definitions
  - MetricsRegistry: metric name/unit enforcement
- Common utilities (pathing, hashing, logging, artifacts, units)

### Notes
- This is the Single Source of Truth (SSOT) for all sessions
- All sessions must import from contracts/ and common/
- Breaking changes require version bump and CHANGELOG update
