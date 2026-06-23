"""Tests for GPU detection/statistics (monitoring module)."""

from monitoring.gpu_collector import MockGPUCollector, create_gpu_collector


class TestGPUCollector:
    """Tests for GPU metrics collector."""

    def test_mock_collector(self):
        """Test mock GPU collector."""

        collector = MockGPUCollector(num_gpus=2)

        assert collector.is_available()

        stats = collector.collect_once()
        assert len(stats) == 2

        # Verify stats structure
        for gpu in stats:
            assert 0 <= gpu.utilization_percent <= 100
            assert gpu.memory_used_bytes > 0
            assert gpu.memory_total_bytes > 0

    def test_collector_factory(self):
        """Test GPU collector factory."""

        # Mock mode
        collector = create_gpu_collector(mock=True)
        assert collector.is_available()
