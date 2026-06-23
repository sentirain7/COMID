================================================================================
        COMID - COmplex Multiphase Integrated Dynamics
                              v0.99.01
================================================================================

(English version: README.txt)


프로젝트 개요
--------------------------------------------------------------------------------
COMID는 복합 다상(multiphase) 재료의 분자동역학(MD) 시뮬레이션을 단일 재현 가능 파이프라인으로
자동화하는 오픈소스 플랫폼이다. 기존에 수작업으로 결합하던 도구 체인(Packmol /
antechamber / LAMMPS / 파서 / 분석)을 단일 SSOT(single-source-of-truth)
아키텍처로 통합하여, 조성 명세(SARA + 첨가제)로부터 벌크 물성을 결정론적으로
산출한다. 모든 결정은 해시 고정(hash-pinned)으로 재현성과 감사가능성을 보장한다.

2단계 재현성 경계:
  - Reviewable Core (LAMMPS-free): FF 할당, 토폴로지 조립, 프로토콜 생성,
    메트릭 계산을 GPU/LAMMPS 없이 수 분 내 실행. 전체 결정 로직을 특수 하드웨어
    없이 검증 가능.
  - Execution Backend (선택): GPU LAMMPS 실행, Packmol 패킹, antechamber 전하
    도출은 subprocess로 격리. 평가/리뷰 시 필수가 아님.

(COMID는 NACMID로 개발되던 아스팔트 바인더 MD/ML 에이전트를 기반으로 한다.)


현재 기능 (Stable Core - 벌크 MD 자동화)
--------------------------------------------------------------------------------
[구조 생성]
  - SARA 분자 라이브러리: 정의 바인더 AAA1 / AAK1 / AAM1, 시스템 크기
    X1 / X2 / X3 = 72 / 144 / 216 분자 (Li & Greenfield 2014 기준)
  - 노화 상태: non_aging(U-) / short_aging(S-) / long_aging(L-)
    (Saturate는 노화 구조 없음 -> non_aging fallback)
  - SARA 분자 12종(Saturate 2, Aromatic 2, Resin 5, Asphaltene 3) +
    첨가제 라이브러리(SBS, SiO2, NanoClay, Lignin, PPA, Sasobit, CRM,
    Graphine, CNT, Polyethylene 등)
  - Packmol 패킹 + 수렴 게이트(고리 관통 검출, 저밀도 초기화) + 실패 시 재시도

[Force Field - 결정론적 라우팅 (선택 아님)]
  - 분자 metadata 기반 typing_router가 5개 route 중 하나로 결정론적 매핑:
      organic_curated_artifact : GAFF2 + AM1-BCC (antechamber) -- 유일한 활성
                                 organic route. baseline -> sqm_robust 자동
                                 에스컬레이션, 영구 실패 시 fail-closed
      inorganic_profile        : INTERFACE FF Lennard-Jones (Heinz 2013) +
                                 소재별 문헌 전하(CLAYFF 계열 / Raiteri-Gale /
                                 formal ionic), Lorentz-Berthelot mixing
      water_model              : TIP3P
      ionic_profile            : Joung-Cheatham / Li-Merz (운영자 게이트)
      blocked                  : fail-closed (즉시 차단)
  - fragment_fallback (3차 폴백): AM1 SCF 비수렴 중성 CHONS 분자(곡면 CNT 등)를
    canonical GAFF2 bonded(dihedral 포함) + AM1-BCC 참조 전하로 파라미터화.
    거버넌스 research_only (ML 데이터셋/제출에서 firewall 격리)
  - FF 거버넌스: ValidationLevel = validated / research_only / blocked
  - 개별 분자 FF 아티팩트와 E_intra는 git-추적 사이드카로 머신 간 공유

[시뮬레이션 / 프로토콜]
  - Jinja2 기반 LAMMPS 입력 스크립트 생성
  - pair_style lj/cut/coul/long + PPPM 장거리 정전기 (kspace pppm)
  - Study Type: BULK ("p p p", NPT iso)
  - Run Tier (선형 사다리가 아니라 조건부 선택/트리거):
    screening / confirm / viscosity
  - 안정화 체인: minimize -> NVT -> NPT (-> 점도 시 NEMD)
  - 정책 기반 실패 복구: overlap -> change_seed, 압력/에너지 발산 -> reduce_dt

[메트릭 - 벌크 물성 7종]
  - density                          (NPT 평균)
  - cohesive_energy_density          (단일분자 vacuum E_intra 빼기식)
  - bulk_modulus                     (NPT 체적 요동)
  - glass_transition_temperature_k   (bilinear fit + bootstrap CI)
  - viscosity                        (NEMD)
  - rdf_first_peak / coordination_number (RDF)
  - msd_diffusion_coefficient        (MSD)
  - 배열 메트릭(Parquet): rdf_curve, msd_curve, density_profile, thermo_log
  - 모든 메트릭은 DEFAULT_METRICS_REGISTRY(SSOT)로 검증

