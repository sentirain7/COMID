import json
import sys
from types import SimpleNamespace

sys.path.insert(0, "src")

from features.mlops import service as mlops_service
from features.recommendations import pending_service


def test_trigger_retraining_marks_linked_recommendations_fed_back(
    db_session, monkeypatch, tmp_path
):
    created = pending_service.add_candidates_to_pending(
        candidates=[
            {
                "origin": "optimizer",
                "score": 0.9,
                "composition": {
                    "asphaltene": 20.0,
                    "resin": 30.0,
                    "aromatic": 35.0,
                    "saturate": 15.0,
                },
                "predicted_properties": {"density": 1.0},
            }
        ],
        source="quick",
    )[0]

    from database.repositories.recommendation_repo import PendingRecommendationRepository
    from features.common import run_in_session_commit

    def _queue_and_complete(session):
        repo = PendingRecommendationRepository(session)
        repo.transition(created.id, to_status="approved", expected_version=1)
        repo.transition(
            created.id, to_status="queued", expected_version=2, queued_exp_id="exp-fed-1"
        )
        repo.transition(created.id, to_status="running", expected_version=3)
        return repo.transition(created.id, to_status="completed", expected_version=4)

    run_in_session_commit(_queue_and_complete)

    captured = {}
    snapshot_path = tmp_path / "training_snapshot.json"
    snapshot_path.write_text("{}")

    class _FakeRetrainer:
        def run(self, **kwargs):
            captured.update(kwargs)
            snapshot_path.write_text(
                json.dumps(kwargs.get("training_snapshot_extra") or {}, indent=2)
            )
            return SimpleNamespace(
                version_id="mt_1",
                promoted=False,
            )

    monkeypatch.setattr("api.deps.get_model_retrainer", lambda session: _FakeRetrainer())

    changed = mlops_service.trigger_retraining_if_needed(
        triggered_by="active_learning",
        new_samples=50,
        completed_exp_ids=["exp-fed-1"],
    )

    assert changed is True
    assert captured["training_snapshot_extra"]["active_learning_exp_ids"] == ["exp-fed-1"]
    assert captured["training_snapshot_extra"]["linked_recommendation_ids"] == [created.id]

    detail = pending_service.get_detail(created.id)
    assert detail.status == "fed_back"
    assert detail.used_in_retraining is True


def test_trigger_retraining_noop_does_not_mark_fed_back(db_session, monkeypatch):
    created = pending_service.add_candidates_to_pending(
        candidates=[
            {
                "origin": "optimizer",
                "score": 0.9,
                "composition": {
                    "asphaltene": 20.0,
                    "resin": 30.0,
                    "aromatic": 35.0,
                    "saturate": 15.0,
                },
                "predicted_properties": {"density": 1.0},
            }
        ],
        source="quick",
    )[0]

    from database.repositories.recommendation_repo import PendingRecommendationRepository
    from features.common import run_in_session_commit

    def _queue_and_complete(session):
        repo = PendingRecommendationRepository(session)
        repo.transition(created.id, to_status="approved", expected_version=1)
        repo.transition(
            created.id, to_status="queued", expected_version=2, queued_exp_id="exp-fed-2"
        )
        repo.transition(created.id, to_status="running", expected_version=3)
        return repo.transition(created.id, to_status="completed", expected_version=4)

    run_in_session_commit(_queue_and_complete)

    class _FakeRetrainer:
        def run(self, **kwargs):
            return SimpleNamespace(
                version_id=None,
                promoted=False,
            )

    monkeypatch.setattr("api.deps.get_model_retrainer", lambda session: _FakeRetrainer())

    changed = mlops_service.trigger_retraining_if_needed(
        triggered_by="active_learning",
        new_samples=50,
        completed_exp_ids=["exp-fed-2"],
    )

    assert changed is False
    detail = pending_service.get_detail(created.id)
    assert detail.status == "completed"
    assert detail.used_in_retraining is False
