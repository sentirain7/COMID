"""Tests for inverse design API endpoints (Phase 6).

Inverse design is property-target driven: the caller specifies the property
targets (``custom_targets``) to design for; there is no PG-grade/pavement-temp
entry path.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

TestClient = pytest.importorskip(
    "fastapi.testclient",
    reason="FastAPI not installed",
).TestClient


# A representative bulk target set reused across success cases.
_BULK_TARGETS = [
    {
        "metric_name": "density",
        "target_min": 0.9,
        "target_max": 1.1,
        "direction": "target",
    },
    {
        "metric_name": "viscosity",
        "target_max": 3000.0,
        "direction": "minimize",
    },
]


@pytest.fixture()
def client():
    """Create a test client for the API."""
    from api.application import app

    return TestClient(app, raise_server_exceptions=False)


class TestRunEndpoint:
    """Tests for POST /api/recommendations/inverse/run."""

    def test_missing_target_spec(self, client: TestClient) -> None:
        """Should return 422 if no custom_targets are provided (required field)."""
        resp = client.post("/recommendations/inverse/run", json={})
        assert resp.status_code == 422

    def test_empty_target_spec(self, client: TestClient) -> None:
        """Should return 422 for an empty custom_targets list (min_length=1)."""
        resp = client.post(
            "/recommendations/inverse/run",
            json={"custom_targets": []},
        )
        assert resp.status_code == 422

    def test_no_model_returns_503(self, client: TestClient) -> None:
        """Should return 503 when ML model is not loaded."""
        with patch("api.deps.get_ml_predictor_fn", return_value=None):
            resp = client.post(
                "/recommendations/inverse/run",
                json={"custom_targets": _BULK_TARGETS},
            )
            assert resp.status_code == 503
            assert "ML model not loaded" in resp.json()["detail"]

    def test_custom_targets(self, client: TestClient) -> None:
        """Should accept custom property targets and report the 'custom' target set."""

        def _mock_predict(comp: dict) -> dict:
            return {"density": 1.0, "viscosity": 1500.0}

        with patch("api.deps.get_ml_predictor_fn", return_value=_mock_predict):
            resp = client.post(
                "/recommendations/inverse/run",
                json={
                    "custom_targets": _BULK_TARGETS,
                    "max_iterations": 3,
                    "n_results": 2,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["target_set_name"] == "custom"
            assert data["n_iterations"] > 0
            assert len(data["results"]) <= 2
            assert "hypervolume_history" in data

    def test_response_exposes_pareto_and_audit(self, client: TestClient) -> None:
        """Response includes a Pareto front and a decision-trace audit log."""

        def _mock_predict(comp: dict) -> dict:
            return {"density": 1.0, "viscosity": 1500.0}

        with patch("api.deps.get_ml_predictor_fn", return_value=_mock_predict):
            resp = client.post(
                "/recommendations/inverse/run",
                json={
                    "custom_targets": _BULK_TARGETS,
                    "max_iterations": 3,
                    "n_results": 2,
                },
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()

            # Pareto front exposed
            assert data["pareto_front"] is not None
            for pt in data["pareto_front"]:
                assert "composition" in pt
                assert "predicted_properties" in pt
                assert "crowding_distance" in pt

            # Audit log exposed
            audit = data["audit_log"]
            assert audit is not None
            assert audit["acquisition_function"] in ("expected_improvement", "expected_hypervolume_improvement")
            assert "auto:" in audit["acquisition_rationale"]
            assert "ranking" in audit and "formula" in audit["ranking"]
            assert isinstance(audit["iterations"], list)

    def test_invalid_custom_target_metric(self, client: TestClient) -> None:
        """Should return 400 for invalid metric in custom targets."""

        def _mock_predict(comp: dict) -> dict:
            return {}

        with patch("api.deps.get_ml_predictor_fn", return_value=_mock_predict):
            resp = client.post(
                "/recommendations/inverse/run",
                json={
                    "custom_targets": [
                        {
                            "metric_name": "nonexistent_metric",
                            "direction": "maximize",
                        },
                    ],
                    "max_iterations": 3,
                },
            )
            assert resp.status_code == 400
            assert "Invalid targets" in resp.json()["detail"]

    def test_additive_type_passed(self, client: TestClient) -> None:
        """additive_type from request should be forwarded to predictor."""
        received: list[dict] = []

        def _spy_predict(comp: dict) -> dict:
            received.append(dict(comp))
            return {"density": 1.0, "viscosity": 1500.0}

        with patch("api.deps.get_ml_predictor_fn", return_value=_spy_predict):
            resp = client.post(
                "/recommendations/inverse/run",
                json={
                    "custom_targets": _BULK_TARGETS,
                    "additive_type": "SiO2",
                    "max_iterations": 2,
                    "n_results": 1,
                },
            )
            assert resp.status_code == 200
            # At least some calls should have additive_type
            assert any(c.get("additive_type") == "SiO2" for c in received)

    def test_result_item_structure(self, client: TestClient) -> None:
        """Each result item should have the expected fields."""

        def _mock_predict(comp: dict) -> dict:
            return {"density": 1.0, "viscosity": 1500.0}

        with patch("api.deps.get_ml_predictor_fn", return_value=_mock_predict):
            resp = client.post(
                "/recommendations/inverse/run",
                json={
                    "custom_targets": _BULK_TARGETS,
                    "max_iterations": 3,
                    "n_results": 2,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            for item in data["results"]:
                assert "composition" in item
                assert "predicted_properties" in item
                assert "targets_satisfied" in item
                assert "target_distances" in item
                assert "is_ood" in item
                assert "rationale" in item
                assert "extrapolation_status" in item
                assert "high_uncertainty" in item

    def test_temperature_optimization_forwarded_to_predictor(self, client: TestClient) -> None:
        """Temperature optimization should inject temperature_k into predictor calls."""
        received: list[dict] = []

        def _mock_predict(comp: dict) -> dict:
            received.append(dict(comp))
            return {
                "density": 1.0,
                "viscosity": 1500.0,
            }

        with (
            patch("api.deps.get_ml_predictor_with_uncertainty_fn", return_value=_mock_predict),
            patch(
                "api.deps.get_runtime_capability_manifest",
                return_value={
                    "supported_targets": ["density", "viscosity"],
                    "per_target_feature_set": {"density": "v5", "viscosity": "v5"},
                    "supported_temperature_range_k": [273.0, 333.0],
                },
            ),
            patch("api.deps.get_runtime_ood_detector", return_value=None),
        ):
            resp = client.post(
                "/recommendations/inverse/run",
                json={
                    "custom_targets": [
                        {"metric_name": "density", "direction": "maximize"},
                    ],
                    "optimize_temperature": True,
                    "temperature_range_k": {"min_k": 273.0, "max_k": 333.0},
                    "max_iterations": 2,
                    "n_results": 1,
                },
            )
            assert resp.status_code == 200
            assert any("temperature_k" in comp for comp in received)

    def test_aggregate_aware_without_layered_model_returns_503(self, client: TestClient) -> None:
        """Aggregate-aware requests must fail fast when layered predictor is unavailable."""
        with patch("api.deps.get_layered_predictor_fn", return_value=None):
            resp = client.post(
                "/recommendations/inverse/run",
                json={
                    "custom_targets": [
                        {
                            "metric_name": "adhesion_energy",
                            "direction": "maximize",
                        }
                    ],
                    "aggregate_specs": [{"material": "SiO2", "surface": "001"}],
                    "n_results": 1,
                    "max_iterations": 2,
                },
            )
            assert resp.status_code == 503
            assert "Layered-capable ML model not loaded" in resp.json()["detail"]


class TestFeasibilityScout:
    """Feasibility pre-screening gate (opt-in via policy)."""

    def test_scout_off_by_default_does_not_block(self, client: TestClient) -> None:
        """With the scout disabled (default), infeasible-looking targets still run."""

        def _never_satisfies(comp: dict) -> dict:
            return {"density": 9.0}  # far outside the [0.9, 1.1] band

        with patch("api.deps.get_ml_predictor_fn", return_value=_never_satisfies):
            resp = client.post(
                "/recommendations/inverse/run",
                json={
                    "custom_targets": [
                        {"metric_name": "density", "target_min": 0.9, "target_max": 1.1,
                         "direction": "target"},
                    ],
                    "max_iterations": 2,
                    "n_results": 1,
                },
            )
            assert resp.status_code == 200, resp.text
            # No feasibility report attached when the scout is off.
            assert resp.json()["feasibility"] is None

    def test_scout_enabled_blocks_infeasible(self, client: TestClient, monkeypatch) -> None:
        """When enabled, infeasible targets are rejected with a 400 + feasibility detail."""
        from contracts.policies.recommendation_policy import DEFAULT_RECOMMENDATION_POLICY

        monkeypatch.setattr(
            DEFAULT_RECOMMENDATION_POLICY.inverse_design,
            "feasibility_scout_enabled",
            True,
        )
        monkeypatch.setattr(
            DEFAULT_RECOMMENDATION_POLICY.inverse_design, "feasibility_n_samples", 40
        )

        def _never_satisfies(comp: dict) -> dict:
            return {"density": 9.0}

        with patch("api.deps.get_ml_predictor_fn", return_value=_never_satisfies):
            resp = client.post(
                "/recommendations/inverse/run",
                json={
                    "custom_targets": [
                        {"metric_name": "density", "target_min": 0.9, "target_max": 1.1,
                         "direction": "target"},
                    ],
                    "max_iterations": 2,
                    "n_results": 1,
                },
            )
            assert resp.status_code == 400, resp.text
            assert "infeasible" in resp.json()["detail"].lower()

    def test_scout_enabled_allows_with_override(self, client: TestClient, monkeypatch) -> None:
        """allow_infeasible_exploration bypasses the block and attaches the report."""
        from contracts.policies.recommendation_policy import DEFAULT_RECOMMENDATION_POLICY

        monkeypatch.setattr(
            DEFAULT_RECOMMENDATION_POLICY.inverse_design,
            "feasibility_scout_enabled",
            True,
        )
        monkeypatch.setattr(
            DEFAULT_RECOMMENDATION_POLICY.inverse_design, "feasibility_n_samples", 40
        )

        def _never_satisfies(comp: dict) -> dict:
            return {"density": 9.0}

        with patch("api.deps.get_ml_predictor_fn", return_value=_never_satisfies):
            resp = client.post(
                "/recommendations/inverse/run",
                json={
                    "custom_targets": [
                        {"metric_name": "density", "target_min": 0.9, "target_max": 1.1,
                         "direction": "target"},
                    ],
                    "allow_infeasible_exploration": True,
                    "max_iterations": 2,
                    "n_results": 1,
                },
            )
            assert resp.status_code == 200, resp.text
            feasibility = resp.json()["feasibility"]
            assert feasibility is not None
            assert feasibility["status"] == "infeasible"