[오케스트레이션 / GPU]
  - Celery + Redis 분산 작업 큐
  - GPUService: 원자적 전역 락(fcntl) + 단일 트랜잭션으로 GPU 할당 직렬화
    (1잡=1슬롯 불변량)
  - MPS 다중잡 co-location: GPU당 3슬롯
  - 하드웨어 UUID 라우팅 (비연속 인덱스 허용), 부적격 GPU(<32GB, 예: RTX 3050)는
    할당에서 하드 배제
  - 3-풀 워커 분리: gpu@ (시뮬레이션 GPU 잡) / control@ (스케줄러·복구 등 제어
    평면) / cpu(build)@ (Packmol 빌드 + 메트릭 + CPU 후처리)
  - 해시 고정 재현성: plan_hash, provenance, 결정론적 시딩
  - 결과 사이드카 write-through/import로 머신 간 결과 DB 공유(곡선 parquet 추적)

[인터페이스]
  - FastAPI REST API (REST 전용, GraphQL 없음)
  - React + Vite 웹 대시보드, React Query 폴링 (WebSocket 구독 없음)
  - 영문 전용 UI


향후 개발 (Roadmap)
--------------------------------------------------------------------------------
아래 기능은 코드베이스에 존재하나 향후 개발 트랙으로 분류한다. 정량 검증 및/또는
기본 활성화가 진행 중이며, 위의 안정 벌크-MD 코어에는 포함되지 않는다.

[다층 / 계면 구조]
  - 바인더-결정 계면 생성 (study type LAYER_BULKFF, "p p f")
  - INTERFACE FF (Heinz 2013) + 광물 전하 카탈로그(CLAYFF / Raiteri-Gale /
    formal-ionic); CPU rerun으로 장거리 Coulomb 복원
  - 계면 / 역학 물성: work_of_separation, interfacial_tensile_strength,
    tensile_strength, elastic_modulus (replicate mean +/- SE)
  - 상태: 구현됨; 계면 물성 정량 검증 진행 중

[기계학습 물성 예측]
  - V7 구조 기반 피처셋: 32개 = RDKit descriptor 10종을 조성가중
    mean/sum/std로 집계(30) + 시스템 2종(분자 fragment 수, 온도)
  - 물성별 XGBoost vs RandomForest 경쟁 학습 (물성마다 우승 모델 채택)
  - Group-aware holdout (additive_mol_id 기반 -> 첨가제 누설 방지)
  - viscosity / MSD는 log 변환, 평가는 원 스케일
  - OOD / 불확실성 플래그, champion-challenger 모델 레지스트리
  - 내부 데이터 전용(GAFF2) 기본 학습, Parquet 피처 스토어
  - opt-in 실시간 재학습 (기본 OFF)

[역설계 - 조성 추천 (ML 기반)]
  - 베이지안 최적화: acquisition EI / UCB / EHVI / PI (기본 auto)
  - Pareto front 추출, FeasibilityScout 사전 달성가능성 진단(opt-in),
    결정론적 닫힌 루프(opt-in, 기본 OFF)
  - 목표는 물성 타겟 전용 (점도/밀도/CED/work_of_separation 등 직접 명시)
  - 후보 = (binder_type, additive_type, additive_wt), structure_size 입력,
    정방향 batch binder cell 경로를 SSOT로 재사용
  - Stateless 파이프라인: plan(plan_hash) -> approve -> progress -> results -> loop
  - 수분손상 트랙: wet/dry 계면 페어 + 에너지비(ER) 판정
  - 비고: BO 스크리닝이 위 ML 예측기에 의존

[ReaxFF 검증 트랙]
  - 반응성 force field 검증 (validation tier, dt 0.5 fs, QEq)


요구 사항
--------------------------------------------------------------------------------
  Python       >= 3.11 (3.12 권장)
  conda env    environment.yml 제공

  [Reviewable Core 만] Linux + Python + RDKit (GPU 불필요)

  [전체 실행 시 추가]
  LAMMPS       22 Jul 2025 커스텀 빌드 (KOKKOS + CUDA + OpenMP + cuFFT)
               .env: LAMMPS_EXECUTABLE, LAMMPS_GPU_PACKAGE=kokkos
  Packmol      구조 패킹
  AmberTools   antechamber / parmchk2 / tleap (GAFF2/AM1-BCC 파라미터화)
  Redis        >= 6 (Celery broker)
  DB           SQLite (개발/단일머신) / PostgreSQL >= 14 (다중머신)


