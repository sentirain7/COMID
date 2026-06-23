"""Unit tests for crystal-structure service supercell metadata handling."""

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

import pytest

from api.schemas import CrystalStructureCreateRequest, CrystalStructureResponse
from builder.supercell_search import CrystalSizeEntry
from contracts.errors import ContractError, ErrorCode

_FAKE_CRYSTAL_REPO = ModuleType("database.repositories.crystal_repo")
_FAKE_FEATURES_COMMON = ModuleType("features.common")
_FAKE_FEATURES_COMMON.__path__ = []  # mark as package for submodule imports
_FAKE_FEATURES_COMMON_DENSITY = ModuleType("features.common.density")
_FAKE_FEATURES_COMMON_WORKSPACE = ModuleType("features.common.workspace")


class _DummyCrystalStructureRepository:
    pass


_FAKE_CRYSTAL_REPO.CrystalStructureRepository = _DummyCrystalStructureRepository
_FAKE_FEATURES_COMMON.run_in_session = lambda fn, *args, **kwargs: fn(None)
_FAKE_FEATURES_COMMON.run_in_session_commit = lambda fn, *args, **kwargs: fn(None)
_FAKE_FEATURES_COMMON_DENSITY.density_from_total_mass = lambda *args, **kwargs: 0.0
_FAKE_FEATURES_COMMON_DENSITY.total_mass_from_types = lambda *args, **kwargs: 0.0
_FAKE_FEATURES_COMMON_WORKSPACE.as_workspace_relative = lambda value: value
_FAKE_FEATURES_COMMON_WORKSPACE.resolve_workspace_path = Path
sys.modules.setdefault("database.repositories.crystal_repo", _FAKE_CRYSTAL_REPO)
sys.modules.setdefault("features.common", _FAKE_FEATURES_COMMON)
sys.modules.setdefault("features.common.density", _FAKE_FEATURES_COMMON_DENSITY)
sys.modules.setdefault("features.common.workspace", _FAKE_FEATURES_COMMON_WORKSPACE)

_SERVICE_PATH = Path(__file__).resolve().parents[2] / "src/features/crystal_structures/service.py"
_SPEC = spec_from_file_location("crystal_service_under_test", _SERVICE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

_build_source_hash = _MODULE._build_source_hash
batch_generate_crystal_sizes = _MODULE.batch_generate_crystal_sizes
_response_to_yaml_item = _MODULE._response_to_yaml_item
_yaml_item_to_response = _MODULE._yaml_item_to_response


def test_source_hash_ignores_legacy_nx_ny_when_matrix_search_enabled():
    base = CrystalStructureCreateRequest(name="Quartz", material="SiO2", nx=2, ny=3)
    variant = CrystalStructureCreateRequest(name="Quartz", material="SiO2", nx=7, ny=9)

    assert _build_source_hash(base) == _build_source_hash(variant)


def test_source_hash_respects_legacy_nx_ny_when_matrix_search_disabled():
    base = CrystalStructureCreateRequest(
        name="Quartz",
        material="SiO2",
        nx=2,
        ny=3,
        use_matrix_search=False,
    )
    variant = CrystalStructureCreateRequest(
        name="Quartz",
        material="SiO2",
        nx=7,
        ny=9,
        use_matrix_search=False,
    )

    assert _build_source_hash(base) != _build_source_hash(variant)


def test_yaml_projection_restores_supercell_metadata_to_top_level():
    response = CrystalStructureResponse(
        crystal_id="crys_001",
        name="Quartz",
        source_type="preset",
        material="SiO2",
        surface="001",
        status="ready",
        atom_count=100,
        nx=8,
        ny=8,
        nz=3,
        thickness_angstrom=16.215,
        xy_size_angstrom=39.304,
        hydroxylated=False,
        hydroxyl_density=4.6,
        transformation_matrix=[[3, 6], [1, 0]],
        n_cells_xy=6,
        error_xy_pct=1.7,
        matrix_search_used=True,
        metadata={"cell_mode": "orthogonalized"},
    )

    yaml_item = _response_to_yaml_item(response)
    restored = _yaml_item_to_response(yaml_item)

    assert restored.transformation_matrix == [[3, 6], [1, 0]]
    assert restored.n_cells_xy == 6
    assert restored.error_xy_pct == 1.7
    assert restored.matrix_search_used is True


@pytest.mark.asyncio
async def test_batch_generate_counts_existing_as_skipped(monkeypatch):
    entries = [
        CrystalSizeEntry(
            lx=39.304,
            ly=38.293,
            avg_xy=38.7985,
            anisotropy_pct=2.6,
            det=6,
            matrix=((3, 6), (1, 0)),
        ),
        CrystalSizeEntry(
            lx=44.217,
            ly=42.548,
            avg_xy=43.3825,
            anisotropy_pct=3.8,
            det=8,
            matrix=((5, 4), (2, 0)),
        ),
    ]

    monkeypatch.setattr("builder.supercell_search.enumerate_available_sizes", lambda **_: entries)
    monkeypatch.setattr(_MODULE, "_upsert_yaml_crystal_entry", lambda entry: None)
    monkeypatch.setattr(_MODULE, "_response_to_yaml_item", lambda resp: {})

    existing = CrystalStructureResponse(
        crystal_id="crys_existing",
        name="Quartz-existing",
        source_type="preset",
        material="SiO2",
        surface="001",
        status="ready",
        atom_count=100,
        nx=8,
        ny=8,
        nz=3,
        thickness_angstrom=25.0,
        xy_size_angstrom=39.304,
        hydroxylated=True,
        hydroxyl_density=4.6,
    )

    def _existing_lookup(request):
        if abs(request.xy_size_angstrom - entries[0].avg_xy) < 1e-6:
            return existing
        return None

    async def _create(request):
        return CrystalStructureResponse(
            crystal_id="crys_new",
            name=request.name,
            source_type="preset",
            material=request.material.value,
            surface=request.surface.value,
            status="ready",
            atom_count=120,
            nx=9,
            ny=9,
            nz=3,
            thickness_angstrom=request.thickness_angstrom,
            xy_size_angstrom=request.xy_size_angstrom,
            hydroxylated=request.hydroxylated,
            hydroxyl_density=request.hydroxyl_density,
        )

    monkeypatch.setattr(_MODULE, "_get_existing_crystal_structure", _existing_lookup)
    monkeypatch.setattr(_MODULE, "create_crystal_structure", _create)

    result = await batch_generate_crystal_sizes(
        _MODULE.CrystalBatchGenerateRequest(material="SiO2")
    )

    assert result.generated_count == 1
    assert result.skipped_count == 1
    assert [item.crystal_id for item in result.sizes] == ["crys_existing", "crys_new"]


@pytest.mark.asyncio
async def test_batch_generate_propagates_creation_errors(monkeypatch):
    entries = [
        CrystalSizeEntry(
            lx=44.217,
            ly=42.548,
            avg_xy=43.3825,
            anisotropy_pct=3.8,
            det=8,
            matrix=((5, 4), (2, 0)),
        ),
    ]

    monkeypatch.setattr("builder.supercell_search.enumerate_available_sizes", lambda **_: entries)
    monkeypatch.setattr(_MODULE, "_get_existing_crystal_structure", lambda request: None)

    async def _create(_request):
        raise ContractError(ErrorCode.SERVICE_UNAVAILABLE, "boom")

    monkeypatch.setattr(_MODULE, "create_crystal_structure", _create)

    with pytest.raises(ContractError, match="boom"):
        await batch_generate_crystal_sizes(_MODULE.CrystalBatchGenerateRequest(material="SiO2"))
