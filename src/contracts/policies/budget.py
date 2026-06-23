"""
Job budgeting policy - SSOT for GPU allocation and job limits.

All sessions must use this policy for job scheduling decisions.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class JobPriority(StrEnum):
    """Job priority levels."""

    HIGHEST = "highest"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    LOWEST = "lowest"


class SimilarExistingAction(StrEnum):
    """유사 실험 존재 시 사용자 선택 옵션."""

    UNSPECIFIED = "unspecified"
    KEEP_PRIORITY = "keep_priority"
    DEMOTE_PRIORITY = "demote_priority"


# Priority ordering from highest to lowest
_PRIORITY_ORDER: list[JobPriority] = [
    JobPriority.HIGHEST,
    JobPriority.HIGH,
    JobPriority.MEDIUM,
    JobPriority.LOW,
    JobPriority.LOWEST,
]


def demote_priority(priority: JobPriority, steps: int = 1) -> JobPriority:
    """우선순위를 지정된 단계만큼 낮춤.

    Args:
        priority: 현재 우선순위
        steps: 낮출 단계 수 (기본값 1)

    Returns:
        낮춰진 우선순위 (최저 LOWEST로 제한)
    """
    try:
        current_idx = _PRIORITY_ORDER.index(priority)
    except ValueError:
        return JobPriority.LOWEST
    new_idx = min(current_idx + steps, len(_PRIORITY_ORDER) - 1)
    return _PRIORITY_ORDER[new_idx]


class TierPriority(BaseModel):
    """Priority mapping for run tiers."""

    screening: JobPriority = Field(JobPriority.HIGH)
    confirm: JobPriority = Field(JobPriority.MEDIUM)
    viscosity: JobPriority = Field(JobPriority.LOWEST)
    validation: JobPriority = Field(JobPriority.LOW)


class SafetyLimits(BaseModel):
    """Safety limits for different tiers."""

    max_atoms_screening: int = Field(120000, description="Max atoms for screening")
    max_atoms_confirm: int = Field(200000, description="Max atoms for confirm")
    max_atoms_viscosity: int = Field(150000, description="Max atoms for viscosity")
    max_atoms_validation: int = Field(100000, description="Max atoms for validation")


class JobBudgetingPolicy(BaseModel):
    """
    Job budgeting policy - SSOT for GPU allocation and job limits.

    This policy controls resource usage to prevent GPU monopolization.

    Note: max_queued_jobs is derived from QueueLimitsPolicy.batch_submission_chunk_size (SSOT).
    """

    # Concurrency limits
    # max_concurrent_jobs_per_gpu=3 (운영 결정): 4-GPU MPS 실측(docs/architecture/
    # md-speed-optimization-exploration.md §4.1·4.4)은 6슬롯에서 처리량 4.3×를
    # 보였으나, 대량배치(300잡) 시 GPU당 6잡 co-location 경합(99% util 포화·
    # `lmp -h` 프로브 타임아웃·과구독)으로 실패가 누적돼 슬롯을 3으로 낮춤 —
    # per-GPU 경합을 줄여 안정성 우선. 6→3은 정책값 변경만으로 전 소비처
    # (gpu_service 슬롯 캡·Celery 동시성·스레드 예산·MPS 기동)에 자동 전파.
    # 할당은 gpu_service의 원자적 전역 락 + 단일 트랜잭션 안 슬롯 카운트로
    # 직렬화(이중배정 방지 불변). 6 H200 × 3 = 18 동시.
    max_concurrent_jobs_total: int = Field(
        18, description="Max total concurrent jobs (gpus x per-gpu slots ceiling)"
    )
    max_concurrent_jobs_per_gpu: int = Field(3, description="Max jobs per GPU (MPS)")
    default_gpu_per_job: int = Field(1, description="Default GPUs per job")

    # GPU 공유 모드 — GPU당 다중잡 실현 방식 (SSOT).
    #   "mps" : whole GPU에 N잡 co-location (**현재 활성 기본**). 처리량 최대(GPU x N).
    #   "mig" : MIG instance 단위 1잡/instance — 메모리·SM·결함 완전격리(목표). 단
    #           MIG 활성화는 GPU에 클라이언트 0개 필요 — 이 머신은 Xorg가 모든 H200을
    #           점유해 셋업이 막혀 있다(docs/operations/mig-setup-xorg.md). MIG 가능
    #           환경에서 opt-in: 이 값을 mig로 + scripts/setup_mig.sh.
    #   "none": 1잡/GPU.   "auto": MIG instance 감지 시 mig, 아니면 none.
    # 기본 mps: MIG 셋업이 이 하드웨어(Xorg가 H200 점유)에서 막혀 있어 처리량을 위해
    # MPS 사용. MIG 인프라(detect/route/slot/setup)는 구현돼 있어 환경이 갖춰지면
    # 정책 한 줄로 전환. MIG 모드만 켜지고 인스턴스 0개인 GPU는 enumerate가 모드와
    # 무관하게 부적격 처리(unusable 보호).
    gpu_sharing_mode: str = Field("mps", description="GPU sharing: mps|mig|none|auto")
    # MIG 프로파일(H200 분할). 재벤치로 확정 — 1g.18gb=7/GPU(최대병렬·소형잡),
    # 2g.35gb=3/GPU(여유), 3g.71gb=2/GPU(대형잡). setup_mig가 이 값으로 생성.
    mig_profile: str = Field("1g.18gb", description="MIG instance profile for setup")
    # REMOVED: max_queued_jobs - now uses QueueLimitsPolicy.batch_submission_chunk_size as SSOT

    # GPU 적격 메모리 하한 — auto-detect 폴백에서 이 미만 GPU(예: 디스플레이용
    # 소형 GPU)를 MD 잡 배정 대상에서 제외. 데이터센터급(A100 40GB+, H200 143GB)은
    # 통과, 소비자급(≤24GB)은 제외. settings.json에 selected_gpus를 명시하면
    # 그 값이 우선(이 필터는 미설정 시 자동선택에만 적용). 필터가 전부 제외하면
    # strand 방지를 위해 무필터로 폴백(detect_eligible_compute_gpus).
    min_gpu_memory_gb: float = Field(
        32.0, description="Min GPU memory (GB) to be eligible for MD job allocation"
    )

    # 동시 구조빌드(Packmol) 상한 — 빌드는 GPU 불요이나 CPU/RAM 집약적이라
    # GPU잡과 같은 워커풀(gpu_count x slots)을 공유하면 대량배치 시 수십 개
    # Packmol이 동시에 떠 CPU/RAM이 고갈된다(v01.05.39 wall-clock 병리). 0 이하면
    # 무제한(레거시 동작). 크로스프로세스 fcntl 슬롯 세마포어로 강제.
    max_concurrent_builds: int = Field(
        8, description="Max concurrent Packmol structure builds (CPU/RAM bound, 0=unlimited)"
    )

    # Priority mapping
    tier_priority: TierPriority = Field(
        default_factory=TierPriority, description="Priority by run tier"
    )

    # Safety limits
    safety_limits: SafetyLimits = Field(
        default_factory=SafetyLimits, description="Safety limits by tier"
    )

    # Queue settings
    queue_backend: str = Field("celery", description="Queue backend")
    queue_broker: str = Field("redis", description="Queue broker")
    hpc_submission: str = Field("slurm_direct", description="HPC submission method")

    def get_priority(self, tier: str) -> JobPriority:
        """
        Get priority for a tier.

        Args:
            tier: Run tier name

        Returns:
            JobPriority for the tier
        """
        return getattr(self.tier_priority, tier, JobPriority.MEDIUM)

    def get_max_atoms(self, tier: str) -> int:
        """
        Get maximum atom count for a tier.

        Args:
            tier: Run tier name

        Returns:
            Maximum atom count
        """
        attr_name = f"max_atoms_{tier}"
        return getattr(self.safety_limits, attr_name, 100000)

    def can_submit_job(
        self,
        tier: str,
        atom_count: int,
        current_jobs: int,
        gpu_usage: dict[int, int],
        queued_jobs: int = 0,
    ) -> tuple[bool, str | None]:
        """
        Check if a job can be submitted.

        Args:
            tier: Run tier name
            atom_count: Requested atom count
            current_jobs: Current number of RUNNING jobs (not queued)
            gpu_usage: Current GPU usage (gpu_id -> job_count)
            queued_jobs: Current number of QUEUED/PENDING jobs

        Returns:
            Tuple of (can_submit, reason_if_not)
        """
        # Check queue depth limit (SSOT: QueueLimitsPolicy.max_batch_queued)
        # batch_submission_chunk_size is a per-call cap, not the queue depth limit.
        max_queued = DEFAULT_QUEUE_LIMITS_POLICY.max_batch_queued
        if queued_jobs >= max_queued:
            return False, f"Queue full: {queued_jobs}/{max_queued}"

        # Note: We do NOT block submission based on current_jobs count.
        # Jobs will queue in Celery and wait for GPU via retry mechanism.
        # The max_concurrent_jobs_total is enforced by GPU allocation, not submission.

        # Check atom count limit
        max_atoms = self.get_max_atoms(tier)
        if atom_count > max_atoms:
            return False, f"Atom count {atom_count} exceeds limit {max_atoms} for {tier}"

        # GPU configuration check (not availability)
        # Only reject if no GPUs are configured at all (settings error)
        # If GPUs are busy, allow submit - task will retry via failure.py policy
        if not gpu_usage:
            return False, "No GPUs configured in settings"
        # GPU availability is checked at task execution time by GPUService.allocate()
        # If no GPU available, task retries per failure.py gpu_not_available_* policy

        # Special rules for large jobs
        if tier == "confirm" and atom_count >= 200000:
            # Only one 200k job at a time
            if current_jobs > 0:
                return False, "200k confirm jobs run exclusively"

        if tier == "viscosity":
            # Viscosity only when no other jobs
            if current_jobs > 0:
                return False, "Viscosity jobs run when queue is empty"

        return True, None

    def select_gpu(self, gpu_usage: dict[int, int]) -> int | None:
        """
        Select GPU for a new job.

        Args:
            gpu_usage: Current GPU usage (gpu_id -> job_count)

        Returns:
            GPU ID to use, or None if none available
        """
        # Select GPU with least jobs
        available = [
            (gpu_id, jobs)
            for gpu_id, jobs in gpu_usage.items()
            if jobs < self.max_concurrent_jobs_per_gpu
        ]
        if not available:
            return None
        return min(available, key=lambda x: x[1])[0]

    def get_queue_position(self, tier: str, pending_jobs: list[dict]) -> int:
        """
        Calculate queue position for a new job based on priority.

        Args:
            tier: Run tier name
            pending_jobs: List of pending job info dicts

        Returns:
            Position in queue (0 = next)
        """
        priority = self.get_priority(tier)
        priority_order = [
            JobPriority.HIGHEST,
            JobPriority.HIGH,
            JobPriority.MEDIUM,
            JobPriority.LOW,
            JobPriority.LOWEST,
        ]
        priority_rank = priority_order.index(priority)

        position = 0
        for job in pending_jobs:
            job_priority = self.get_priority(job.get("tier", "screening"))
            job_rank = priority_order.index(job_priority)
            if job_rank <= priority_rank:
                position += 1

        return position


class DuplicateDetectionPolicy(BaseModel):
    """중복/유사 실험 감지 정책."""

    composition_similarity_enabled: bool = Field(True, description="유사 조성 감지 활성화")
    temperature_tolerance_k: float = Field(5.0, ge=0.0, le=50.0, description="온도 허용 오차 (K)")
    similar_experiment_priority_demotion: int = Field(
        2, ge=1, le=4, description="유사 실험 시 우선순위 하향 단계"
    )
    max_similarity_check_limit: int = Field(
        500, ge=10, le=2000, description="유사도 검색 최대 레코드 수"
    )


class QueueLimitsPolicy(BaseModel):
    """작업 유형별 큐 한계."""

    max_interactive_queued: int = Field(
        100, ge=10, le=1000, description="인터랙티브 큐 최대 작업 수"
    )
    max_batch_queued: int = Field(
        1000, ge=50, le=5000, description="배치 큐 최대 작업 수 (queue depth 상한)"
    )
    max_total_queued: int = Field(2000, ge=100, le=10000, description="전체 큐 최대 작업 수")
    batch_submission_chunk_size: int = Field(
        1000, ge=10, le=2000, description="한 번의 submit 호출 최대 제출 수 (per-call cap)"
    )


# Default instances for convenience
DEFAULT_JOB_BUDGETING_POLICY = JobBudgetingPolicy()
DEFAULT_DUPLICATE_DETECTION_POLICY = DuplicateDetectionPolicy()
DEFAULT_QUEUE_LIMITS_POLICY = QueueLimitsPolicy()
