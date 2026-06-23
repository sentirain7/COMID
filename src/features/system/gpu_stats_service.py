"""GPU statistics service."""

from api.schemas import GPUStatsResponse
from common.logging import get_logger

logger = get_logger("features.system")


async def get_gpu_stats() -> GPUStatsResponse:
    """Get GPU utilization statistics with real-time nvidia-smi data."""
    try:
        from api.deps import get_gpu_resource_tracker
        from monitoring.gpu_collector import GPUCollector

        tracker = get_gpu_resource_tracker()
        summary = tracker.get_utilization_summary()

        collector = GPUCollector()
        realtime_stats = {}
        if collector.is_available():
            for gpu_stat in collector.collect_once():
                gpu_id = int(gpu_stat.gpu_id)
                realtime_stats[gpu_id] = {
                    "utilization": gpu_stat.utilization_percent,
                    "memory": round(
                        (gpu_stat.memory_used_bytes / gpu_stat.memory_total_bytes * 100), 2
                    )
                    if gpu_stat.memory_total_bytes > 0
                    else 0,
                    "name": gpu_stat.name,
                }

        tracker_ids = {gpu.gpu_id for gpu in tracker.get_all_gpus()}
        missing_ids = sorted(set(realtime_stats.keys()) - tracker_ids)
        if missing_ids:
            tracker.register_detected_gpus(
                [
                    {
                        "gpu_id": gpu_id,
                        "name": realtime_stats[gpu_id]["name"],
                        "memory_gb": 0.0,
                    }
                    for gpu_id in missing_ids
                ]
            )
            tracker.apply_offline_for_unselected()
            logger.info(f"GPU tracker reconciled with runtime detection: added GPUs {missing_ids}")

        # GPU당 슬롯 수(다중잡/MPS). 1이면 기존 1잡/GPU 표시와 동일.
        try:
            from contracts.policies.budget import DEFAULT_JOB_BUDGETING_POLICY

            slots_total = max(1, int(DEFAULT_JOB_BUDGETING_POLICY.max_concurrent_jobs_per_gpu))
        except Exception:  # noqa: BLE001
            slots_total = 1

        def _entry(gpu, name, util, mem):
            # 가산 필드: jobs(전체 동시잡)·slots·eligible/uuid. job(단일)은 구프론트 호환.
            jobs = list(getattr(gpu, "active_jobs", None) or [])
            # per-device 슬롯: 디바이스 실제 slots 우선(MIG instance=1, MPS H200=N,
            # 부적격 소형 GPU=1). 미설정(0)이면 정책 기반 폴백.
            eligible = bool(getattr(gpu, "eligible", True))
            dev_slots_total = int(getattr(gpu, "slots", 0)) or (slots_total if eligible else 1)
            return {
                "id": gpu.gpu_id,
                "name": name,
                "utilization": util,
                "memory": mem,
                "status": gpu.status.value,
                "job": gpu.current_job_id,  # backward-compat (첫 잡)
                "jobs": [j.get("exp_id") or j.get("task_id") for j in jobs],
                "slots_used": len(jobs),
                "slots_total": dev_slots_total,
                "uuid": getattr(gpu, "uuid", None),
                "eligible": eligible,
                "kind": getattr(gpu, "kind", "whole_gpu"),
            }

        gpus = []
        for gpu in tracker.get_all_gpus():
            if gpu.gpu_id in realtime_stats:
                rt = realtime_stats[gpu.gpu_id]
                gpus.append(_entry(gpu, rt["name"], rt["utilization"], rt["memory"]))
            else:
                mem = (
                    round((gpu.memory_used_gb / gpu.memory_total_gb * 100), 2)
                    if gpu.memory_total_gb > 0
                    else 0
                )
                gpus.append(_entry(gpu, gpu.name, gpu.utilization_percent, mem))

        return GPUStatsResponse(
            gpus=gpus,
            total=summary["total_gpus"],
            available=summary["available_gpus"],
            busy=summary["busy_gpus"],
        )
    except Exception as e:
        logger.error(f"GPU stats collection failed: {e}")
        return GPUStatsResponse(gpus=[], total=0, available=0, busy=0)
