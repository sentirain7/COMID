"""Structural feature store — mixing layer for V7 training data (P2).

A thin Parquet-backed store that holds 32-feature structural rows together
with per-property labels and **force-field provenance** tags. Its purpose is
to let the V7 challenger train on a mix of:

- ``our_production`` (GAFF2+AM1-BCC) rows — extractable on the fly from the
  experiments DB, but materialised here so they can be mixed; and
- ``mdml_pretrain`` (COMPASS III) rows — *not* in the experiments DB, so the
  store is their only entry point.

The force-field tag is metadata (not a 33rd feature — V7 stays 32-dim), so a
future GAFF2-only model is a one-line ``force_field == 'gaff2_am1bcc'`` filter.

Schema (one row per system):
    <32 STRUCTURAL_FEATURE_NAMES> , label_<target>... , source , force_field ,
    group_key , row_key
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from common.logging import get_logger
from common.pathing import get_project_root

# FF/source 태그는 정책 SSOT(contracts)에서 — 문자열 이중 정의 금지(drift→0건 매칭).
# 본 모듈을 통해 re-export(ingest 스크립트·테스트·challenger가 store에서 import).
from contracts.policies.structural_ml import (
    FF_COMPASS_TAG as FF_COMPASS,
)
from contracts.policies.structural_ml import (
    FF_GAFF2_TAG as FF_GAFF2,
)
from contracts.policies.structural_ml import (
    SOURCE_MDML,
    SOURCE_OUR,
)
from ml.structural_features import STRUCTURAL_FEATURE_NAMES

logger = get_logger("ml.structural_feature_store")

# FF/source 태그 re-export 명시 (ruff가 미사용으로 제거하지 않도록).
__all__ = [
    "FF_COMPASS",
    "FF_GAFF2",
    "SOURCE_MDML",
    "SOURCE_OUR",
    "StoreDataset",
    "StructuralFeatureStore",
]

_META_COLUMNS = ("source", "force_field", "group_key", "row_key")


def _default_store_path() -> Path:
    return get_project_root() / "data" / "ml" / "structural_feature_store"


@dataclass
class StoreDataset:
    """Materialised training view loaded from the store."""

    X: np.ndarray
    y: np.ndarray
    groups: np.ndarray
    sources: list[str]
    force_fields: list[str]
    feature_names: list[str]
    target_name: str

    @property
    def n_samples(self) -> int:
        return len(self.y)


class StructuralFeatureStore:
    """Parquet-backed store of 32-feature rows + labels + FF provenance."""

    def __init__(self, store_path: Path | None = None):
        self.store_path = store_path or _default_store_path()

    def _file_for_source(self, source: str) -> Path:
        return self.store_path / f"{source}.parquet"

    @staticmethod
    def make_row(
        *,
        features: dict[str, float],
        labels: dict[str, float],
        source: str,
        force_field: str,
        group_key: str,
        row_key: str,
    ) -> dict[str, Any]:
        """Build a canonical store row (validates the 32-feature contract)."""
        missing = [n for n in STRUCTURAL_FEATURE_NAMES if n not in features]
        if missing:
            raise ValueError(f"row missing structural features: {missing[:3]}...")
        row: dict[str, Any] = {n: float(features[n]) for n in STRUCTURAL_FEATURE_NAMES}
        for target, value in labels.items():
            if value is not None:
                row[f"label_{target}"] = float(value)
        row["source"] = source
        row["force_field"] = force_field
        row["group_key"] = group_key
        row["row_key"] = row_key
        return row

    @contextmanager
    def _source_lock(self, source: str):
        """Per-source advisory file lock (멀티 워커 read-modify-write 직렬화).

        POSIX ``fcntl.flock`` — the project documentation "원자적/전역 락 없는 할당 금지" 철학을
        feature store에도 적용. 비POSIX/실패 시 best-effort(락 없이 진행).
        """
        self.store_path.mkdir(parents=True, exist_ok=True)
        lock_path = self.store_path / f"{source}.lock"
        fd = None
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
            try:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass  # best-effort
            yield
        finally:
            if fd is not None:
                try:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_UN)
                except (ImportError, OSError):
                    pass
                os.close(fd)

    @staticmethod
    def _read_parquet_safe(path: Path) -> Any | None:
        """손상/부분 parquet 읽기 격리 — 실패 시 None+경고 (전체 중단 방지)."""
        import pandas as pd

        try:
            return pd.read_parquet(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("structural store: corrupt/unreadable parquet %s: %s", path.name, exc)
            return None

    def upsert(self, rows: list[dict[str, Any]], *, source: str) -> int:
        """Insert/replace rows for a source (idempotent by ``row_key``).

        Atomic + locked: read-modify-write를 source 락으로 직렬화하고, tmp 파일에
        쓴 뒤 ``os.replace``로 원자 교체 — 동시 ingest 시 lost update / 부분 손상
        파일을 방지.
        """
        import pandas as pd

        if not rows:
            return 0
        path = self._file_for_source(source)
        new_df = pd.DataFrame(rows)
        with self._source_lock(source):
            existing = self._read_parquet_safe(path) if path.exists() else None
            if existing is not None:
                merged = pd.concat([existing, new_df], ignore_index=True)
            else:
                merged = new_df
            merged = merged.drop_duplicates(subset=["row_key"], keep="last")
            tmp = path.with_suffix(".parquet.tmp")
            merged.to_parquet(tmp, index=False)
            os.replace(tmp, path)  # atomic
        logger.info("structural store upsert: %d rows → %s", len(new_df), path.name)
        return len(new_df)

    def load_dataset(
        self,
        target: str,
        *,
        sources: list[str] | None = None,
        force_fields: list[str] | None = None,
    ) -> StoreDataset | None:
        """Load a training view for ``target`` across sources/force fields.

        Args:
            target: Property name (e.g. 'density'); rows must have label_<target>.
            sources: Restrict to these sources (default: all present).
            force_fields: Restrict to these FFs (default: all present).

        Returns:
            StoreDataset or None when no rows match.
        """
        import pandas as pd

        if not self.store_path.exists():
            return None
        label_col = f"label_{target}"
        frames: list[Any] = []
        wanted = sources or [p.stem for p in self.store_path.glob("*.parquet")]
        for source in wanted:
            path = self._file_for_source(source)
            if not path.exists():
                continue
            df = self._read_parquet_safe(path)
            if df is None or label_col not in df.columns:
                continue
            df = df[df[label_col].notna()]
            if force_fields is not None:
                df = df[df["force_field"].isin(force_fields)]
            if not df.empty:
                frames.append(df)
        if not frames:
            return None
        data = pd.concat(frames, ignore_index=True)
        X = data[list(STRUCTURAL_FEATURE_NAMES)].to_numpy(dtype=float)
        y = data[label_col].to_numpy(dtype=float)
        groups = data["group_key"].astype(str).to_numpy()
        return StoreDataset(
            X=X,
            y=y,
            groups=groups,
            sources=data["source"].astype(str).tolist(),
            force_fields=data["force_field"].astype(str).tolist(),
            feature_names=list(STRUCTURAL_FEATURE_NAMES),
            target_name=target,
        )

    def ingest_experiments(
        self,
        session: Any,
        *,
        targets: list[str],
        ff_type: str = "bulk_ff_gaff2",
        run_tiers: list[str] | None = None,
    ) -> int:
        """Materialise our completed GAFF2 experiments into the store.

        Each experiment becomes one row (32 structural features computed via
        the same StructuralFeatureExtractor as serving) tagged
        ``source=our_production`` / ``force_field=gaff2_am1bcc``, with whatever
        of the requested ``targets`` have metric values.

        Args:
            session: SQLAlchemy session.
            targets: Metric names to capture as labels (e.g. ['density']).
            ff_type: Experiment force-field filter.
            run_tiers: Tiers to include (default screening/confirm).

        Returns:
            Number of rows written.
        """
        from database.models import ExperimentModel, MetricModel
        from ml.structural_features import RDKIT_AVAILABLE, StructuralFeatureExtractor

        if not RDKIT_AVAILABLE:
            logger.warning("RDKit unavailable — cannot ingest experiments to store")
            return 0
        tiers = run_tiers or ["screening", "confirm"]
        experiments = (
            session.query(ExperimentModel)
            .filter(
                ExperimentModel.status == "completed",
                ExperimentModel.ff_type == ff_type,
                ExperimentModel.run_tier.in_(tiers),
                ExperimentModel.study_type == "bulk",
            )
            .all()
        )
        extractor = StructuralFeatureExtractor()
        rows: list[dict[str, Any]] = []
        for exp in experiments:
            temperature = float(exp.temperature_K or 298.0)
            feats = extractor.extract_from_db(session, exp.id, temperature)
            if feats is None:
                continue
            metrics = {
                m.metric_name: m.value
                for m in session.query(
                    MetricModel.metric_name, MetricModel.value
                ).filter(
                    MetricModel.experiment_id == exp.id,
                    MetricModel.metric_name.in_(targets),
                    MetricModel.value.isnot(None),
                )
            }
            if not metrics:
                continue
            rows.append(
                self.make_row(
                    features=feats,
                    labels=metrics,
                    source=SOURCE_OUR,
                    force_field=FF_GAFF2,
                    group_key=str(exp.additive_mol_id or exp.additive_type or "none"),
                    row_key=f"our::{exp.exp_id}",
                )
            )
        return self.upsert(rows, source=SOURCE_OUR)

    def summary(self) -> dict[str, Any]:
        """Row counts by source and available labels (diagnostics)."""

        out: dict[str, Any] = {"sources": {}, "store_path": str(self.store_path)}
        if not self.store_path.exists():
            return out
        for path in sorted(self.store_path.glob("*.parquet")):
            df = self._read_parquet_safe(path)
            if df is None:
                continue
            labels = [c[len("label_") :] for c in df.columns if c.startswith("label_")]
            out["sources"][path.stem] = {
                "rows": int(len(df)),
                "labels": labels,
                "force_fields": sorted(df["force_field"].astype(str).unique().tolist()),
            }
        return out
