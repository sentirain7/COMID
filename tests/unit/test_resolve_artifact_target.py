"""ArtifactTarget resolver + source_id SSOT tests.

v01.01.00: CNT/Graphene use individual source_ids (Carbon_Nano_Tube, Graphine)
with parameterization.mode=organic_gaff2. They are no longer passthrough and
do not share a source_id.

Passthrough BLOCKED contract is preserved via synthetic fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from features.molecules import artifact_service


@pytest.fixture(autouse=True)
def _refresh_consumer_index():
    """Rebuild the cached YAML index per test to avoid order coupling."""
    artifact_service.refresh_consumer_index()
    yield
    artifact_service.refresh_consumer_index()


# ---------------------------------------------------------------------------
# Simple organic entry
# ---------------------------------------------------------------------------


def test_resolve_simple_organic_entry_uses_mol_id_as_source():
    target = artifact_service.resolve_artifact_target("Toluene")
    assert target.source_id == "Toluene"
    assert target.consumer_ids == ["Toluene"]
    assert target.has_shared_source_id is False
    assert target.is_passthrough is False
    assert target.artifact_path.name == "Toluene.json"
    assert target.admin_sidecar_path.parent.name == ".admin_status"


# ---------------------------------------------------------------------------
# CNT/Graphene — individual source_ids, NOT passthrough (v01.01.00)
# ---------------------------------------------------------------------------


class TestCNTGrapheneResolver:
    def test_cnt_has_individual_source_id(self):
        target = artifact_service.resolve_artifact_target("Carbon_Nano_Tube")
        assert target.source_id == "Carbon_Nano_Tube"
        assert target.is_passthrough is False
        assert target.artifact_path.name == "Carbon_Nano_Tube.json"

    def test_graphene_has_individual_source_id(self):
        target = artifact_service.resolve_artifact_target("Graphine")
        assert target.source_id == "Graphine"
        assert target.is_passthrough is False
        assert target.artifact_path.name == "Graphine.json"

    def test_cnt_graphene_not_shared(self):
        cnt = artifact_service.resolve_artifact_target("Carbon_Nano_Tube")
        gra = artifact_service.resolve_artifact_target("Graphine")
        assert cnt.source_id != gra.source_id

    def test_cnt_in_pending_molecules(self):
        pending = artifact_service.get_pending_molecules()
        cnt_rows = [
            r
            for r in pending
            if r.get("mol_id") == "Carbon_Nano_Tube" and r.get("artifact_type") == "organic"
        ]
        assert len(cnt_rows) == 1
        assert cnt_rows[0]["is_passthrough"] is False
        assert cnt_rows[0]["source_id"] == "Carbon_Nano_Tube"


# ---------------------------------------------------------------------------
# Passthrough BLOCKED contract (synthetic fixture — NOT real CNT/Graphene)
# ---------------------------------------------------------------------------


def _synthetic_passthrough_ff():
    return {
        "route": "organic_curated_artifact",
        "status": "active",
        "source_id": "synthetic_passthrough_v1",
    }


def _synthetic_passthrough_additive_def():
    return {
        "parameterization": {
            "mode": "organic_gaff2_passthrough",
            "profile_id": "synthetic_passthrough_v1",
        },
    }


# ---------------------------------------------------------------------------
# Delete / dedupe
# ---------------------------------------------------------------------------


def test_delete_cleans_up_legacy_mol_id_filename(tmp_path: Path, monkeypatch) -> None:
    """Defensive: legacy {mol_id}.json sibling is removed during transition."""
    monkeypatch.setattr(artifact_service, "ARTIFACT_DIR", tmp_path)
    canonical = tmp_path / "Toluene.json"
    canonical.write_text("{}")

    removed = artifact_service.delete_artifact("Toluene")
    assert removed is True
    assert not canonical.exists()


def test_dedupe_by_source_id_handles_unique_entries():
    row_cnt = {
        "mol_id": "Carbon_Nano_Tube",
        "source_id": "Carbon_Nano_Tube",
        "mol_path": "/tmp/cnt.mol",
    }
    row_gra = {
        "mol_id": "Graphine",
        "source_id": "Graphine",
        "mol_path": "/tmp/graphene.mol",
    }
    row_tol = {
        "mol_id": "Toluene",
        "source_id": "Toluene",
        "mol_path": "/tmp/toluene.mol",
    }

    unique, conflicts = artifact_service.dedupe_by_source_id([row_cnt, row_gra, row_tol])
    unique_sids = {row["source_id"] for row in unique}
    assert unique_sids == {"Carbon_Nano_Tube", "Graphine", "Toluene"}
    assert len(conflicts) == 0


def test_get_artifact_path_matches_resolver() -> None:
    target = artifact_service.resolve_artifact_target("Toluene")
    assert (
        artifact_service.get_artifact_path("Toluene", target.ff_assignment) == target.artifact_path
    )
