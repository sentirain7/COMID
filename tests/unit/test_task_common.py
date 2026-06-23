from orchestrator import task_common


def test_get_experiment_work_dir_default(monkeypatch, tmp_path):
    monkeypatch.setattr(task_common, "get_project_root", lambda: tmp_path)
    work_dir = task_common.get_experiment_work_dir("exp_001")
    assert work_dir == tmp_path / "database" / "exp_001"
    assert work_dir.exists()


def test_get_experiment_work_dir_attempt_isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(task_common, "get_project_root", lambda: tmp_path)
    work_dir = task_common.get_experiment_work_dir(
        "exp_001",
        attempt_tag="3e4f:run prepared/attempt#1",
    )
    assert work_dir.parent == tmp_path / "database" / "exp_001"
    assert work_dir.name.startswith("attempt_")
    assert ":" not in work_dir.name
    assert "/" not in work_dir.name
    assert work_dir.exists()
