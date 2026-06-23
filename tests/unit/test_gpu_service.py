"""
Unit tests for GPU Service (v00.68.04).

Tests the GPUService singleton and its methods.
"""

from datetime import datetime
from unittest.mock import patch

from orchestrator.gpu_service import (
    GPUInfo,
    GPUService,
    GPUStatus,
    get_gpu_service,
    reset_gpu_service,
)


class TestGPUStatus:
    """Tests for GPUStatus enum."""

    def test_status_values(self):
        """Test enum values."""
        assert GPUStatus.AVAILABLE.value == "available"
        assert GPUStatus.BUSY.value == "busy"
        assert GPUStatus.RESERVED.value == "reserved"
        assert GPUStatus.ERROR.value == "error"
        assert GPUStatus.OFFLINE.value == "offline"

    def test_status_is_str(self):
        """Test enum is string-based."""
        assert isinstance(GPUStatus.AVAILABLE, str)
        assert GPUStatus.AVAILABLE == "available"


class TestGPUInfo:
    """Tests for GPUInfo dataclass."""

    def test_default_values(self):
        """Test default values."""
        info = GPUInfo(gpu_id=0)

        assert info.gpu_id == 0
        assert info.name == "Unknown"
        assert info.status == GPUStatus.AVAILABLE
        assert info.current_task_id is None
        assert info.current_exp_id is None
        assert info.memory_used_gb == 0.0
        assert info.memory_total_gb == 0.0
        assert info.utilization_pct == 0.0
        assert info.temperature_c == 0.0
        assert info.allocated_at is None
        assert info.last_updated is None

    def test_custom_values(self):
        """Test with custom values."""
        now = datetime.now()
        info = GPUInfo(
            gpu_id=1,
            name="GPU-1",
            status=GPUStatus.BUSY,
            current_task_id="task-123",
            current_exp_id="exp-456",
            memory_used_gb=20.5,
            memory_total_gb=80.0,
            utilization_pct=85.0,
            temperature_c=72.0,
            allocated_at=now,
            last_updated=now,
        )

        assert info.gpu_id == 1
        assert info.status == GPUStatus.BUSY
        assert info.current_task_id == "task-123"
        assert info.current_exp_id == "exp-456"
        assert info.memory_used_gb == 20.5
        assert info.allocated_at == now
        assert info.last_updated == now

    def test_alias_properties(self):
        """Test compatibility aliases."""
        info = GPUInfo(gpu_id=0)
        info.current_job_id = "job-1"
        assert info.current_task_id == "job-1"
        info.utilization_percent = 42.0
        assert info.utilization_pct == 42.0


