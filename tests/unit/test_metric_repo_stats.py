"""Unit tests for MetricRepository.get_statistics() with stddev and filters."""

from unittest.mock import MagicMock

import pytest

from database.repositories.metric_repo import MetricRepository


@pytest.fixture
def mock_session():
    """Create a mock SQLAlchemy session."""
    session = MagicMock()
    return session


@pytest.fixture
def metric_repo(mock_session):
    """Create a MetricRepository with mock session."""
    return MetricRepository(mock_session)


class TestGetStatistics:
    """Tests for get_statistics() method."""

    def test_basic_statistics_returned(self, metric_repo, mock_session):
        """Returns count, avg, min, max, stddev."""
        # Mock the main query
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = (10, 1.00, 0.95, 1.05)

        # Mock the stddev query (avg of x^2)
        mock_query.scalar.return_value = 1.0004  # avg(x^2) = 1.0004 → var = 0.0004 → std = 0.02

        result = metric_repo.get_statistics("density")

        assert "count" in result
        assert "avg" in result
        assert "min" in result
        assert "max" in result
        assert "stddev" in result
        assert result["count"] == 10

    def test_stddev_zero_when_count_is_one(self, metric_repo, mock_session):
        """Stddev is 0 when only one data point."""
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = (1, 1.00, 1.00, 1.00)

        result = metric_repo.get_statistics("density")

        assert result["stddev"] == 0.0

    def test_stddev_zero_when_count_is_zero(self, metric_repo, mock_session):
        """Stddev is 0 when no data."""
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = (0, None, None, None)

        result = metric_repo.get_statistics("density")

        assert result["count"] == 0
        assert result["stddev"] == 0.0

    def test_backward_compatible_no_extra_args(self, metric_repo, mock_session):
        """Calling without run_tier/temperature_k works (backward compatible)."""
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = (5, 1.00, 0.95, 1.05)
        mock_query.scalar.return_value = 1.0004

        # Should not raise
        result = metric_repo.get_statistics("density", namespace="bulk_ff_gaff2")

        assert result["count"] == 5

    def test_run_tier_filter_triggers_join(self, metric_repo, mock_session):
        """Passing run_tier triggers a JOIN with ExperimentModel."""
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.first.return_value = (5, 1.00, 0.95, 1.05)
        mock_query.scalar.return_value = 1.0004

        result = metric_repo.get_statistics("density", run_tier="screening", temperature_k=298.0)

        # Verify join was called
        assert mock_query.join.called
        assert result["count"] == 5
