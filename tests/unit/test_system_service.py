"""Tests for system service GPU/settings behavior."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from features.system import service
from orchestrator.gpu_types import GPUInfo, GPUStatus


@pytest.mark.asyncio
async def test_update_settings_clears_gpu_tracker_cache_on_selected_gpu_change():
    """selected_gpus 변경 시 GPU tracker 캐시를 재초기화한다."""
    initial = {"gpu_enabled": True, "selected_gpus": [0], "max_concurrent_jobs": 4}
    saved = {}

    def _save(settings: dict) -> None:
        saved.update(settings)

    with (
        patch("config.dashboard_settings.load_dashboard_settings", return_value=initial.copy()),
        patch("config.dashboard_settings.save_dashboard_settings", side_effect=_save),
        patch("api.deps.clear_gpu_tracker_cache") as clear_cache,
    ):
        result = await service.update_settings({"selected_gpus": [0, 1]})

    assert result["status"] == "updated"
    assert result["settings"]["selected_gpus"] == [0, 1]
    assert saved["selected_gpus"] == [0, 1]
    clear_cache.assert_called_once()


@pytest.mark.asyncio
async def test_get_gpu_stats_reconciles_missing_runtime_gpu_ids():
    """초기 cache에 없던 GPU가 실시간 탐지되면 응답에 포함되도록 동기화한다."""

    class FakeTracker:
        def __init__(self):
            self._selected = [0]
            self._cache = {
                0: GPUInfo(
                    gpu_id=0,
                    name="GPU-0",
                    status=GPUStatus.AVAILABLE,
                    memory_total_gb=16.0,
                    utilization_pct=0.0,
                )
            }

        def get_utilization_summary(self) -> dict:
            values = list(self._cache.values())
            return {
                "total_gpus": len(values),
                "available_gpus": sum(1 for g in values if g.status == GPUStatus.AVAILABLE),
                "busy_gpus": sum(1 for g in values if g.status == GPUStatus.BUSY),
            }

        def get_all_gpus(self):
            return list(self._cache.values())

        def register_detected_gpus(self, detected_gpus: list[dict]) -> None:
            for info in detected_gpus:
                gpu_id = info["gpu_id"]
                if gpu_id not in self._cache:
                    self._cache[gpu_id] = GPUInfo(
                        gpu_id=gpu_id,
                        name=info.get("name", f"GPU-{gpu_id}"),
                        status=GPUStatus.AVAILABLE,
                    )

        def apply_offline_for_unselected(self) -> None:
            for gpu_id, gpu in self._cache.items():
                if gpu_id not in self._selected:
                    gpu.status = GPUStatus.OFFLINE

    class FakeCollector:
        def is_available(self) -> bool:
            return True

        def collect_once(self):
            return [
                SimpleNamespace(
                    gpu_id="0",
                    utilization_percent=35.0,
                    memory_used_bytes=4 * 1024 * 1024 * 1024,
                    memory_total_bytes=16 * 1024 * 1024 * 1024,
                    name="RTX-0",
                ),
                SimpleNamespace(
                    gpu_id="1",
                    utilization_percent=0.0,
                    memory_used_bytes=0,
                    memory_total_bytes=8 * 1024 * 1024 * 1024,
                    name="RTX-1",
                ),
            ]

    tracker = FakeTracker()

    with (
        patch("api.deps.get_gpu_resource_tracker", return_value=tracker),
        patch("monitoring.gpu_collector.GPUCollector", return_value=FakeCollector()),
    ):
        result = await service.get_gpu_stats()

    gpu_ids = sorted(g["id"] for g in result.gpus)
    assert gpu_ids == [0, 1]
    gpu_1 = next(g for g in result.gpus if g["id"] == 1)
    assert gpu_1["name"] == "RTX-1"
    assert gpu_1["status"] == "offline"