설치
--------------------------------------------------------------------------------
  git clone <repository-url>
  cd COMID

  # 원커맨드 부트스트랩. conda 없으면 자동 설치 -> 환경 생성 -> 패키지 설치 ->
  # .env 스캐폴드 -> 코어 검증을 의존성 순서대로 수행.
  ./install.sh                 # Reviewable Core (GPU/LAMMPS 불필요)
  ./install.sh --full          # + GPU LAMMPS 빌드 (Execution Backend)
  ./install.sh --extras ml     # pip extras 선택 (기본: all)

  conda activate asphalt_env

  ./install.sh 가 하는 일 (순서대로):
    1. conda (Miniforge)  - 없으면 ~/miniforge3에 자동 설치
    2. environment.yml로 conda 환경 생성
       (rdkit, ambertools, numpy, scipy, xgboost ... conda-forge가 과학 스택의
        순서/ABI를 자동 해결)
    3. pip install -e ".[all]"        (COMID 패키지 본체)
    4. .env.example -> .env 스캐폴드
    5. (--full 일 때만) scripts/install_lammps.sh로 GPU LAMMPS 빌드
    6. Reviewable Core import 검증

  수동 / 단계별 설치 (동등, 선호 시):
    conda env create -f environment.yml && conda activate asphalt_env
    pip install -e ".[all]"           # 또는 ".[ml]" (reviewable core + ML)
    cp .env.example .env              # 이후 머신에 맞게 편집
    scripts/install_lammps.sh         # 핀고정 GPU LAMMPS (stable_22Jul2025,
                                      #   KOKKOS+CUDA+cuFFT; GPU arch 자동 감지,
                                      #   LAMMPS_EXECUTABLE를 .env에 자동 기록)

  # 실행 시 항상 PYTHONPATH=src:packages 필요


실행
--------------------------------------------------------------------------------
  ./start_all.sh            # 전체 서비스 기동
                            #   Redis + FastAPI(:8000) + React(:5173)
                            #   + Celery 워커(gpu@/control@/build@) + MPS
  ./start_all.sh --dev      # 개발 모드(auto-reload)
  ./start_all.sh --status   # 서비스 상태 확인
  ./start_all.sh --stop     # 전체 정지
  ./start_all.sh --check    # 의존성만 점검
  ./start_all.sh --verify   # 모듈 import만 검증

  # LAMMPS-free dry run (코어 로직만, GPU 불필요)
  PYTHONPATH=src:packages python scripts/run_inverse_pipeline_smoke.py


디렉토리 구조
--------------------------------------------------------------------------------
  src/
    contracts/      스키마 + 정책 정의 (SSOT, 수정 금지)
    common/         공용 유틸리티 (pathing/hashing/logging, 수정 금지)
    builder/        구조 생성 (Packmol, 분자 DB)
    forcefield/     FF 파라미터 관리 (GAFF2/AM1-BCC, INTERFACE FF, fragment_fallback)
    protocols/      LAMMPS 입력 스크립트 생성 (Jinja2)
    parsers/        로그/덤프 파싱
    metrics/        물성 계산 (density, CED, Tg, bulk_modulus 등)
    database/       SQLite/PostgreSQL 연동 (SQLAlchemy ORM)
    orchestrator/   파이프라인 조율 (celery_job_manager, gpu_service)
    monitoring/     GPU 감지/통계 (nvidia-smi, gpu_collector)
    config/         Pydantic Settings 환경 설정
    api/            FastAPI REST 엔드포인트
    templates/      LAMMPS Jinja2 템플릿
    ml/             구조 기반 ML 예측 (V7)               [향후 개발]
    recommendation/ 역설계 엔진 (BO, Pareto)             [향후 개발]
    validation/     ReaxFF 검증 트랙                     [향후 개발]
    features/       도메인별 Feature 모듈 (역설계 파이프라인 등)

  data/
    molecules/      SARA + 첨가제 분자 라이브러리
    forcefields/    광물 전하/LJ 카탈로그
    forcefield_artifacts/  생성된 GAFF2 아티팩트 + E_intra 사이드카

  frontend/
    src/            React + Vite 웹 대시보드

  docs/
    USER_MANUAL.md  (현재 Stable Core 전체 사용자 매뉴얼)


테스트
--------------------------------------------------------------------------------
  ./run_tests.sh              # 전체 테스트
  pytest tests/unit/ -v       # 단위 테스트 (3,000건 이상, LAMMPS 불필요)
  pytest tests/e2e/ -v        # E2E 테스트 (Level 0~7; 대부분 LAMMPS 불필요,
                              #             실 MD smoke만 GPU LAMMPS 필요)
  ruff check . && ruff format .   # 린트/포맷


문서
--------------------------------------------------------------------------------
  docs/USER_MANUAL.md      전체 사용자 매뉴얼 — 설치, 분자 라이브러리,
                           단일분자/바인더/배치 워크플로우, FF 결정,
                           시뮬레이션 프로토콜, 메트릭, REST API, 트러블슈팅.
                           (현재 Stable Core 기준; 향후 트랙은 위 '향후 개발' 참조)


라이선스
--------------------------------------------------------------------------------
  MIT License

  외부 GPL 도구(LAMMPS, AmberTools, Packmol)는 subprocess(명령행)로 호출만 하며
  본 패키지에 링크/재배포하지 않음. Python 의존성(RDKit, scikit-learn, XGBoost,
  SQLAlchemy, FastAPI, Celery 등)은 permissive 라이선스로 MIT 호환.

================================================================================
