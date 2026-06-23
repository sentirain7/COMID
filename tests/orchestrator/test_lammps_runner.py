"""Tests for LAMMPS runner."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, "src")

from contracts.schemas import ProtocolResult
from orchestrator.lammps_runner import (
    LAMMPSConfig,
    LAMMPSRunner,
    MockLAMMPSRunner,
    calculate_threads_per_job,
)


class TestMockLAMMPSRunner:
    """Test mock LAMMPS runner."""

    def test_successful_run(self):
        """Test successful mock run."""
        runner = MockLAMMPSRunner(success=True)
        protocol = ProtocolResult(
            input_script_path="/mock/in.lammps",
            expected_outputs=["log.lammps", "dump.lammpstrj"],
            estimated_steps=10000,
            protocol_hash="abc123",
            stabilization_chain=["min", "nvt", "npt"],
        )

        result = runner.run(protocol)

        assert result.success is True
        assert result.exit_code == 0
        assert runner.run_count == 1

    def test_failed_run(self):
        """Test failed mock run."""
        runner = MockLAMMPSRunner(success=False)
        protocol = ProtocolResult(
            input_script_path="/mock/in.lammps",
            expected_outputs=["log.lammps"],
            estimated_steps=10000,
            protocol_hash="abc123",
            stabilization_chain=["min", "nvt", "npt"],
        )

        result = runner.run(protocol)

        assert result.success is False
        assert result.error_message == "Mock failure"

    def test_run_count(self):
        """Test run counting."""
        runner = MockLAMMPSRunner()

        for _ in range(3):
            protocol = ProtocolResult(
                input_script_path="/mock/in.lammps",
                expected_outputs=["log.lammps"],
                estimated_steps=10000,
                protocol_hash="abc123",
                stabilization_chain=["min", "nvt", "npt"],
            )
            runner.run(protocol)

        assert runner.run_count == 3


class TestCalculateThreadsPerJob:
    """Test automatic thread calculation."""

    # Patch the os module where it's imported (in lammps_runner)
    PATCH_TARGET = "orchestrator.lammps_runner.os.cpu_count"

    def test_16_cores_4_gpus(self):
        """Test: 16 cores / 4 GPUs = 4 threads per job."""
        with patch(self.PATCH_TARGET, return_value=16):
            assert calculate_threads_per_job(4) == 4

    def test_16_cores_2_gpus(self):
        """Test: 16 cores / 2 GPUs = 8 threads per job."""
        with patch(self.PATCH_TARGET, return_value=16):
            assert calculate_threads_per_job(2) == 8

    def test_16_cores_1_gpu(self):
        """Test: 16 cores / 1 GPU = 16 threads per job."""
        with patch(self.PATCH_TARGET, return_value=16):
            assert calculate_threads_per_job(1) == 16

    def test_8_cores_4_gpus(self):
        """Test: 8 cores / 4 GPUs = 2 threads per job."""
        with patch(self.PATCH_TARGET, return_value=8):
            assert calculate_threads_per_job(4) == 2

    def test_minimum_1_thread(self):
        """Test minimum 1 thread when cores < GPUs."""
        with patch(self.PATCH_TARGET, return_value=2):
            assert calculate_threads_per_job(4) >= 1

    def test_cpu_count_none_fallback(self):
        """Test fallback to 4 when os.cpu_count() returns None."""
        with patch(self.PATCH_TARGET, return_value=None):
            # Fallback is 4 cores, so 4/2 = 2 threads
            assert calculate_threads_per_job(2) == 2

    def test_zero_gpu_treated_as_one(self):
        """Test 0 GPUs treated as 1 to avoid division by zero."""
        with patch(self.PATCH_TARGET, return_value=8):
            assert calculate_threads_per_job(0) == 8


class TestLAMMPSConfig:
    """Test LAMMPS configuration."""

    def test_default_config(self):
        """Test default configuration."""
        config = LAMMPSConfig()

        assert config.executable == "lmp"
        assert config.num_procs == 4
        assert config.num_threads == 4
        assert config.gpu_enabled is False

    def test_custom_config(self):
        """Test custom configuration."""
        config = LAMMPSConfig(
            executable="/opt/lammps/bin/lmp",
            num_procs=8,
            num_threads=8,
            gpu_enabled=True,
            gpu_id=1,
        )

        assert config.executable == "/opt/lammps/bin/lmp"
        assert config.num_procs == 8
        assert config.num_threads == 8
        assert config.gpu_enabled is True
        assert config.gpu_id == 1


class TestLAMMPSRunner:
    """Test LAMMPS runner."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_missing_input_file(self, temp_dir):
        """Test handling of missing input file."""
        runner = LAMMPSRunner(work_dir=temp_dir)
        protocol = ProtocolResult(
            input_script_path=str(temp_dir / "nonexistent.in"),
            expected_outputs=["log.lammps"],
            estimated_steps=10000,
            protocol_hash="abc123",
            stabilization_chain=["min", "nvt", "npt"],
        )

        result = runner.run(protocol)

        assert result.success is False
        assert "not found" in result.error_message.lower()

    def test_build_command_single_proc(self, temp_dir):
        """Test command building for single process."""
        config = LAMMPSConfig(num_procs=1)
        runner = LAMMPSRunner(config=config, work_dir=temp_dir)

        cmd = runner._build_command(Path("in.lammps"))

        assert cmd[0] == "lmp"
        assert "-in" in cmd

    def test_build_command_mpi(self, temp_dir):
        """Test command building for MPI."""
        config = LAMMPSConfig(num_procs=4)
        runner = LAMMPSRunner(config=config, work_dir=temp_dir)

        cmd = runner._build_command(Path("in.lammps"))

        assert "mpirun" in cmd
        assert "-np" in cmd
        assert "4" in cmd

    def test_build_command_gpu(self, temp_dir):
        """Test command building with GPU (KOKKOS backend)."""
        config = LAMMPSConfig(num_procs=1, gpu_enabled=True)
        runner = LAMMPSRunner(config=config, work_dir=temp_dir)

        cmd = runner._build_command(Path("in.lammps"))

        assert "-sf" in cmd
        assert "kk" in cmd
        assert "-k" in cmd

    def test_build_command_gpu_with_threads(self, temp_dir):
        """Test GPU command includes thread count (-t flag)."""
        config = LAMMPSConfig(gpu_enabled=True, gpu_id=0, num_threads=8)
        runner = LAMMPSRunner(config=config, work_dir=temp_dir)

        cmd = runner._build_command(Path("in.lammps"))

        # Check KOKKOS flags are present
        assert "-k" in cmd
        assert "on" in cmd
        assert "g" in cmd
        assert "1" in cmd  # 1 GPU
        assert "t" in cmd  # Thread flag
        assert "8" in cmd  # Thread count
        assert "-sf" in cmd
        assert "kk" in cmd

        # Verify order: -k on g 1 t 8
        k_idx = cmd.index("-k")
        on_idx = cmd.index("on")
        g_idx = cmd.index("g")
        t_idx = cmd.index("t")
        assert k_idx < on_idx < g_idx < t_idx

    def test_build_command_gpu_thread_count_varies(self, temp_dir):
        """Test different thread counts are reflected in command."""
        for threads in [1, 4, 8, 16]:
            config = LAMMPSConfig(gpu_enabled=True, num_threads=threads)
            runner = LAMMPSRunner(config=config, work_dir=temp_dir)
            cmd = runner._build_command(Path("in.lammps"))

            # Find "t" flag and check next element is the thread count
            t_idx = cmd.index("t")
            assert cmd[t_idx + 1] == str(threads)

    # ----- accel_mode branch tests -----

    def test_build_command_accel_kokkos_gpu(self, temp_dir):
        """accel_mode=kokkos_gpu uses KOKKOS GPU flags."""
        config = LAMMPSConfig(accel_mode="kokkos_gpu", num_threads=8)
        runner = LAMMPSRunner(config=config, work_dir=temp_dir)
        cmd = runner._build_command(Path("in.lammps"))

        assert "-k" in cmd
        assert "g" in cmd
        assert "-sf" in cmd and "kk" in cmd
        assert "8" in cmd  # thread count

    def test_build_command_accel_kokkos_cpu(self, temp_dir):
        """accel_mode=kokkos_cpu uses KOKKOS CPU flags without GPU."""
        config = LAMMPSConfig(accel_mode="kokkos_cpu", num_threads=4, mpi_executable="mpirun")
        runner = LAMMPSRunner(config=config, work_dir=temp_dir)
        cmd = runner._build_command(Path("in.lammps"))

        assert "-sf" in cmd and "kk" in cmd
        assert "g" not in cmd  # no GPU flag
        assert "4" in cmd  # thread count

    def test_build_command_accel_kokkos_cpu_no_mpi(self, temp_dir):
        """accel_mode=kokkos_cpu with empty mpi_executable runs directly."""
        config = LAMMPSConfig(accel_mode="kokkos_cpu", num_threads=4, mpi_executable="")
        runner = LAMMPSRunner(config=config, work_dir=temp_dir)
        cmd = runner._build_command(Path("in.lammps"))

        assert cmd[0] == "lmp"  # direct execution, no mpirun
        assert "mpirun" not in cmd

    def test_build_command_accel_mpi_only_multi(self, temp_dir):
        """accel_mode=mpi_only with num_procs>1 uses mpirun."""
        config = LAMMPSConfig(accel_mode="mpi_only", num_procs=4, mpi_executable="mpirun")
        runner = LAMMPSRunner(config=config, work_dir=temp_dir)
        cmd = runner._build_command(Path("in.lammps"))

        assert "mpirun" in cmd
        assert "-np" in cmd
        assert "4" in cmd

    def test_build_command_accel_mpi_only_single(self, temp_dir):
        """accel_mode=mpi_only with num_procs=1 runs directly without mpirun."""
        config = LAMMPSConfig(accel_mode="mpi_only", num_procs=1, mpi_executable="mpirun")
        runner = LAMMPSRunner(config=config, work_dir=temp_dir)
        cmd = runner._build_command(Path("in.lammps"))

        assert cmd[0] == "lmp"
        assert "mpirun" not in cmd

    def test_build_command_accel_serial(self, temp_dir):
        """accel_mode=serial runs directly."""
        config = LAMMPSConfig(accel_mode="serial")
        runner = LAMMPSRunner(config=config, work_dir=temp_dir)
        cmd = runner._build_command(Path("in.lammps"))

        assert cmd == ["lmp", "-in", "in.lammps"]

    def test_build_command_accel_kokkos_gpu_no_mpi(self, temp_dir):
        """accel_mode=kokkos_gpu with empty mpi_executable runs directly."""
        config = LAMMPSConfig(accel_mode="kokkos_gpu", num_threads=4, mpi_executable="")
        runner = LAMMPSRunner(config=config, work_dir=temp_dir)
        cmd = runner._build_command(Path("in.lammps"))

        assert cmd[0] == "lmp"  # direct execution, no mpirun
        assert "mpirun" not in cmd
        assert "-k" in cmd and "-sf" in cmd  # KOKKOS flags present

    def test_build_command_accel_none_legacy_gpu(self, temp_dir):
        """accel_mode=None falls back to legacy gpu_enabled path."""
        config = LAMMPSConfig(gpu_enabled=True, num_threads=4)
        runner = LAMMPSRunner(config=config, work_dir=temp_dir)
        cmd = runner._build_command(Path("in.lammps"))

        assert "-sf" in cmd and "kk" in cmd  # legacy KOKKOS path


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