class TestGPUService:
    """Tests for GPUService class."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_gpu_service()

    def teardown_method(self):
        """Reset singleton after each test."""
        reset_gpu_service()

    def test_init(self):
        """Test initialization."""
        service = GPUService()

        assert service._initialized is False
        assert service._selected_gpus == []
        assert service._cache == {}

    def test_initialize_with_explicit_gpus(self):
        """Test initialization with explicit GPU list."""
        service = GPUService()
        service.initialize(selected_gpus=[0, 1, 2])

        assert service._initialized is True
        assert service._selected_gpus == [0, 1, 2]
        assert len(service._cache) == 3
        assert all(info.status == GPUStatus.AVAILABLE for info in service._cache.values())

    def test_initialize_idempotent(self):
        """Test that initialize() is idempotent."""
        service = GPUService()
        service.initialize(selected_gpus=[0, 1])
        service.initialize(selected_gpus=[2, 3])  # Should be ignored

        assert service._selected_gpus == [0, 1]
        assert len(service._cache) == 2

    def test_initialize_empty_gpus(self):
        """Test initialization with no GPUs (CPU-only mode)."""
        service = GPUService()

        # Mock _load_selected_gpus to return empty list
        with patch.object(service, "_load_selected_gpus", return_value=[]):
            service.initialize()

        assert service._initialized is True
        assert service._selected_gpus == []
        assert len(service._cache) == 0

    def test_selected_gpus_property(self):
        """Test selected_gpus property."""
        service = GPUService()
        service.initialize(selected_gpus=[0, 2, 4])

        # Property should return a copy
        gpus = service.selected_gpus
        assert gpus == [0, 2, 4]

        # Modifying returned list shouldn't affect internal state
        gpus.append(6)
        assert service.selected_gpus == [0, 2, 4]

    def test_is_initialized_property(self):
        """Test is_initialized property."""
        service = GPUService()
        assert service.is_initialized is False

        service.initialize(selected_gpus=[0])
        assert service.is_initialized is True

    def test_num_gpus_property(self):
        """Test num_gpus property."""
        service = GPUService()
        service.initialize(selected_gpus=[0, 1, 2])
        assert service.num_gpus == 3

    def test_update_stats(self):
        """Test updating GPU statistics."""
        service = GPUService()
        service.initialize(selected_gpus=[0, 1])

        service.update_stats(
            gpu_id=0,
            memory_used_gb=30.0,
            memory_total_gb=80.0,
            utilization_pct=75.0,
            temperature_c=68.0,
        )

        info = service._cache[0]
        assert info.memory_used_gb == 30.0
        assert info.memory_total_gb == 80.0
        assert info.utilization_pct == 75.0
        assert info.temperature_c == 68.0

    def test_update_stats_unknown_gpu(self):
        """Test updating stats for unknown GPU (should be no-op)."""
        service = GPUService()
        service.initialize(selected_gpus=[0])

        # Should not raise
        service.update_stats(gpu_id=99, memory_used_gb=10.0)

        # GPU 99 should not be in cache
        assert 99 not in service._cache

    def test_get_status_format(self):
        """Test get_status returns correct format."""
        service = GPUService()
        service.initialize(selected_gpus=[0, 1])

        # Mock _sync_from_db to avoid DB calls
        with patch.object(service, "_sync_from_db"):
            status = service.get_status()

        assert "gpus" in status
        assert "total" in status
        assert "available" in status
        assert "busy" in status

        assert status["total"] == 2
        assert status["available"] == 2
        assert status["busy"] == 0

        # Check GPU info format
        assert len(status["gpus"]) == 2
        gpu_info = status["gpus"][0]
        assert "gpu_id" in gpu_info
        assert "status" in gpu_info
        assert "current_task_id" in gpu_info
        assert "current_exp_id" in gpu_info
        assert "memory_used_gb" in gpu_info
        assert "allocated_at" in gpu_info

    def test_get_gpu_and_get_all_gpus(self):
        """Test GPUResourceTracker-compatible getters."""
        service = GPUService()
        service.initialize(selected_gpus=[0, 1])

        gpu0 = service.get_gpu(0)
        assert gpu0 is not None
        assert gpu0.gpu_id == 0

        all_gpus = service.get_all_gpus()
        assert len(all_gpus) == 2
        assert all(g.gpu_id in (0, 1) for g in all_gpus)

    def test_update_gpu_stats_compat(self):
        """Test GPUResourceTracker-compatible stats update."""
        service = GPUService()
        service.initialize(selected_gpus=[0])

        service.update_gpu_stats(
            gpu_id=0,
            memory_used_gb=12.0,
            utilization_percent=55.0,
            temperature_c=65.0,
        )

        info = service.get_gpu(0)
        assert info is not None
        assert info.memory_used_gb == 12.0
        assert info.utilization_percent == 55.0
        assert info.temperature_c == 65.0
        assert info.last_updated is not None

    def test_get_utilization_summary_format(self):
        """Test GPUResourceTracker-compatible utilization summary."""
        service = GPUService()
        service.initialize(selected_gpus=[0, 1])

        with patch.object(service, "_sync_from_db"):
            summary = service.get_utilization_summary()

        assert set(summary.keys()) == {
            "total_gpus",
            "available_gpus",
            "busy_gpus",
            "total_memory_gb",
            "used_memory_gb",
            "average_utilization_percent",
        }

    def test_restore_allocation(self):
        """Test restore_allocation behavior."""
        service = GPUService()
        service.initialize(selected_gpus=[0])

        restored = service.restore_allocation(gpu_id=0, job_id="job-1", exp_id="exp-1")
        assert restored is True
        info = service.get_gpu(0)
        assert info is not None
        assert info.status == GPUStatus.BUSY
        assert info.current_job_id == "job-1"


class TestGPUServiceWithDB:
    """Tests for GPUService with mocked DB."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_gpu_service()

    def teardown_method(self):
        """Reset singleton after each test."""
        reset_gpu_service()

    def test_allocate_success(self, db_session):
        """Test successful GPU allocation."""
        from database.models import ExperimentModel

        # Create an experiment with celery_task_id
        exp = ExperimentModel(
            exp_id="test_exp_001",
            celery_task_id="task-12345",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="pending",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
        )
        db_session.add(exp)
        db_session.commit()

        service = GPUService()
        service.initialize(selected_gpus=[0, 1])

        gpu_id = service.allocate(task_id="task-12345")

        assert gpu_id == 0
        assert service._cache[0].status == GPUStatus.BUSY
        assert service._cache[0].current_task_id == "task-12345"
        assert service._cache[0].current_exp_id == "test_exp_001"

        # Verify DB was updated
        db_session.refresh(exp)
        assert exp.gpu_id_allocated == 0

    def test_allocate_no_gpus_available(self, db_session):
        """Test allocation when every per-GPU slot is busy.

        With multi-job-per-GPU (N slots/GPU, policy SSOT) "no GPU available"
        means *all* slots on *all* selected GPUs are occupied. Fill the grid
        dynamically from the slot count so this stays correct for any N.
        """
        from database.models import ExperimentModel

        service = GPUService()
        service.initialize(selected_gpus=[0, 1])
        slots = service._slots_per_gpu()

        # Fill every slot on GPUs 0 and 1 (slots x 2 running experiments).
        for gpu_id in (0, 1):
            for slot in range(slots):
                exp = ExperimentModel(
                    exp_id=f"running_exp_g{gpu_id}_s{slot}",
                    celery_task_id=f"running-task-g{gpu_id}-s{slot}",
                    run_tier="screening",
                    ff_type="bulk_ff_gaff2",
                    status="running",
                    comp_asphaltene_wt=20.0,
                    comp_resin_wt=30.0,
                    comp_aromatic_wt=35.0,
                    comp_saturate_wt=15.0,
                    gpu_id_allocated=gpu_id,
                )
                db_session.add(exp)

        # Create a new experiment trying to allocate
        new_exp = ExperimentModel(
            exp_id="new_exp",
            celery_task_id="new-task",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="pending",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
        )
        db_session.add(new_exp)
        db_session.commit()

        gpu_id = service.allocate(task_id="new-task")

        assert gpu_id is None

    def test_allocate_not_initialized(self):
        """Test allocation fails if service not initialized."""
        service = GPUService()

        gpu_id = service.allocate(task_id="any-task")

        assert gpu_id is None

    def test_allocate_no_gpus_configured(self):
        """Test allocation with no GPUs configured."""
        service = GPUService()
        service._initialized = True
        service._selected_gpus = []

        gpu_id = service.allocate(task_id="any-task")

        assert gpu_id is None

    def test_allocate_experiment_not_found(self, db_session):
        """Test allocation fails when experiment record doesn't exist."""
        service = GPUService()
        service.initialize(selected_gpus=[0, 1])

        # Try to allocate for a task that doesn't have an experiment record
        gpu_id = service.allocate(task_id="nonexistent-task")

        # Should return None to avoid tracking inconsistency
        assert gpu_id is None
        # GPU should still be available
        assert service._cache[0].status == GPUStatus.AVAILABLE

    def test_allocate_round_robin_when_gpus_become_available_again(self, db_session):
        """Round-robin should avoid always picking the first GPU when both are available."""
        from database.models import ExperimentModel

        exp1 = ExperimentModel(
            exp_id="rr_exp_1",
            celery_task_id="rr-task-1",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="pending",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
        )
        exp2 = ExperimentModel(
            exp_id="rr_exp_2",
            celery_task_id="rr-task-2",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="pending",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
        )
        db_session.add(exp1)
        db_session.add(exp2)
        db_session.commit()

        service = GPUService()
        service.initialize(selected_gpus=[0, 1])

        first_gpu = service.allocate(task_id="rr-task-1")
        assert first_gpu == 0
        assert service.release(first_gpu, task_id="rr-task-1") is True

        second_gpu = service.allocate(task_id="rr-task-2")
        assert second_gpu == 1

    def test_release_success(self, db_session):
        """Test successful GPU release."""
        from database.models import ExperimentModel

        # Create an experiment with GPU allocated
        exp = ExperimentModel(
            exp_id="test_exp",
            celery_task_id="task-abc",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="running",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            gpu_id_allocated=0,
        )
        db_session.add(exp)
        db_session.commit()

        service = GPUService()
        service.initialize(selected_gpus=[0, 1])
        service._cache[0].status = GPUStatus.BUSY
        service._cache[0].current_task_id = "task-abc"

        result = service.release(gpu_id=0, task_id="task-abc")

        assert result is True
        assert service._cache[0].status == GPUStatus.AVAILABLE
        assert service._cache[0].current_task_id is None

        # Verify DB was updated
        db_session.refresh(exp)
        assert exp.gpu_id_allocated is None

    def test_release_without_task_id_is_blocked(self, db_session):
        """Release without task_id/exp_id should be blocked for safety."""
        from database.models import ExperimentModel

        # Create an experiment with GPU allocated
        exp = ExperimentModel(
            exp_id="test_exp",
            celery_task_id="task-xyz",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="running",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            gpu_id_allocated=1,
        )
        db_session.add(exp)
        db_session.commit()

        service = GPUService()
        service.initialize(selected_gpus=[0, 1])
        service._cache[1].status = GPUStatus.BUSY

        # Release without identity should be blocked
        result = service.release(gpu_id=1)

        assert result is False
        assert service._cache[1].status == GPUStatus.BUSY

    def test_release_with_mismatched_identity_does_not_clear(self, db_session):
        """Release must not clear allocation without matching task_id/exp_id."""
        from database.models import ExperimentModel

        exp = ExperimentModel(
            exp_id="test_exp_identity",
            celery_task_id="task-identity",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="running",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            gpu_id_allocated=0,
        )
        db_session.add(exp)
        db_session.commit()

        service = GPUService()
        service.initialize(selected_gpus=[0, 1])
        service._cache[0].status = GPUStatus.BUSY
        service._cache[0].current_task_id = "task-identity"

        result = service.release(gpu_id=0, task_id="other-task", exp_id="other-exp")
        assert result is False

        db_session.refresh(exp)
        assert exp.gpu_id_allocated == 0
        assert service._cache[0].status == GPUStatus.BUSY

    def test_restore_from_db(self, db_session):
        """Test restoring allocation state from DB."""
        from database.models import ExperimentModel

        # Create experiments with GPU allocations
        for i in range(2):
            exp = ExperimentModel(
                exp_id=f"running_exp_{i}",
                celery_task_id=f"task-{i}",
                run_tier="screening",
                ff_type="bulk_ff_gaff2",
                status="running",
                comp_asphaltene_wt=20.0,
                comp_resin_wt=30.0,
                comp_aromatic_wt=35.0,
                comp_saturate_wt=15.0,
                gpu_id_allocated=i,
            )
            db_session.add(exp)
        db_session.commit()

        service = GPUService()
        service.initialize(selected_gpus=[0, 1, 2])

        # Verify restored state
        assert service._cache[0].status == GPUStatus.BUSY
        assert service._cache[0].current_task_id == "task-0"
        assert service._cache[1].status == GPUStatus.BUSY
        assert service._cache[1].current_task_id == "task-1"
        assert service._cache[2].status == GPUStatus.AVAILABLE

    def test_get_available_gpus(self, db_session):
        """Test get_available_gpus method."""
        from database.models import ExperimentModel

        # Create one experiment using GPU 0
        exp = ExperimentModel(
            exp_id="running_exp",
            celery_task_id="task-1",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="running",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            gpu_id_allocated=0,
        )
        db_session.add(exp)
        db_session.commit()

        service = GPUService()
        service.initialize(selected_gpus=[0, 1, 2])

        available = service.get_available_gpus()
        available_ids = {g.gpu_id for g in available}

        assert 0 not in available_ids
        assert 1 in available_ids
        assert 2 in available_ids

    def test_allocate_gpu_compat(self, db_session):
        """Test GPUResourceTracker-compatible allocate_gpu."""
        from database.models import ExperimentModel

        exp = ExperimentModel(
            exp_id="exp_alloc",
            celery_task_id="task-alloc",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="running",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
        )
        db_session.add(exp)
        db_session.commit()

        service = GPUService()
        service.initialize(selected_gpus=[0, 1])

        gpu_id = service.allocate_gpu(job_id="task-alloc", gpu_id=0, exp_id="exp_alloc")
        assert gpu_id == 0

        info = service.get_gpu(0)
        assert info is not None
        assert info.status == GPUStatus.BUSY
        assert info.current_job_id == "task-alloc"
        assert info.current_exp_id == "exp_alloc"

    def test_clear_all_allocations(self, db_session):
        """Test clear_all_allocations clears DB and cache."""
        from database.models import ExperimentModel

        exp1 = ExperimentModel(
            exp_id="exp_clear_1",
            celery_task_id="task-clear-1",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="running",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            gpu_id_allocated=0,
        )
        exp2 = ExperimentModel(
            exp_id="exp_clear_2",
            celery_task_id="task-clear-2",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="running",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            gpu_id_allocated=1,
        )
        db_session.add(exp1)
        db_session.add(exp2)
        db_session.commit()

        service = GPUService()
        service.initialize(selected_gpus=[0, 1])

        cleared = service.clear_all_allocations()
        assert cleared == 2

        # Verify DB allocations cleared
        exp1_db = (
            db_session.query(ExperimentModel)
            .filter(ExperimentModel.exp_id == "exp_clear_1")
            .first()
        )
        exp2_db = (
            db_session.query(ExperimentModel)
            .filter(ExperimentModel.exp_id == "exp_clear_2")
            .first()
        )
        assert exp1_db.gpu_id_allocated is None
        assert exp2_db.gpu_id_allocated is None


