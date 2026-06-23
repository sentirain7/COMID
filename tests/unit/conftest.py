"""tests/unit 공통 fixture.

``isolated_db_session``: 전역 DB 상태(init_memory_db/close_db)를 건드리지
않는 완전 격리 in-memory 세션 — 루트 conftest의 ``db_session``(전역 연결
기반)과 이름을 분리해 충돌을 피한다 (R-P2-1).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database.models import Base


@pytest.fixture(autouse=True)
def _isolate_sidecars(tmp_path, monkeypatch):
    """Redirect E_intra and result sidecar write-through to per-test tmp dirs.

    Both write-throughs are enabled by default in production; this keeps unit
    tests from dirtying the real git-tracked ``data/forcefield_artifacts/e_intra/``
    and ``data/result_sidecars/`` directories.
    """
    monkeypatch.setenv("ASPHALT_E_INTRA_SIDECAR_DIR", str(tmp_path / "e_intra_sidecars"))
    monkeypatch.setenv("ASPHALT_RESULT_SIDECAR_DIR", str(tmp_path / "result_sidecars"))


@pytest.fixture
def isolated_db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        yield s
