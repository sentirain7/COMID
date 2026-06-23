"""Unit tests for the E_intra sidecar store (write-through + import/export).

The autouse ``_isolate_e_intra_sidecar`` fixture (tests/unit/conftest.py)
redirects ``ASPHALT_E_INTRA_SIDECAR_DIR`` to a per-test tmp dir, so these
exercise real file I/O without touching the git-tracked sidecar directory.
"""

from __future__ import annotations

from contracts.policies.e_intra_export import EIntraExportPolicy
from contracts.policies.forcefield import get_ff_display_label, get_ff_version
from database.repositories.e_intra_repo import EIntraRepository
from features.common import e_intra_sidecar
from features.common.e_intra_sidecar import (
    export_db_to_sidecars,
    import_sidecars_to_db,
    iter_sidecar_files,
    read_sidecar,
    upsert_entry,
)

FF_TYPE = "bulk_ff_gaff2"
FF_NAME = get_ff_display_label(FF_TYPE)
FF_VERSION = get_ff_version(FF_TYPE)
METHOD = "single_molecule_vacuum"
MOL = "U-AS-Thio"


def _upsert(mol: str, temp: float, value: float) -> None:
    upsert_entry(
        mol_id=mol,
        ff_name=FF_NAME,
        ff_version=FF_VERSION,
        method=METHOD,
        temperature_K=temp,
        e_intra=value,
        n_samples=200,
        averaging_window_ps=200.0,
    )


def test_upsert_creates_sidecar_with_entry():
    path = upsert_entry(
        mol_id=MOL,
        ff_name=FF_NAME,
        ff_version=FF_VERSION,
        method=METHOD,
        temperature_K=293.0,
        e_intra=-123.45,
    )
    assert path is not None and path.exists()
    doc = read_sidecar(MOL)
    assert doc["mol_id"] == MOL
    assert len(doc["entries"]) == 1
    e = doc["entries"][0]
    assert e["temperature_K"] == 293.0
    assert e["e_intra"] == -123.45
    assert e["method"] == METHOD
    # No machine-specific fields leak into the shareable file.
    assert "source_exp_id" not in e
    assert "computed_at" not in e


def test_upsert_is_idempotent_and_replaces_same_temperature():
    _upsert(MOL, 293.0, -100.0)
    _upsert(MOL, 293.0, -111.0)  # same (ff, method, temp) → replace, not append
    doc = read_sidecar(MOL)
    assert len(doc["entries"]) == 1
    assert doc["entries"][0]["e_intra"] == -111.0


def test_partial_coverage_preserved_per_temperature():
    for t in (213.0, 233.0, 253.0):
        _upsert(MOL, t, -100.0 - t)
    doc = read_sidecar(MOL)
    temps = sorted(e["temperature_K"] for e in doc["entries"])
    assert temps == [213.0, 233.0, 253.0]  # only computed temps, not all 12


def test_entries_sorted_deterministically():
    for t in (333.0, 213.0, 293.0):
        _upsert(MOL, t, -50.0)
    doc = read_sidecar(MOL)
    temps = [e["temperature_K"] for e in doc["entries"]]
    assert temps == sorted(temps)


def test_policy_disabled_writes_nothing(monkeypatch):
    monkeypatch.setattr(
        e_intra_sidecar, "DEFAULT_E_INTRA_EXPORT_POLICY", EIntraExportPolicy(enabled=False)
    )
    path = upsert_entry(
        mol_id=MOL,
        ff_name=FF_NAME,
        ff_version=FF_VERSION,
        method=METHOD,
        temperature_K=293.0,
        e_intra=-1.0,
    )
    assert path is None
    assert read_sidecar(MOL) is None


def test_import_roundtrip_populates_db_coverage(isolated_db_session):
    for t in (213.0, 233.0, 253.0):
        _upsert(MOL, t, -200.0 - t)

    result = import_sidecars_to_db(isolated_db_session)
    isolated_db_session.commit()
    assert result["files"] == 1
    assert result["entries"] == 3
    assert result["upserted"] == 3

    repo = EIntraRepository(isolated_db_session)
    cov = repo.get_coverage(MOL, required_temperatures=[213.0, 233.0, 253.0])
    assert cov["computed_count"] == 3
    assert cov["latest_values_by_temperature"][213.0] == -413.0


def test_import_is_idempotent(isolated_db_session):
    _upsert(MOL, 293.0, -300.0)
    import_sidecars_to_db(isolated_db_session)
    isolated_db_session.commit()
    import_sidecars_to_db(isolated_db_session)  # second import → no duplicate
    isolated_db_session.commit()
    from database.models import EIntraModel

    rows = isolated_db_session.query(EIntraModel).filter(EIntraModel.mol_id == MOL).all()
    assert len(rows) == 1


def test_export_rebuilds_sidecars_from_db(isolated_db_session):
    from contracts.schemas import EIntraKey, EIntraValue

    repo = EIntraRepository(isolated_db_session)
    for t in (273.0, 293.0):
        repo.set(
            EIntraKey(
                mol_id=MOL, ff_name=FF_NAME, ff_version=FF_VERSION, temperature_K=t, method=METHOD
            ),
            EIntraValue(e_intra=-500.0 - t, temperature_K=t),
        )
    isolated_db_session.commit()

    result = export_db_to_sidecars(isolated_db_session)
    assert result["rows"] == 2
    assert result["sidecars"] == 1

    doc = read_sidecar(MOL)
    assert {e["temperature_K"] for e in doc["entries"]} == {273.0, 293.0}
    assert len(list(iter_sidecar_files())) == 1