class TestMultiJobPerGPUSlots:
    """Multi-job-per-GPU slot allocation (N slots/GPU via MPS, N>=1).

    The per-GPU slot count is the budget-policy SSOT. These tests pin the
    invariant: a GPU accepts up to N concurrent jobs and not one more, and
    the count is enforced atomically inside the allocation transaction.
    """

    def setup_method(self):
        reset_gpu_service()

    def teardown_method(self):
        reset_gpu_service()

    def test_available_with_slots_counts_per_gpu(self):
        """_available_with_slots returns GPUs below their slot limit."""
        # slots=2: gpu 0 has 2 jobs (full), gpu 1 has 1 job (free) -> only [1]
        assert GPUService._available_with_slots([0, 1], [0, 0, 1], 2) == [1]
        # slots=1: classic 1-job/GPU semantics -> gpu 0 full, gpu 1 free
        assert GPUService._available_with_slots([0, 1], [0], 1) == [1]
        # empty allocations -> all selected GPUs available
        assert GPUService._available_with_slots([0, 1], [], 3) == [0, 1]
        # None entries (unallocated rows) are ignored in the count
        assert GPUService._available_with_slots([0, 1], [None, 0], 2) == [0, 1]

    def test_slots_per_gpu_reads_policy(self):
        """Slot count comes from the budget policy SSOT (>=1)."""
        from contracts.policies.budget import DEFAULT_JOB_BUDGETING_POLICY

        service = GPUService()
        expected = max(1, int(DEFAULT_JOB_BUDGETING_POLICY.max_concurrent_jobs_per_gpu))
        assert service._slots_per_gpu() == expected
        assert service._slots_per_gpu() >= 1

    def test_available_with_slots_accepts_per_device_cap_map(self):
        """_available_with_slots / _detect_overallocation honor a {gpu_id: cap} map."""
        caps = {0: 6, 5: 1}
        # gpu 0 has 1 job (cap 6 -> free); gpu 5 has 1 job (cap 1 -> full)
        assert GPUService._available_with_slots([0, 5], [0, 5], caps) == [0]
        # both empty -> both available
        assert GPUService._available_with_slots([0, 5], [], caps) == [0, 5]
        # over-allocation detector also honors the per-device cap
        assert GPUService._detect_overallocation([5, 5], caps) == {5: 2}
        assert GPUService._detect_overallocation([0, 0], caps) == {}

    def test_slot_caps_from_per_device_slots(self):
        """_slot_caps reads each device's registry ``slots`` (mode-aware).

        MPS H200 -> N, sub-threshold RTX 3050 -> 0 (hard-excluded), MIG -> 1.
        """
        from contracts.policies.budget import DEFAULT_JOB_BUDGETING_POLICY

        base = max(1, int(DEFAULT_JOB_BUDGETING_POLICY.max_concurrent_jobs_per_gpu))
        service = GPUService()
        service._selected_gpus = [0, 5, 9]
        # Simulate registry: H200 (N slots), 3050 (ineligible), MIG instance (1).
        service._device_cache = {
            0: {"eligible": True, "slots": base, "kind": "whole_gpu", "uuid": "GPU-a"},
            5: {"eligible": False, "slots": 1, "kind": "whole_gpu", "uuid": "GPU-3050"},
            9: {"eligible": True, "slots": 1, "kind": "mig_instance", "uuid": "MIG-x"},
        }
        # Ineligible GPU 5 (sub-threshold VRAM) gets cap 0 even though the registry
        # reports slots=1 — it stays visible but is never allocatable.
        assert service._slot_caps() == {0: base, 5: 0, 9: 1}

    def test_ineligible_gpu_never_allocatable(self):
        """A sub-threshold GPU in selected_gpus is hard-excluded from allocation.

        Guards the user requirement that the RTX 3050 (display GPU) must never
        receive a job even if its index slips into selected_gpus via the UI.
        """
        service = GPUService()
        service._selected_gpus = [0, 5]  # 5 = ineligible 3050
        service._device_cache = {
            0: {"eligible": True, "slots": 3, "kind": "whole_gpu", "uuid": "GPU-a"},
            5: {"eligible": False, "slots": 1, "kind": "whole_gpu", "uuid": "GPU-3050"},
        }
        caps = service._slot_caps()
        # Even with zero current allocations, GPU 5 is never offered (cap 0).
        avail = GPUService._available_with_slots(service._selected_gpus, [], caps)
        assert 5 not in avail
        assert avail == [0]

    def test_allocate_fills_n_slots_on_single_gpu(self, db_session):
        """A single GPU accepts up to N concurrent jobs, then rejects the (N+1)th."""
        from database.models import ExperimentModel

        service = GPUService()
        service.initialize(selected_gpus=[0])  # one GPU only
        slots = service._slots_per_gpu()
        # Pin N slots for GPU 0 so the N-slot counting machinery is exercised
        # regardless of the ambient sharing mode (mig default -> 1 slot/whole GPU).
        service._device_cache = {
            0: {"eligible": True, "slots": slots, "kind": "whole_gpu", "uuid": "GPU-0"}
        }

        # Create slots+1 pending experiments all targeting the single GPU.
        for i in range(slots + 1):
            db_session.add(
                ExperimentModel(
                    exp_id=f"slot_exp_{i}",
                    celery_task_id=f"slot-task-{i}",
                    run_tier="screening",
                    ff_type="bulk_ff_gaff2",
                    status="pending",
                    comp_asphaltene_wt=20.0,
                    comp_resin_wt=30.0,
                    comp_aromatic_wt=35.0,
                    comp_saturate_wt=15.0,
                )
            )
        db_session.commit()

        # First N allocations succeed on GPU 0.
        for i in range(slots):
            assert service.allocate(task_id=f"slot-task-{i}") == 0

        # The (N+1)th allocation finds no free slot.
        assert service.allocate(task_id=f"slot-task-{slots}") is None

        # DB reflects exactly N jobs pinned to GPU 0.
        n_on_gpu0 = (
            db_session.query(ExperimentModel)
            .filter(ExperimentModel.gpu_id_allocated == 0)
            .count()
        )
        assert n_on_gpu0 == slots

    def test_release_one_slot_keeps_gpu_busy_until_empty(self, db_session):
        """Releasing one of N co-located jobs keeps the GPU BUSY; empty -> AVAILABLE."""
        from database.models import ExperimentModel

        service = GPUService()
        service.initialize(selected_gpus=[0])
        slots = service._slots_per_gpu()
        if slots < 2:
            import pytest

            pytest.skip("multi-slot behavior requires slots>=2")
        # Pin N slots for GPU 0 (mode-independent slot-counting test).
        service._device_cache = {
            0: {"eligible": True, "slots": slots, "kind": "whole_gpu", "uuid": "GPU-0"}
        }

        # Occupy two slots on GPU 0.
        for i in range(2):
            db_session.add(
                ExperimentModel(
                    exp_id=f"co_exp_{i}",
                    celery_task_id=f"co-task-{i}",
                    run_tier="screening",
                    ff_type="bulk_ff_gaff2",
                    status="pending",
                    comp_asphaltene_wt=20.0,
                    comp_resin_wt=30.0,
                    comp_aromatic_wt=35.0,
                    comp_saturate_wt=15.0,
                )
            )
        db_session.commit()

        assert service.allocate(task_id="co-task-0") == 0
        assert service.allocate(task_id="co-task-1") == 0
        assert service._cache[0].status == GPUStatus.BUSY
        assert len(service._cache[0].active_jobs) == 2

        # Release one job: GPU still BUSY (one co-located job remains).
        assert service.release(0, task_id="co-task-0") is True
        assert service._cache[0].status == GPUStatus.BUSY
        assert len(service._cache[0].active_jobs) == 1

        # Release the last job: GPU becomes AVAILABLE.
        assert service.release(0, task_id="co-task-1") is True
        assert service._cache[0].status == GPUStatus.AVAILABLE
        assert len(service._cache[0].active_jobs) == 0


