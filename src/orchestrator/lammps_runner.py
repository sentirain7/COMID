"""
LAMMPS Runner.

Provides interface for executing LAMMPS simulations with process tracking.
"""

import os
import re
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from common.logging import get_logger
from contracts.interfaces import AbstractLAMMPSRunner
from contracts.schemas import LAMMPSRunResult, ProtocolResult
from orchestrator.process_tracker import ProcessRegistrationConflict

if TYPE_CHECKING:
    from orchestrator.process_tracker import ProcessTracker

logger = get_logger("orchestrator.lammps_runner")


def calculate_threads_per_job(
    selected_gpu_count: int,
    min_threads: int = 1,
    accel_mode: str | None = None,
    target_atoms: int | None = None,
    slots_per_gpu: int = 1,
) -> int:
    """
    Calculate CPU threads per job based on system resources and acceleration mode.

    For GPU mode: Scale threads based on atom count (v00.97.00).
    For CPU mode: Distribute cores evenly across concurrent jobs.

    Args:
        selected_gpu_count: Number of selected GPUs (= max concurrent jobs)
        min_threads: Minimum threads per job (default 1)
        accel_mode: Acceleration mode from LammpsCaps probe
        target_atoms: Target atom count from tier policy (for GPU thread scaling)

    Returns:
        Threads per job

    Examples:
        - GPU mode, 100k atoms → 8 threads/job
        - GPU mode, 150k atoms → 12 threads/job
        - GPU mode, 200k atoms → 16 threads/job
        - CPU mode, 256 cores, 4 jobs → 64 threads/job
        - MPI mode, 256 cores, 4 procs → 64 threads/job
    """
    cpu_count = os.cpu_count() or 4  # Fallback to 4 if detection fails

    if accel_mode == "kokkos_gpu":
        # GPU mode: scale threads by atom count, then CAP by the per-job CPU
        # budget so co-located jobs don't oversubscribe host cores. With N jobs
        # co-located per GPU (slots_per_gpu), total concurrent jobs =
        # selected_gpu_count * slots_per_gpu; the OpenMP threads must satisfy
        # Sum(Nt) <= cpu_count (LAMMPS rule Np*Nt <= cores/node). Oversubscription
        # under MPS causes core contention and cudaErrorIllegalAddress (v01.05.56
        # C). slots_per_gpu defaults to 1 → budget = cpu_count/gpu_count, so the
        # atom-based value (<=16) is unchanged in single-job mode (byte-identical).
        if target_atoms is None or target_atoms <= 120_000:
            atom_based = 8
        elif target_atoms <= 175_000:
            atom_based = 12
        else:
            atom_based = 16

        concurrent_jobs = max(1, selected_gpu_count) * max(1, slots_per_gpu)
        budget = max(min_threads, cpu_count // concurrent_jobs)
        return min(atom_based, budget)
    elif accel_mode == "kokkos_cpu":
        # CPU mode: Distribute cores across concurrent jobs
        threads = max(cpu_count // max(selected_gpu_count, 1), min_threads)
        return min(threads, 64)  # Cap at 64 to avoid excessive threading overhead
    else:
        # MPI/Serial mode: Use reasonable default
        threads = max(cpu_count // max(selected_gpu_count, 1), min_threads)
        return min(threads, 64)


@dataclass
class LAMMPSConfig:
    """LAMMPS execution configuration."""

    executable: str = "lmp"
    mpi_executable: str = "mpirun"
    num_procs: int = 4
    num_threads: int = 4  # KOKKOS CPU threads (auto-calculated in tasks.py)
    gpu_enabled: bool = False
    gpu_id: int = 0
    timeout_seconds: int = 86400  # 24 hours default
    log_suffix: str = ".lammps"
    heartbeat_interval_seconds: int = 30  # Heartbeat interval for long runs
    accel_mode: str | None = None  # AccelMode value from LammpsCaps probe


class LAMMPSRunner(AbstractLAMMPSRunner):
    """
    LAMMPS simulation runner with process tracking.

    Handles execution of LAMMPS simulations with:
    - GPU support via KOKKOS
    - Process tracking for recovery
    - Heartbeat updates during long runs
    """

    def __init__(
        self,
        config: LAMMPSConfig | None = None,
        work_dir: Path | None = None,
        process_tracker: Optional["ProcessTracker"] = None,
    ):
        """
        Initialize runner.

        Args:
            config: LAMMPS configuration
            work_dir: Working directory for simulations
            process_tracker: Optional ProcessTracker for persistence
        """
        self.config = config or LAMMPSConfig()
        self.work_dir = Path(work_dir) if work_dir else Path.cwd() / "runs"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.process_tracker = process_tracker
        self._hostname = socket.gethostname()

        # Track current running process for signal handling
        self._current_process: subprocess.Popen | None = None
        self._setup_signal_handlers()

    def _setup_signal_handlers(self) -> None:
        """
        Set up signal handlers to kill LAMMPS subprocess when Celery worker is terminated.

        This ensures that Cancel operations properly kill the LAMMPS process,
        not just the Celery worker.
        """
        import signal

        def signal_handler(signum: int, frame) -> None:
            """Handle termination signals by killing the LAMMPS subprocess."""
            if self._current_process is not None:
                logger.info(
                    f"Received signal {signum}, killing LAMMPS process "
                    f"PID {self._current_process.pid}"
                )
                try:
                    self._current_process.kill()
                    self._current_process.wait(timeout=5)
                except Exception as e:
                    logger.warning(f"Failed to kill LAMMPS process: {e}")

        # Register handlers for common termination signals
        try:
            signal.signal(signal.SIGTERM, signal_handler)
            signal.signal(signal.SIGINT, signal_handler)
        except Exception as e:
            logger.warning(f"Failed to set up signal handlers: {e}")

    def run(
        self,
        protocol_result: ProtocolResult,
        timeout: int | None = None,
        *,
        exp_id: str | None = None,
        total_steps: int | None = None,
    ) -> LAMMPSRunResult:
        """
        Execute LAMMPS simulation with process tracking.

        Args:
            protocol_result: Protocol with input script path
            exp_id: Experiment ID for process tracking
            total_steps: Total expected steps for progress tracking
            timeout: Optional timeout in seconds (overrides config)

        Returns:
            LAMMPSRunResult with execution status
        """
        input_file = Path(protocol_result.input_script_path)
        run_dir = input_file.parent

        if not input_file.exists():
            return LAMMPSRunResult(
                success=False,
                log_file="",
                dump_files=[],
                wall_time_seconds=0.0,
                exit_code=-1,
                error_message=f"Input file not found: {input_file}",
                exp_id=exp_id,
            )

        logger.info(f"Starting LAMMPS run: {input_file}")

        # Build command
        cmd = self._build_command(input_file)
        logger.debug(f"Command: {' '.join(cmd)}")

        # Set up environment with CUDA_VISIBLE_DEVICES and OMP_NUM_THREADS for GPU mode.
        # CUDA MPS: GPU당 다중잡일 때 부모(start_all.sh)가 CUDA_MPS_PIPE_DIRECTORY를
        # export하므로 os.environ.copy()로 자동 상속 → 이 LAMMPS가 MPS 클라이언트가
        # 되어 같은 GPU의 다른 잡과 진짜 동시 실행(별도 설정 불요).
        env = os.environ.copy()
        if self.config.gpu_enabled:
            # Route by hardware UUID, NOT the raw integer index. Under CUDA MPS a
            # non-contiguous visible set is renumbered to logical 0..N-1, so a
            # physical index (e.g. "6") yields cudaErrorNoDevice and silently kills
            # every job on that GPU. UUID is hardware-pinned and remap-immune.
            # See memory `gpu-uuid-routing-principle`. Falls back to str(gpu_id)
            # when no UUID is available (non-GPU env).
            from monitoring.gpu_collector import gpu_uuid_for

            cuda_device = gpu_uuid_for(self.config.gpu_id)
            env["CUDA_VISIBLE_DEVICES"] = cuda_device
            env["OMP_NUM_THREADS"] = str(self.config.num_threads)
            # OMP_PROC_BIND=false: don't pin OpenMP threads. Under MPS co-location
            # multiple LAMMPS processes share host cores; pinning (spread/true)
            # would make them fight over the same cores. false lets the OS balance
            # and also suppresses the non-fatal KOKKOS "OMP_PROC_BIND not set" /
            # "MPI ranks must be bound to exclusive CPU sets" warnings that were
            # being mis-surfaced as failure reasons (v01.05.56 C).
            env.setdefault("OMP_PROC_BIND", "false")
            logger.info(
                f"Environment: CUDA_VISIBLE_DEVICES={cuda_device} "
                f"(logical gpu_id={self.config.gpu_id}), "
                f"OMP_NUM_THREADS={self.config.num_threads}, OMP_PROC_BIND=false"
            )

        # Log full command for debugging
        logger.info(f"LAMMPS command: {' '.join(cmd)}")

        # Use total_steps from protocol_result if not provided
        if total_steps is None:
            total_steps = protocol_result.estimated_steps

        # Run LAMMPS with Popen for process tracking
        start_time = time.time()
        process = None
        log_file = str(run_dir / f"log{self.config.log_suffix}")

        try:
            # Start process with Popen
            process = subprocess.Popen(
                cmd,
                cwd=str(run_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )

            # Track current process for signal handling (Cancel support)
            self._current_process = process

            # Register process for tracking
            if self.process_tracker and exp_id:
                try:
                    self.process_tracker.register_process(
                        exp_id=exp_id,
                        pid=process.pid,
                        hostname=self._hostname,
                        working_dir=str(run_dir),
                        gpu_id=self.config.gpu_id if self.config.gpu_enabled else None,
                        total_steps=total_steps,
                    )
                except ProcessRegistrationConflict as conflict:
                    # FATAL backstop: registration detected a duplicate/conflicting
                    # lmp for this experiment. Historically this RuntimeError was
                    # swallowed as a warning AFTER Popen, so the duplicate lmp kept
                    # running invisibly (two+ lmp for one experiment). Kill the
                    # just-launched process and abort so the duplicate never
                    # survives; the legitimate owner keeps running.
                    logger.error(
                        "Aborting duplicate/conflicting lmp for %s (PID %s): %s",
                        exp_id,
                        process.pid,
                        conflict,
                    )
                    try:
                        process.kill()
                        process.wait(timeout=5)
                    except Exception:
                        pass
                    self._current_process = None
                    raise
                except Exception as e:
                    logger.warning(f"Failed to register process: {e}")

            logger.info(f"LAMMPS started with PID {process.pid}")

            # Wait for completion with periodic heartbeat updates
            effective_timeout = timeout if timeout is not None else self.config.timeout_seconds
            stdout, stderr = self._wait_with_heartbeat(
                process=process,
                exp_id=exp_id,
                log_file=Path(log_file),
                timeout=effective_timeout,
            )

            wall_time = time.time() - start_time

            # Find dump files
            dump_files = self._find_dump_files(run_dir)

            success = process.returncode == 0
            error_message = None

            if not success:
                stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""
                stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""
                error_message = self._extract_error(stderr_text, stdout_text)
                logger.error(f"LAMMPS failed: {error_message}")
            else:
                logger.info(f"LAMMPS completed in {wall_time:.1f}s")

            return LAMMPSRunResult(
                success=success,
                log_file=log_file,
                dump_files=dump_files,
                wall_time_seconds=wall_time,
                exit_code=process.returncode,
                error_message=error_message,
                exp_id=exp_id,
            )

        except subprocess.TimeoutExpired:
            wall_time = time.time() - start_time
            logger.error(f"LAMMPS timeout after {wall_time:.1f}s")

            # Kill the process
            if process:
                try:
                    process.kill()
                    process.wait(timeout=5)
                except Exception:
                    pass

            return LAMMPSRunResult(
                success=False,
                log_file=log_file,
                dump_files=[],
                wall_time_seconds=wall_time,
                exit_code=-1,
                error_message="Simulation timeout",
                exp_id=exp_id,
            )

        except Exception as e:
            wall_time = time.time() - start_time
            logger.error(f"LAMMPS error: {e}")

            # Kill the process
            if process:
                try:
                    process.kill()
                    process.wait(timeout=5)
                except Exception:
                    pass

            return LAMMPSRunResult(
                success=False,
                log_file="",
                dump_files=[],
                wall_time_seconds=wall_time,
                exit_code=-1,
                error_message=str(e),
                exp_id=exp_id,
            )

        finally:
            # Clear current process reference (for signal handler)
            self._current_process = None

            # Unregister process after completion
            if self.process_tracker and exp_id:
                try:
                    self.process_tracker.unregister_process(exp_id)
                except Exception as e:
                    logger.warning(f"Failed to unregister process: {e}")

    def _wait_with_heartbeat(
        self,
        process: subprocess.Popen,
        exp_id: str | None,
        log_file: Path,
        timeout: int,
    ) -> tuple[bytes, bytes]:
        """
        Wait for process with periodic heartbeat updates.

        Args:
            process: Running Popen process
            exp_id: Experiment ID for heartbeat updates
            log_file: Path to LAMMPS log file
            timeout: Timeout in seconds

        Returns:
            Tuple of (stdout, stderr)
        """
        start_time = time.time()
        heartbeat_interval = self.config.heartbeat_interval_seconds
        last_heartbeat = start_time

        while True:
            # Check if process completed
            try:
                stdout, stderr = process.communicate(timeout=heartbeat_interval)
                return stdout, stderr
            except subprocess.TimeoutExpired:
                pass

            # Check overall timeout
            elapsed = time.time() - start_time
            if elapsed > timeout:
                raise subprocess.TimeoutExpired(cmd=[], timeout=timeout)

            # Send heartbeat update
            if self.process_tracker and exp_id:
                current_time = time.time()
                if current_time - last_heartbeat >= heartbeat_interval:
                    current_step, temperature, pressure, density, energy = (
                        self._parse_latest_telemetry(log_file)
                    )
                    try:
                        self.process_tracker.update_heartbeat(
                            exp_id=exp_id,
                            current_step=current_step,
                            pid=process.pid,
                            temperature=temperature,
                            pressure=pressure,
                            density=density,
                            energy=energy,
                        )
                    except Exception as e:
                        logger.debug(f"Heartbeat update failed: {e}")
                    last_heartbeat = current_time

    def _parse_latest_telemetry(
        self, log_file: Path
    ) -> tuple[int | None, float | None, float | None, float | None, float | None]:
        """Parse latest step and thermo telemetry from log tail."""
        if not log_file.exists():
            return None, None, None, None, None

        # First try structured parser.
        try:
            from parsers.log_parser import LogParser

            parser = LogParser()
            result = parser.parse_tail(log_file, bytes_to_read=102400, max_points=50)
            td = result.thermo_data or {}

            steps = td.get("Step") or []
            if steps:
                current_step = int(float(steps[-1]))
                temperature = self._safe_float((td.get("Temp") or [None])[-1])
                pressure = self._safe_float((td.get("Press") or [None])[-1])
                density = self._safe_float((td.get("Density") or [None])[-1])
                energy = self._safe_float((td.get("PotEng") or [None])[-1])
                return current_step, temperature, pressure, density, energy
        except Exception:
            pass

        # Fallback: scan numeric lines in last 100KB (works even if header is missing).
        try:
            with open(log_file, "rb") as f:
                f.seek(0, 2)
                file_size = f.tell()
                read_size = min(102400, file_size)
                f.seek(-read_size, 2)
                content = f.read().decode("utf-8", errors="replace")

            for line in reversed(content.splitlines()):
                parts = line.split()
                if len(parts) < 2:
                    continue
                if not re.match(r"^\d+$", parts[0]):
                    continue

                current_step = int(parts[0])

                # nvt/npt thermo: Step Temp Pe Ke Etot Press Vol Density
                if len(parts) >= 8:
                    return (
                        current_step,
                        self._safe_float(parts[1]),
                        self._safe_float(parts[5]),
                        self._safe_float(parts[7]),
                        self._safe_float(parts[2]),
                    )

                # minimize thermo: Step Pe Ke Etot Press Vol Density (no Temp)
                if len(parts) >= 7:
                    return (
                        current_step,
                        None,
                        self._safe_float(parts[4]),
                        self._safe_float(parts[6]),
                        self._safe_float(parts[1]),
                    )
                return current_step, None, None, None, None
        except Exception:
            pass

        return None, None, None, None, None

    def _parse_current_step(self, log_file: Path) -> int | None:
        """
        Parse current step from LAMMPS log file.

        Args:
            log_file: Path to log file

        Returns:
            Current step number or None
        """
        step, _, _, _, _ = self._parse_latest_telemetry(log_file)
        return step

    @staticmethod
    def _safe_float(value: object) -> float | None:
        """Best-effort float conversion."""
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    def _build_command(self, input_file: Path) -> list[str]:
        """Build LAMMPS command based on detected acceleration mode.

        Uses ``accel_mode`` from LammpsCaps probe when available,
        falling back to the legacy ``gpu_enabled`` flag for backward
        compatibility.
        """
        accel = self.config.accel_mode
        input_name = str(input_file.name)

        if accel == "kokkos_gpu":
            # KOKKOS GPU: 1 MPI rank, 1 GPU, T CPU threads (OpenMP)
            # Threads handle data preparation while GPU computes
            kokkos_args = [
                "-k",
                "on",
                "g",
                "1",
                "t",
                str(self.config.num_threads),
                "-sf",
                "kk",
                "-in",
                input_name,
            ]
            if self.config.mpi_executable:
                cmd = [self.config.mpi_executable, "-np", "1", self.config.executable, *kokkos_args]
            else:
                cmd = [self.config.executable, *kokkos_args]
            logger.info(
                f"KOKKOS GPU mode: GPU {self.config.gpu_id}, {self.config.num_threads} CPU threads"
            )
        elif accel == "kokkos_cpu":
            # KOKKOS CPU-only (OpenMP threads)
            # Use MPI launcher only if mpi_executable is available
            base = [self.config.executable]
            if self.config.mpi_executable:
                base = [self.config.mpi_executable, "-np", "1", self.config.executable]
            cmd = [
                *base,
                "-k",
                "on",
                "t",
                str(self.config.num_threads),
                "-sf",
                "kk",
                "-in",
                input_name,
            ]
            logger.info(f"KOKKOS CPU mode: {self.config.num_threads} threads")
        elif accel == "mpi_only":
            if self.config.num_procs > 1 and self.config.mpi_executable:
                cmd = [
                    self.config.mpi_executable,
                    "-np",
                    str(self.config.num_procs),
                    self.config.executable,
                    "-in",
                    input_name,
                ]
            else:
                cmd = [self.config.executable, "-in", input_name]
            logger.info(f"MPI-only mode: {self.config.num_procs} procs")
        elif accel == "serial":
            cmd = [self.config.executable, "-in", input_name]
            logger.info("Serial mode")
        else:
            # Legacy fallback: use gpu_enabled flag (backward compatible)
            if self.config.gpu_enabled:
                cmd = [
                    self.config.mpi_executable,
                    "-np",
                    "1",
                    self.config.executable,
                    "-k",
                    "on",
                    "g",
                    "1",
                    "t",
                    str(self.config.num_threads),
                    "-sf",
                    "kk",
                    "-in",
                    input_name,
                ]
                logger.info(
                    f"GPU enabled (legacy): KOKKOS with GPU {self.config.gpu_id}, "
                    f"{self.config.num_threads} CPU threads"
                )
            elif self.config.num_procs > 1:
                cmd = [
                    self.config.mpi_executable,
                    "-np",
                    str(self.config.num_procs),
                    self.config.executable,
                    "-in",
                    input_name,
                ]
            else:
                cmd = [self.config.executable, "-in", input_name]

        return cmd

    def _find_dump_files(self, run_dir: Path) -> list[str]:
        """Find dump files in run directory."""
        dump_patterns = ["*.dump", "dump.*", "*.lammpstrj"]
        dump_files = []

        for pattern in dump_patterns:
            dump_files.extend(str(f) for f in run_dir.glob(pattern))

        return sorted(dump_files)

    def _extract_error(self, stderr: str, stdout: str) -> str:
        """Extract error message from output."""
        # Look for ERROR lines
        for line in stderr.split("\n") + stdout.split("\n"):
            if "ERROR" in line:
                return line.strip()

        # Return last non-empty line
        for line in reversed(stderr.split("\n")):
            if line.strip():
                return line.strip()

        return "Unknown error"

    def validate_installation(self) -> tuple[bool, str]:
        """
        Validate LAMMPS installation.

        Returns:
            Tuple of (is_valid, message)
        """
        try:
            subprocess.run(
                [self.config.executable, "-help"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return True, f"LAMMPS found: {self.config.executable}"
        except FileNotFoundError:
            return False, f"LAMMPS executable not found: {self.config.executable}"
        except Exception as e:
            return False, f"Error checking LAMMPS: {e}"

    def check_lammps_available(self) -> bool:
        """Check if LAMMPS is available (AbstractLAMMPSRunner interface)."""
        is_valid, _ = self.validate_installation()
        return is_valid

    def get_lammps_version(self) -> str:
        """Get LAMMPS version string (AbstractLAMMPSRunner interface)."""
        try:
            result = subprocess.run(
                [self.config.executable, "-help"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            for line in result.stdout.split("\n"):
                if "LAMMPS" in line:
                    return line.strip()
            return "unknown"
        except Exception:
            return "unavailable"


class MockLAMMPSRunner(AbstractLAMMPSRunner):
    """Mock LAMMPS runner for testing."""

    def __init__(self, success: bool = True, delay: float = 0.1):
        """
        Initialize mock runner.

        Args:
            success: Whether runs should succeed
            delay: Simulated delay in seconds
        """
        self.success = success
        self.delay = delay
        self.run_count = 0

    def run(
        self,
        protocol_result: ProtocolResult,
        timeout: int | None = None,
        *,
        exp_id: str | None = None,
        **kwargs,
    ) -> LAMMPSRunResult:
        """Execute mock simulation."""
        import time

        time.sleep(self.delay)
        self.run_count += 1

        if self.success:
            return LAMMPSRunResult(
                success=True,
                log_file="/mock/log.lammps",
                dump_files=["/mock/dump.0.lammpstrj"],
                wall_time_seconds=self.delay,
                exit_code=0,
                exp_id=exp_id,
            )
        else:
            return LAMMPSRunResult(
                success=False,
                log_file="/mock/log.lammps",
                dump_files=[],
                wall_time_seconds=self.delay,
                exit_code=1,
                error_message="Mock failure",
                exp_id=exp_id,
            )

    def check_lammps_available(self) -> bool:
        """Check if LAMMPS is available (mock: always True)."""
        return True

    def get_lammps_version(self) -> str:
        """Get LAMMPS version string (mock)."""
        return "LAMMPS Mock (test)"
