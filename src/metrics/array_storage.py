"""
Array metric storage using Parquet format.

Provides efficient storage for time series and array-based
metrics like RDF, MSD trajectories, etc.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from common.logging import get_logger
from common.pathing import DEFAULT_ARRAYS_DIR, get_array_storage_path, get_project_root
from contracts.interfaces import AbstractArrayStorage
from contracts.schemas import ArrayMetricStorage

logger = get_logger("metrics.array_storage")

# Optional pyarrow/parquet import
try:
    import pyarrow as pa  # type: ignore[import-untyped]
    import pyarrow.parquet as pq  # type: ignore[import-untyped]

    HAS_PARQUET = True
except ImportError:
    HAS_PARQUET = False


class ArrayStorage(AbstractArrayStorage):
    """
    Parquet-based storage for array metrics.

    Stores time series and multi-dimensional array data
    efficiently using columnar storage.
    """

    def __init__(self, storage_dir: Path | None = None):
        """
        Initialize array storage.

        Args:
            storage_dir: Directory for parquet files
        """
        self._use_ssot_layout = storage_dir is None
        if storage_dir is None:
            storage_dir = get_project_root() / DEFAULT_ARRAYS_DIR

        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        if not HAS_PARQUET:
            logger.warning("PyArrow not installed, using JSON fallback")

    def _get_file_path(self, metric_name: str, experiment_id: str) -> Path:
        """Get file path for metric data."""
        ext = ".parquet" if HAS_PARQUET else ".json"
        if self._use_ssot_layout:
            path = get_array_storage_path(experiment_id, metric_name, create=True)
            return path if ext == ".parquet" else path.with_suffix(ext)
        return self.storage_dir / f"{experiment_id}_{metric_name}{ext}"

    def _get_legacy_flat_file_path(self, metric_name: str, experiment_id: str) -> Path:
        """Legacy file path used by older flat storage layout."""
        ext = ".parquet" if HAS_PARQUET else ".json"
        return self.storage_dir / f"{experiment_id}_{metric_name}{ext}"

    def store(
        self,
        metric_name: str,
        experiment_id: str,
        data: dict[str, list],
        metadata: dict | None = None,
    ) -> None:
        """
        Store array metric data.

        Args:
            metric_name: Name of the metric
            experiment_id: Experiment identifier
            data: Dictionary of column_name -> values
            metadata: Optional metadata
        """
        file_path = self._get_file_path(metric_name, experiment_id)

        if HAS_PARQUET:
            self._store_parquet(file_path, data, metadata)
        else:
            self._store_json(file_path, data, metadata)

        logger.debug(f"Stored {metric_name} for experiment {experiment_id}")

    def store_metric(
        self,
        metric_name: str,
        experiment_id: str,
        data: dict[str, list],
        summary: dict[str, float] | None = None,
        metadata: dict | None = None,
    ) -> ArrayMetricStorage:
        """Store array metric data and return ArrayMetricStorage descriptor.

        This is the preferred public API for storing array metrics.
        It stores the data and returns a fully-populated
        ArrayMetricStorage object suitable for inclusion in MetricResult.

        Args:
            metric_name: Name of the metric (e.g. "rdf_curve").
            experiment_id: Experiment identifier.
            data: Dictionary of column_name -> values.
            summary: Optional summary statistics dict.
            metadata: Optional metadata to embed in file.

        Returns:
            ArrayMetricStorage with file_path, file_hash, shape, summary.
        """
        self.store(metric_name, experiment_id, data, metadata)

        file_path = self._get_file_path(metric_name, experiment_id)

        # Compute hash from serialised data
        content_bytes = json.dumps(data, sort_keys=True).encode()
        file_hash = hashlib.sha256(content_bytes).hexdigest()[:16]

        # Determine shape from data
        n_cols = len(data)
        n_rows = max((len(v) for v in data.values()), default=0)
        shape = (n_rows, n_cols)

        return ArrayMetricStorage(
            file_path=str(file_path),
            file_hash=file_hash,
            shape=shape,
            summary=summary or {},
        )

    def save(
        self,
        exp_id: str,
        metric_name: str,
        data: Any,
        columns: list[str] | None = None,
    ) -> ArrayMetricStorage:
        """Save array to file (AbstractArrayStorage interface).

        Args:
            exp_id: Experiment identifier
            metric_name: Name of the metric
            data: Data to store (dict, numpy array, or iterable)
            columns: Column names (for numpy array conversion)

        Returns:
            ArrayMetricStorage descriptor
        """
        if isinstance(data, dict):
            dict_data = data
        else:
            if columns and hasattr(data, "shape"):
                dict_data = {col: data[:, i].tolist() for i, col in enumerate(columns)}
            else:
                dict_data = {"values": list(data) if hasattr(data, "__iter__") else [data]}
        return self.store_metric(metric_name, exp_id, dict_data)

    def _store_parquet(
        self,
        file_path: Path,
        data: dict[str, list],
        metadata: dict | None,
    ) -> None:
        """Store data as Parquet."""
        table = pa.table(data)

        if metadata:
            existing = table.schema.metadata or {}
            new_metadata = {
                **existing,
                b"custom_metadata": json.dumps(metadata).encode(),
                b"stored_at": datetime.now().isoformat().encode(),
            }
            table = table.replace_schema_metadata(new_metadata)

        pq.write_table(table, file_path)

    def _store_json(
        self,
        file_path: Path,
        data: dict[str, list],
        metadata: dict | None,
    ) -> None:
        """Store data as JSON (fallback)."""
        output = {
            "data": data,
            "metadata": metadata or {},
            "stored_at": datetime.now().isoformat(),
        }
        file_path.write_text(json.dumps(output))

    def load(
        self,
        metric_name_or_path: str,
        experiment_id: str | None = None,
    ) -> dict[str, list] | None:
        """Load array metric data.

        Supports two call signatures:
        - load(metric_name, experiment_id) -- legacy key-based lookup
        - load(file_path) -- AbstractArrayStorage interface (path-based)

        Args:
            metric_name_or_path: Metric name (with experiment_id) or file path
            experiment_id: Experiment identifier (None for path-based lookup)

        Returns:
            Dictionary of column_name -> values or None
        """
        if experiment_id is not None:
            return self._load_by_key(metric_name_or_path, experiment_id)
        return self._load_by_path(metric_name_or_path)

    def _load_by_key(
        self,
        metric_name: str,
        experiment_id: str,
    ) -> dict[str, list] | None:
        """Load by metric name + experiment ID (legacy)."""
        file_path = self._get_file_path(metric_name, experiment_id)

        if not file_path.exists():
            if self._use_ssot_layout:
                legacy_path = self._get_legacy_flat_file_path(metric_name, experiment_id)
                if legacy_path.exists():
                    file_path = legacy_path
                else:
                    return None
            else:
                return None

        if HAS_PARQUET:
            return self._load_parquet(file_path)
        else:
            return self._load_json(file_path)

    def _load_by_path(self, file_path_str: str) -> dict[str, list] | None:
        """Load by file path (AbstractArrayStorage interface).

        Validates path is within the project root to prevent directory traversal.
        """
        from features.common.workspace import resolve_workspace_path

        try:
            file_path = resolve_workspace_path(file_path_str)
        except Exception:
            logger.warning(f"Blocked path outside project root: {file_path_str}")
            return None
        if not file_path.exists():
            return None
        if HAS_PARQUET and file_path.suffix == ".parquet":
            return self._load_parquet(file_path)
        return self._load_json(file_path)

    def _load_parquet(self, file_path: Path) -> dict[str, list]:
        """Load data from Parquet."""
        table = pq.read_table(file_path)
        return {col: table[col].to_pylist() for col in table.column_names}

    def _load_json(self, file_path: Path) -> dict[str, list[Any]]:
        """Load data from JSON."""
        data = json.loads(file_path.read_text())
        result: dict[str, list[Any]] = data.get("data", {})
        return result

    def load_with_metadata(
        self,
        metric_name: str,
        experiment_id: str,
    ) -> tuple[dict[str, list] | None, dict | None]:
        """
        Load array metric data with metadata.

        Args:
            metric_name: Name of the metric
            experiment_id: Experiment identifier

        Returns:
            Tuple of (data, metadata)
        """
        file_path = self._get_file_path(metric_name, experiment_id)

        if not file_path.exists():
            if self._use_ssot_layout:
                legacy_path = self._get_legacy_flat_file_path(metric_name, experiment_id)
                if legacy_path.exists():
                    file_path = legacy_path
                else:
                    return None, None
            else:
                return None, None

        if HAS_PARQUET:
            table = pq.read_table(file_path)
            data = {col: table[col].to_pylist() for col in table.column_names}
            metadata = {}
            if table.schema.metadata:
                raw = table.schema.metadata.get(b"custom_metadata")
                if raw:
                    metadata = json.loads(raw.decode())
            return data, metadata
        else:
            raw = json.loads(file_path.read_text())
            return raw.get("data"), raw.get("metadata")

    def exists(self, metric_name: str, experiment_id: str) -> bool:
        """Check if data exists for metric and experiment."""
        file_path = self._get_file_path(metric_name, experiment_id)
        if file_path.exists():
            return True
        if self._use_ssot_layout:
            return self._get_legacy_flat_file_path(metric_name, experiment_id).exists()
        return False

    def delete(
        self,
        metric_name_or_path: str,
        experiment_id: str | None = None,
    ) -> None:
        """Delete stored data.

        Supports two call signatures:
        - delete(metric_name, experiment_id) -- legacy key-based
        - delete(file_path) -- AbstractArrayStorage interface (path-based)

        Args:
            metric_name_or_path: Metric name (with experiment_id) or file path
            experiment_id: Experiment identifier (None for path-based)
        """
        if experiment_id is not None:
            self._delete_by_key(metric_name_or_path, experiment_id)
        else:
            self._delete_by_path(metric_name_or_path)

    def _delete_by_key(self, metric_name: str, experiment_id: str) -> None:
        """Delete by metric name + experiment ID (legacy)."""
        file_path = self._get_file_path(metric_name, experiment_id)
        if file_path.exists():
            file_path.unlink()
            return
        if self._use_ssot_layout:
            legacy_path = self._get_legacy_flat_file_path(metric_name, experiment_id)
            if legacy_path.exists():
                legacy_path.unlink()

    def _delete_by_path(self, file_path_str: str) -> None:
        """Delete by file path (AbstractArrayStorage interface)."""
        file_path = Path(file_path_str)
        if file_path.exists():
            file_path.unlink()

    def list_experiments(self, metric_name: str) -> list[str]:
        """List all experiments with stored data for a metric."""
        ext = ".parquet" if HAS_PARQUET else ".json"
        exp_ids: set[str] = set()

        if self._use_ssot_layout:
            nested_pattern = f"*/{metric_name}{ext}"
            for file_path in self.storage_dir.glob(nested_pattern):
                exp_ids.add(file_path.parent.name)

        # Backward compatibility for flat layout files
        flat_pattern = f"*_{metric_name}{ext}"
        for file_path in self.storage_dir.glob(flat_pattern):
            exp_ids.add(file_path.stem.replace(f"_{metric_name}", ""))

        return sorted(exp_ids)

    def list_metrics(self, experiment_id: str) -> list[str]:
        """List all metrics stored for an experiment."""
        ext = ".parquet" if HAS_PARQUET else ".json"
        metric_names: set[str] = set()

        if self._use_ssot_layout:
            exp_dir = self.storage_dir / experiment_id
            if exp_dir.exists():
                for file_path in exp_dir.glob(f"*{ext}"):
                    metric_names.add(file_path.stem)

        # Backward compatibility for flat layout files
        pattern = f"{experiment_id}_*{ext}"
        for file_path in self.storage_dir.glob(pattern):
            metric_names.add(file_path.stem.replace(f"{experiment_id}_", ""))

        return sorted(metric_names)

    def get_storage_stats(self) -> dict[str, Any]:
        """Get storage statistics."""
        ext = ".parquet" if HAS_PARQUET else ".json"
        files = list(self.storage_dir.glob(f"*{ext}"))

        total_size = sum(f.stat().st_size for f in files)

        return {
            "num_files": len(files),
            "total_size_bytes": total_size,
            "total_size_mb": total_size / (1024 * 1024),
            "storage_dir": str(self.storage_dir),
            "format": "parquet" if HAS_PARQUET else "json",
        }
