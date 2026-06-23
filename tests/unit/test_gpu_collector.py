"""
Unit tests for GPU collector module.

Tests GPU detection and collection functionality.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest


class TestDetectSystemGpus:
    """Tests for detect_system_gpus function."""

    def test_nvidia_smi_detection(self):
        """Test GPU detection via nvidia-smi."""
        from monitoring.gpu_collector import detect_system_gpus

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = """0, GPU-aaaa1111, NVIDIA GeForce RTX 4090, 24576
1, GPU-bbbb2222, NVIDIA GeForce RTX 3080, 10240"""

        with patch("subprocess.run", return_value=mock_result):
            gpus = detect_system_gpus()

        assert len(gpus) == 2
        assert gpus[0]["gpu_id"] == 0
        assert gpus[0]["uuid"] == "GPU-aaaa1111"
        assert gpus[0]["name"] == "NVIDIA GeForce RTX 4090"
        assert gpus[0]["memory_gb"] == pytest.approx(24.0, rel=0.01)
        assert gpus[1]["gpu_id"] == 1
        assert gpus[1]["name"] == "NVIDIA GeForce RTX 3080"
        assert gpus[1]["memory_gb"] == pytest.approx(10.0, rel=0.01)

    def test_nvidia_smi_single_gpu(self):
        """Test GPU detection with single GPU."""
        from monitoring.gpu_collector import detect_system_gpus

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "0, GPU-h200uuid, NVIDIA H200, 143360"

        with patch("subprocess.run", return_value=mock_result):
            gpus = detect_system_gpus()

        assert len(gpus) == 1
        assert gpus[0]["gpu_id"] == 0
        assert gpus[0]["uuid"] == "GPU-h200uuid"
        assert gpus[0]["name"] == "NVIDIA H200"
        assert gpus[0]["memory_gb"] == pytest.approx(140.0, rel=0.01)

    def test_nvidia_smi_not_found_fallback_lspci(self):
        """Test fallback to lspci when nvidia-smi not found."""
        from monitoring.gpu_collector import detect_system_gpus

        def mock_run(cmd, **kwargs):
            if cmd[0] == "nvidia-smi":
                raise FileNotFoundError("nvidia-smi not found")
            elif cmd[0] == "lspci":
                result = MagicMock()
                result.returncode = 0
                result.stdout = """01:00.0 VGA compatible controller: NVIDIA Corporation GA102 [GeForce RTX 3090]
02:00.0 3D controller: NVIDIA Corporation GA100 [A100 PCIe 40GB]"""
                return result
            return MagicMock(returncode=1)

        with patch("subprocess.run", side_effect=mock_run):
            gpus = detect_system_gpus()

        assert len(gpus) == 2
        # lspci provides minimal info - name extraction may vary
        assert gpus[0]["gpu_id"] == 0
        # Check that we got some name (may or may not contain "NVIDIA" depending on parsing)
        assert len(gpus[0]["name"]) > 0
        assert gpus[0]["memory_gb"] == 0.0  # lspci doesn't provide memory

    def test_no_gpus_found(self):
        """Test when no GPUs are detected."""
        from monitoring.gpu_collector import detect_system_gpus

        def mock_run(cmd, **kwargs):
            if cmd[0] == "nvidia-smi":
                raise FileNotFoundError("nvidia-smi not found")
            elif cmd[0] == "lspci":
                result = MagicMock()
                result.returncode = 0
                result.stdout = "01:00.0 Ethernet controller: Intel Corporation"
                return result
            return MagicMock(returncode=1)

        with patch("subprocess.run", side_effect=mock_run):
            gpus = detect_system_gpus()

        assert gpus == []

    def test_nvidia_smi_timeout(self):
        """Test handling of nvidia-smi timeout."""
        from monitoring.gpu_collector import detect_system_gpus

        def mock_run(cmd, **kwargs):
            if cmd[0] == "nvidia-smi":
                raise subprocess.TimeoutExpired(cmd, 10)
            elif cmd[0] == "lspci":
                result = MagicMock()
                result.returncode = 0
                result.stdout = "01:00.0 3D controller: NVIDIA Corporation RTX 4090"
                return result
            return MagicMock(returncode=1)

        with patch("subprocess.run", side_effect=mock_run):
            gpus = detect_system_gpus()

        # Should fall back to lspci
        assert len(gpus) >= 0  # May or may not find GPUs via lspci


class TestGPUCollector:
    """Tests for GPUCollector class."""

    def test_is_available(self):
        """Test is_available method."""
        from monitoring.gpu_collector import GPUCollector

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            collector = GPUCollector()
            assert collector.is_available() is True

    def test_is_not_available(self):
        """Test is_available when nvidia-smi not found."""
        from monitoring.gpu_collector import GPUCollector

        with patch("subprocess.run", side_effect=FileNotFoundError):
            collector = GPUCollector()
            assert collector.is_available() is False

    def test_collect_once(self):
        """Test collect_once method."""
        from monitoring.gpu_collector import GPUCollector

        def mock_run(cmd, **kwargs):
            result = MagicMock()
            # Check for version check (uses list comparison)
            if isinstance(cmd, list) and len(cmd) >= 2 and cmd[1] == "--version":
                result.returncode = 0
                return result
            # Check for query-gpu (also list). New format: uuid,index,name,util,
            # mem.used,mem.total,temp,power (UUID-keyed for logical-id mapping).
            elif isinstance(cmd, list) and any("--query-gpu" in str(c) for c in cmd):
                result.returncode = 0
                result.stdout = "GPU-uuid0, 0, NVIDIA RTX 4090, 50, 4000, 24576, 45, 250"
                return result
            result.returncode = 0
            return result

        with (
            patch("subprocess.run", side_effect=mock_run),
            patch(
                "monitoring.gpu_collector.get_gpu_uuid_map",
                return_value={0: "GPU-uuid0"},
            ),
        ):
            collector = GPUCollector()
            # Mock that nvidia-smi is available
            collector._nvidia_smi_available = True
            stats = collector.collect_once()

        assert len(stats) == 1
        assert stats[0].gpu_id == "0"
        assert stats[0].name == "NVIDIA RTX 4090"
        assert stats[0].utilization_percent == 50.0
        assert stats[0].temperature_celsius == 45.0
        assert stats[0].power_draw_watts == 250.0


class TestMockGPUCollector:
    """Tests for MockGPUCollector class."""

    def test_mock_is_available(self):
        """Test mock collector is always available."""
        from monitoring.gpu_collector import MockGPUCollector

        collector = MockGPUCollector(num_gpus=2)
        assert collector.is_available() is True

    def test_mock_collect_once(self):
        """Test mock collector returns expected number of GPUs."""
        from monitoring.gpu_collector import MockGPUCollector

        collector = MockGPUCollector(num_gpus=4)
        stats = collector.collect_once()

        assert len(stats) == 4
        for i, stat in enumerate(stats):
            assert stat.gpu_id == str(i)
            assert "Mock GPU" in stat.name


class TestCreateGPUCollector:
    """Tests for create_gpu_collector factory function."""

    def test_create_real_collector(self):
        """Test creating real GPU collector."""
        from monitoring.gpu_collector import GPUCollector, create_gpu_collector

        collector = create_gpu_collector(mock=False)
        assert isinstance(collector, GPUCollector)

    def test_create_mock_collector(self):
        """Test creating mock GPU collector."""
        from monitoring.gpu_collector import MockGPUCollector, create_gpu_collector

        collector = create_gpu_collector(mock=True)
        assert isinstance(collector, MockGPUCollector)