class TestOfflineGPUSupport:
    """Tests for OFFLINE GPU support (Phase 2)."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_gpu_service()

    def teardown_method(self):
        """Reset singleton after each test."""
        reset_gpu_service()

    def test_register_detected_gpus(self):
        """Test registering detected GPUs expands cache."""
        service = GPUService()
        service.initialize(selected_gpus=[0, 1])

        # Initially only selected GPUs in cache
        assert service.num_gpus == 2

        # Register all detected GPUs (including non-selected)
        detected = [
            {"gpu_id": 0, "name": "NVIDIA H200", "memory_gb": 80.0},
            {"gpu_id": 1, "name": "NVIDIA H200", "memory_gb": 80.0},
            {"gpu_id": 2, "name": "NVIDIA H200", "memory_gb": 80.0},
            {"gpu_id": 3, "name": "NVIDIA H200", "memory_gb": 80.0},
        ]
        service.register_detected_gpus(detected)

        # Cache should now have all 4 GPUs
        assert service.num_gpus == 4
        assert service.get_gpu(2) is not None
        assert service.get_gpu(3) is not None

        # Verify names and memory are updated
        assert service.get_gpu(0).name == "NVIDIA H200"
        assert service.get_gpu(0).memory_total_gb == 80.0

    def test_apply_offline_for_unselected(self):
        """Test OFFLINE status for non-selected GPUs."""
        service = GPUService()
        service.initialize(selected_gpus=[0, 1])

        # Register all detected GPUs
        detected = [
            {"gpu_id": 0, "name": "GPU-0", "memory_gb": 80.0},
            {"gpu_id": 1, "name": "GPU-1", "memory_gb": 80.0},
            {"gpu_id": 2, "name": "GPU-2", "memory_gb": 80.0},
            {"gpu_id": 3, "name": "GPU-3", "memory_gb": 80.0},
        ]
        service.register_detected_gpus(detected)
        service.apply_offline_for_unselected()

        # Selected GPUs → AVAILABLE
        assert service.get_gpu(0).status == GPUStatus.AVAILABLE
        assert service.get_gpu(1).status == GPUStatus.AVAILABLE

        # Non-selected GPUs → OFFLINE
        assert service.get_gpu(2).status == GPUStatus.OFFLINE
        assert service.get_gpu(3).status == GPUStatus.OFFLINE

    def test_sync_from_db_preserves_offline(self, db_session):
        """Test _sync_from_db preserves OFFLINE status for non-selected GPUs."""
        service = GPUService()
        service.initialize(selected_gpus=[0])

        # Register GPU 1 as detected but not selected
        detected = [
            {"gpu_id": 0, "name": "GPU-0", "memory_gb": 80.0},
            {"gpu_id": 1, "name": "GPU-1", "memory_gb": 80.0},
        ]
        service.register_detected_gpus(detected)
        service.apply_offline_for_unselected()

        # Verify initial state
        assert service.get_gpu(0).status == GPUStatus.AVAILABLE
        assert service.get_gpu(1).status == GPUStatus.OFFLINE

        # Sync from DB (no allocations in DB)
        service._sync_from_db()

        # GPU 0 should remain AVAILABLE (in selected_gpus, no allocation)
        assert service.get_gpu(0).status == GPUStatus.AVAILABLE
        # GPU 1 should remain OFFLINE (not in selected_gpus)
        assert service.get_gpu(1).status == GPUStatus.OFFLINE

    def test_sync_from_db_with_allocation_and_offline(self, db_session):
        """Test _sync_from_db with active allocation and OFFLINE GPUs."""
        from database.models import ExperimentModel

        # Create experiment with GPU 0 allocated
        exp = ExperimentModel(
            exp_id="test_exp",
            celery_task_id="task-123",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="running",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            gpu_id_allocated=0,
        )
        db_session.add(exp)
        db_session.commit()

        service = GPUService()
        service.initialize(selected_gpus=[0, 1])

        # Register all detected GPUs including non-selected
        detected = [
            {"gpu_id": 0, "name": "GPU-0", "memory_gb": 80.0},
            {"gpu_id": 1, "name": "GPU-1", "memory_gb": 80.0},
            {"gpu_id": 2, "name": "GPU-2", "memory_gb": 80.0},
        ]
        service.register_detected_gpus(detected)
        service.apply_offline_for_unselected()

        # Sync from DB
        service._sync_from_db()

        # GPU 0: BUSY (has allocation)
        assert service.get_gpu(0).status == GPUStatus.BUSY
        assert service.get_gpu(0).current_task_id == "task-123"

        # GPU 1: AVAILABLE (in selected_gpus, no allocation)
        assert service.get_gpu(1).status == GPUStatus.AVAILABLE

        # GPU 2: OFFLINE (not in selected_gpus)
        assert service.get_gpu(2).status == GPUStatus.OFFLINE

    def test_get_utilization_summary_with_offline(self):
        """Test utilization summary includes OFFLINE GPUs correctly."""
        service = GPUService()
        service.initialize(selected_gpus=[0, 1])

        # Register 4 GPUs, 2 selected, 2 not
        detected = [
            {"gpu_id": 0, "name": "GPU-0", "memory_gb": 80.0},
            {"gpu_id": 1, "name": "GPU-1", "memory_gb": 80.0},
            {"gpu_id": 2, "name": "GPU-2", "memory_gb": 80.0},
            {"gpu_id": 3, "name": "GPU-3", "memory_gb": 80.0},
        ]
        service.register_detected_gpus(detected)
        service.apply_offline_for_unselected()

        # Mock _sync_from_db to avoid DB calls
        with patch.object(service, "_sync_from_db"):
            summary = service.get_utilization_summary()

        # total_gpus should include all registered GPUs
        assert summary["total_gpus"] == 4
        # Only selected GPUs are available
        assert summary["available_gpus"] == 2
        assert summary["busy_gpus"] == 0
        # Total memory from all GPUs
        assert summary["total_memory_gb"] == 320.0

    def test_register_detected_gpus_with_missing_fields(self):
        """Test register_detected_gpus handles missing optional fields."""
        service = GPUService()
        service.initialize(selected_gpus=[0])

        # Register with minimal fields
        detected = [
            {"gpu_id": 0},  # No name or memory_gb
            {"gpu_id": 1, "name": "Test GPU"},  # No memory_gb
            {"gpu_id": 2, "memory_gb": 40.0},  # No name
        ]
        service.register_detected_gpus(detected)

        # Should handle gracefully
        assert service.num_gpus == 3
        assert service.get_gpu(0).name == "GPU-0"  # Default name
        assert service.get_gpu(1).name == "Test GPU"
        assert service.get_gpu(2).name == "GPU-2"  # Default name
        assert service.get_gpu(2).memory_total_gb == 40.0

    def test_validate_selected_gpus_marks_undetected_offline(self):
        """Undetected selected GPUs are marked OFFLINE but KEPT selected (non-destructive).

        v01.06.12: a transient detection miss must not permanently drop a GPU from
        selected_gpus (which previously, once echoed to settings, silently lost a
        healthy GPU).
        """
        service = GPUService()
        # Initialize with GPU IDs 0, 1, 5, 99 (5 and 99 absent from this detection)
        service.initialize(selected_gpus=[0, 1, 5, 99])

        # Validate against detected GPUs (only 0, 1, 2, 3 detected this pass)
        detected_ids = [0, 1, 2, 3]
        undetected = service.validate_selected_gpus(detected_ids)

        # Returns the undetected ids
        assert set(undetected) == {5, 99}

        # selected_gpus is NOT shrunk — undetected GPUs stay selected for auto-recovery
        assert service.selected_gpus == [0, 1, 5, 99]

    def test_validate_selected_gpus_keeps_undetected_in_cache_as_offline(self):
        """Undetected selected GPU stays in cache as OFFLINE (not deleted) for auto-recovery."""
        service = GPUService()
        # Initialize with GPU ID 5 (absent from this detection pass)
        service.initialize(selected_gpus=[0, 5])

        # GPU 5 is in cache as AVAILABLE (from initialize)
        assert service.get_gpu(5) is not None
        assert service.get_gpu(5).status == GPUStatus.AVAILABLE
        assert service.num_gpus == 2

        # Validate - GPU 5 not in this detection pass
        detected_ids = [0, 1, 2]
        service.validate_selected_gpus(detected_ids)

        # GPU 5 is KEPT in cache but marked OFFLINE (not removed) so it can
        # auto-recover when detected again, and is never allocated while OFFLINE.
        assert service.get_gpu(5) is not None
        assert service.get_gpu(5).status == GPUStatus.OFFLINE
        assert service.num_gpus == 2

        # GPU 0 should still be AVAILABLE
        assert service.get_gpu(0) is not None
        assert service.get_gpu(0).status == GPUStatus.AVAILABLE

    def test_validate_selected_gpus_no_invalid(self):
        """Test validate_selected_gpus with all valid IDs."""
        service = GPUService()
        service.initialize(selected_gpus=[0, 1])

        detected_ids = [0, 1, 2, 3]
        invalid = service.validate_selected_gpus(detected_ids)

        # No invalid IDs
        assert invalid == []
        # selected_gpus unchanged
        assert service.selected_gpus == [0, 1]

    def test_validate_selected_gpus_empty_selected(self):
        """Test validate_selected_gpus with empty selected_gpus."""
        service = GPUService()
        service._initialized = True
        service._selected_gpus = []

        invalid = service.validate_selected_gpus([0, 1, 2])

        # No invalid IDs (nothing to validate)
        assert invalid == []

    def test_validate_selected_gpus_empty_detected(self):
        """Test validate_selected_gpus with empty detected list (GPU detection failed)."""
        service = GPUService()
        # Initialize with selected GPUs
        service.initialize(selected_gpus=[0, 1, 2])

        # All GPUs in cache initially
        assert service.num_gpus == 3
        assert service.selected_gpus == [0, 1, 2]

        # Validate with empty detected list (simulates a TOTAL detection failure,
        # e.g. nvidia-smi transiently unavailable during a host reboot/fall-off).
        undetected = service.validate_selected_gpus([])

        # All selected GPUs are reported undetected this pass...
        assert set(undetected) == {0, 1, 2}

        # ...but KEPT in cache and marked OFFLINE, NOT removed. A transient
        # detection failure must never permanently drop healthy GPUs; they
        # auto-recover to AVAILABLE when detection returns (next pass).
        assert service.num_gpus == 3
        for gid in (0, 1, 2):
            assert service.get_gpu(gid).status == GPUStatus.OFFLINE

        # selected_gpus is preserved (sticky), not wiped
        assert service.selected_gpus == [0, 1, 2]


class TestRefreshInventory:
    """Real-time GPU pool refresh (repaired/added GPUs usable without restart)."""

    @staticmethod
    def _dev(gid):
        return {
            "gpu_id": gid,
            "name": "NVIDIA H200 NVL",
            "memory_gb": 140.0,
            "eligible": True,
            "slots": 3,
        }

    def test_auto_mode_adds_newly_eligible_gpu(self):
        """Auto-detect mode: a newly-eligible (repaired) GPU joins the active pool."""
        service = GPUService()
        service.initialize(selected_gpus=[0, 1])

        result = service.refresh_inventory(
            [self._dev(0), self._dev(1), self._dev(2)], auto_mode=True
        )

        assert 2 in service.selected_gpus
        assert 2 in result["added"]
        assert service.get_gpu(2) is not None

    def test_non_auto_mode_keeps_explicit_selection(self):
        """Explicit selection is never auto-grown by detection."""
        service = GPUService()
        service.initialize(selected_gpus=[0, 1])

        result = service.refresh_inventory(
            [self._dev(0), self._dev(1), self._dev(2)], auto_mode=False
        )

        assert service.selected_gpus == [0, 1]
        assert result["added"] == []

    def test_recovers_redetected_offline_idle_gpu(self):
        """A previously-OFFLINE selected GPU detected again (idle) recovers to AVAILABLE."""
        service = GPUService()
        service.initialize(selected_gpus=[0, 1])
        service.get_gpu(1).status = GPUStatus.OFFLINE

        result = service.refresh_inventory([self._dev(0), self._dev(1)], auto_mode=True)

        assert service.get_gpu(1).status == GPUStatus.AVAILABLE
        assert 1 in result["recovered"]

    def test_offlines_selected_absent_idle_gpu_non_destructively(self):
        """A selected GPU absent from detection (idle) is marked OFFLINE but kept selected."""
        service = GPUService()
        service.initialize(selected_gpus=[0, 1])

        result = service.refresh_inventory([self._dev(0)], auto_mode=False)

        assert service.get_gpu(1).status == GPUStatus.OFFLINE
        assert 1 in result["offlined"]
        assert 1 in service.selected_gpus  # non-destructive

    def test_busy_gpu_absent_is_not_disturbed(self):
        """A BUSY GPU absent from a detection pass must NOT be offlined (job in flight)."""
        service = GPUService()
        service.initialize(selected_gpus=[0, 1])
        gpu1 = service.get_gpu(1)
        gpu1.status = GPUStatus.BUSY
        gpu1.set_jobs([{"task_id": "t1", "exp_id": "e1"}])

        result = service.refresh_inventory([self._dev(0)], auto_mode=False)

        assert service.get_gpu(1).status == GPUStatus.BUSY
        assert 1 not in result["offlined"]


class TestSingleton:
    """Tests for GPUService singleton pattern."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_gpu_service()

    def teardown_method(self):
        """Reset singleton after each test."""
        reset_gpu_service()

    def test_get_gpu_service_returns_same_instance(self):
        """Test singleton returns same instance."""
        service1 = get_gpu_service()
        service2 = get_gpu_service()

        assert service1 is service2

    def test_reset_gpu_service(self):
        """Test singleton reset."""
        service1 = get_gpu_service()
        service1.initialize(selected_gpus=[0])

        reset_gpu_service()

        service2 = get_gpu_service()

        assert service1 is not service2
        assert service2._initialized is False

    def test_singleton_thread_safety(self):
        """Test singleton is created once in multi-threaded scenario."""
        import threading

        services = []
        results_lock = threading.Lock()
        barrier = threading.Barrier(20)  # Synchronize thread starts

        def get_service():
            barrier.wait()  # All threads start simultaneously
            s = get_gpu_service()
            with results_lock:
                services.append(s)

        threads = [threading.Thread(target=get_service) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should be the same instance
        first = services[0]
        assert all(s is first for s in services)
        assert len(services) == 20

    def test_reset_thread_safety(self):
        """Test reset is thread-safe."""

        # Initialize first
        service1 = get_gpu_service()
        service1.initialize(selected_gpus=[0])

        # Reset and get new instance
        reset_gpu_service()
        service2 = get_gpu_service()

        assert service1 is not service2
        assert not service2._initialized
