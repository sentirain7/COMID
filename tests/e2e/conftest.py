"""Shared E2E fixtures (docs/WORKFLOW_VERIFICATION_PLAN.md §6 Level 0~2, §8).

신규 두 파일(``test_workflow_entrypoints.py`` Level 0, ``test_build_dry_run_matrix.py``
Level 1)이 공통으로 사용하는 격리 client / 시드 / 상수를 한 곳에 모은 것이다.

기존 e2e 파일들(``test_source_lineage_chain.py``, ``test_submission_db_lineage.py``,
``test_recovery_and_idempotency.py``, ``test_data_products.py``,
``test_ml_recommendation_consumers.py``)이 각자 중복 보유하던 패턴 —

  * monkeypatch + ``tmp_path`` + ``ASPHALT_PROJECT_ROOT`` 격리
  * no-op lifespan (startup side-effect 회피)
  * ``close_db()`` + ``reset_settings()`` + 싱글톤 캐시 클리어 (멀티테스트 DB 격리)
  * ``FakeJobManager`` (Celery/GPU 제출 경계)
  * 완료 실험 + 메트릭 시드 (metric 은 ``experiment_id`` 정수 FK 로 조인)

— 를 재사용 가능한 fixture/factory 로 추출한다.

**중요(점진적 도입):** 기존 e2e 파일은 자체 fixture(같은 이름이라도 클래스 메서드
fixture)를 그대로 유지한다. 여기 정의된 fixture 들은 별도 이름(``e2e_client``,
``isolated_e2e_client`` 등)을 사용하므로 기존 모듈 fixture 와 충돌하지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

TestClient = pytest.importorskip(
    "fastapi.testclient",
    reason="FastAPI not installed",
).TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# 대표 상수 (representative molecules / temperatures)
# ---------------------------------------------------------------------------

# Curated GAFF2 artifact 가 base-id 그대로 존재하는 단일 분자들 — amorphous /
# single-molecule dry-run 의 FF eligibility fail-closed gate 를 실제 로직 그대로
# 통과한다 (aging-prefix 분자는 base-id 정규화 때문에 gate 에 걸림).
REPRESENTATIVE_SINGLE_MOLECULES: tuple[str, ...] = (
    "U-AS-Thio",
    "U-RE-Pyrid",
    "U-AR-PHPN",
    "U-SA-Squalane",
)

# 대표 바인더 (batch binder-cell 매트릭스용).
REPRESENTATIVE_BINDERS: tuple[str, ...] = ("AAA1", "AAK1", "AAM1")

# 온도 SSOT: contracts/policies/temperature.py.
#   - 축약 샘플(213/293/433): 전체 sweep 의 양끝 + 중앙
#   - 경계 샘플(223/313/423): UI selectable-only 온도
SAMPLE_TEMPERATURES_K: tuple[float, ...] = (213.0, 293.0, 433.0)
BOUNDARY_TEMPERATURES_K: tuple[float, ...] = (223.0, 313.0, 423.0)

# 노화 상태 (aging axis).
AGING_STATES: tuple[str, ...] = ("non_aging", "short_aging", "long_aging")

NAMESPACE = "bulk_ff_gaff2"
FF_TYPE = "bulk_ff_gaff2"


# ---------------------------------------------------------------------------
# Celery / GPU 제출 경계 mock
# ---------------------------------------------------------------------------


class FakeJobManager:
    """Celery/GPU 실행 경계 mock: 제출 호출만 기록하고 task id 를 부여한다.

    기존 e2e 파일들의 ``_FakeJobManager`` 와 동일 인터페이스(submit / get_task_id /
    cancel_job).
    """

    def __init__(self) -> None:
        self.submit_calls: list[dict] = []

    def submit(self, **kwargs):
        self.submit_calls.append(kwargs)
        return f"job-e2e-{len(self.submit_calls):03d}"

    def get_task_id(self, job_id):
        return f"task-{job_id}"

    def cancel_job(self, job_id):  # pragma: no cover - defensive
        return None


def _clear_singleton_caches() -> None:
    """Molecule DB / aging config / interface catalog 싱글톤 캐시 클리어.

    멀티테스트에서 이전 테스트의 ``ASPHALT_PROJECT_ROOT`` 로 캐시된 분자 DB 가
    다음 테스트로 새지 않도록 한다 (test_source_lineage_chain 패턴).
    """
    import api.deps as api_deps
    from features.interface_molecules.catalog import clear_molecule_info_cache

    api_deps.get_molecule_db.cache_clear()
    api_deps.get_aging_config.cache_clear()
    clear_molecule_info_cache()


# ---------------------------------------------------------------------------
# Autouse isolation guard (defense-in-depth)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _e2e_isolation_guard() -> Generator[None, None, None]:
    """Guarantee env/DB/cache isolation around every e2e test.

    Individual e2e modules manage their own ``ASPHALT_PROJECT_ROOT`` +
    ``tmp_path`` setup, but a test that crashes mid-fixture (or a module
    that reads the env at import) could otherwise leak the tmp-dir root
    into a sibling test and make it read a non-existent molecule library
    (the failure mode that the removed ``test_asphalt_simulation.py``
    exhibited). This autouse guard snapshots and restores the env var and
    clears the DB engine + singleton caches on both sides, so pollution
    cannot cross test boundaries regardless of per-module fixtures.
    """
    import os

    _saved_root = os.environ.get("ASPHALT_PROJECT_ROOT")

    def _cleanup() -> None:
        try:
            from database.connection import close_db

            close_db()
        except Exception:
            pass
        try:
            from config.settings import reset_settings

            reset_settings()
        except Exception:
            pass
        try:
            _clear_singleton_caches()
        except Exception:
            pass

    _cleanup()
    try:
        yield
    finally:
        _cleanup()
        # Restore the env var to its pre-test value so a leaked tmp root
        # from this test does not bleed into the next one.
        if _saved_root is None:
            os.environ.pop("ASPHALT_PROJECT_ROOT", None)
        else:
            os.environ["ASPHALT_PROJECT_ROOT"] = _saved_root


# ---------------------------------------------------------------------------
# Isolated client fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def e2e_client(monkeypatch, tmp_path) -> Generator[TestClient, None, None]:
    """격리된 TestClient (분자 라이브러리 + curated FF artifact 복사 포함).

    라우터 → service → repository → SQLite 경로는 전부 실제로 탄다.
    Celery/GPU 제출 경계(``api.deps.get_job_manager``)와 dashboard GPU 조회만 mock.

    Yields:
        ``TestClient`` — ``client.fake_job_manager`` 로 제출 호출 기록 접근 가능.
    """
    # 분자 라이브러리 SSOT 복사 (MW lookup / MOL 파일 / FF lookup 용).
    molecules_src = REPO_ROOT / "data" / "molecules"
    if not molecules_src.exists():  # pragma: no cover - repo layout guard
        pytest.skip("data/molecules library not found in repository")
    import shutil

    shutil.copytree(
        molecules_src,
        tmp_path / "data" / "molecules",
        ignore=shutil.ignore_patterns("*.lock", "crystal_structures.yaml"),
    )
    # Curated FF artifact store 복사: fail-closed FF eligibility gate 를 실제 로직
    # 그대로 통과시키기 위함 (organic_curated_artifact route).
    ff_artifacts_src = REPO_ROOT / "data" / "forcefield_artifacts"
    if ff_artifacts_src.exists():
        shutil.copytree(ff_artifacts_src, tmp_path / "data" / "forcefield_artifacts")

    from config.settings import reset_settings
    from database.connection import close_db

    monkeypatch.setenv("ASPHALT_PROJECT_ROOT", str(tmp_path))
    db_path = tmp_path / "test_e2e_shared.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    fake_job_manager = FakeJobManager()
    monkeypatch.setattr("api.deps.get_job_manager", lambda: fake_job_manager)
    monkeypatch.setattr(
        "config.dashboard_settings.load_dashboard_settings",
        lambda: {"selected_gpus": []},
    )

    close_db()
    reset_settings()
    _clear_singleton_caches()

    from api.application import app

    @asynccontextmanager
    async def _lifespan(_app):
        yield

    app.router.lifespan_context = _lifespan
    with TestClient(app, raise_server_exceptions=False) as client:
        client.fake_job_manager = fake_job_manager  # type: ignore[attr-defined]
        client.project_root = tmp_path  # type: ignore[attr-defined]
        yield client

    close_db()
    reset_settings()
    _clear_singleton_caches()


# ---------------------------------------------------------------------------
# Completed-experiment factory
# ---------------------------------------------------------------------------


def _build_experiment(exp_id: str, **overrides):
    """Build a completed bulk-ff ``ExperimentModel`` row (request-shaped defaults)."""
    from database.models import ExperimentModel

    fields = {
        "exp_id": exp_id,
        "run_tier": "screening",
        "ff_type": FF_TYPE,
        "study_type": "bulk",
        "status": "completed",
        "comp_asphaltene_wt": 20.0,
        "comp_resin_wt": 30.0,
        "comp_aromatic_wt": 35.0,
        "comp_saturate_wt": 15.0,
        "composition_error_l1": 0.0,
        "target_atoms": 100000,
        "actual_atoms": 99000,
        "temperature_K": 298.0,
        "pressure_atm": 1.0,
        "seed": 1,
        "created_at": datetime.now(UTC),
    }
    fields.update(overrides)
    return ExperimentModel(**fields)


@pytest.fixture
def seed_completed_experiment() -> Callable[..., str]:
    """Factory: 완료 실험 1개 + scalar 메트릭을 DB 에 시드한다.

    metric 은 ``MetricModel.experiment`` 관계가 사용하는 정수 ``experiment_id`` FK 로
    링크된다 (denormalized ``exp_id`` 도 함께 채워 metric_repo / data_loader 양쪽
    경로를 모두 만족). FK 미설정 시 data_loader 가 metric-less 실험으로 보고 skip 한다.

    Returns:
        ``(exp_id=..., *, metrics={name: (value, unit)}, **exp_overrides) -> exp_id``
        호출 가능한 factory. ``metrics`` 미지정 시 density+CED 기본 번들을 시드한다.
    """
    from database.connection import session_scope
    from database.models import MetricModel

    counter = {"n": 0}

    def _factory(
        exp_id: str | None = None,
        *,
        metrics: dict[str, tuple[float, str]] | None = None,
        **exp_overrides,
    ) -> str:
        counter["n"] += 1
        if exp_id is None:
            exp_id = f"e2e_seed_exp_{counter['n']:03d}"
        if metrics is None:
            metrics = {
                "density": (1.01, "g/cm3"),
                "cohesive_energy_density": (300.0, "MJ/m3"),
            }

        with session_scope() as session:
            exp = _build_experiment(exp_id, **exp_overrides)
            session.add(exp)
            session.flush()  # populate exp.id for the metric FK link
            for name, (value, unit) in metrics.items():
                session.add(
                    MetricModel(
                        experiment_id=exp.id,
                        exp_id=exp.exp_id,
                        metric_name=name,
                        namespace=NAMESPACE,
                        value=value,
                        unit=unit,
                        created_at=datetime.now(UTC),
                    )
                )
            session.commit()
        return exp_id

    return _factory
