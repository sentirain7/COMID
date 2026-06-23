"""Unit tests for interface molecule batch generation service (mock-based)."""

from unittest.mock import AsyncMock, patch

import pytest

from api.schemas.interface_molecules import (
    InterfaceMoleculeBatchGenerateRequest,
    InterfaceMoleculeCellResponse,
)


class TestEnumerateInterfaceBatchSizes:
    """Tests for the _enumerate_interface_batch_sizes policy function."""

    def test_enumerate_default_range(self):
        """Test enumeration with default 35-60 range."""
        from features.interface_molecules.service import _enumerate_interface_batch_sizes

        sizes = _enumerate_interface_batch_sizes(35.0, 60.0)
        # With step=10: 35, 45, 55 (65 would exceed)
        assert 35.0 in sizes
        assert 45.0 in sizes
        assert 55.0 in sizes
        # 65 should NOT be included as it's beyond 60 + 10*0.5
        assert all(s <= 65.0 for s in sizes)

    def test_enumerate_single_size(self):
        """Test enumeration with xy_min == xy_max."""
        from features.interface_molecules.service import _enumerate_interface_batch_sizes

        sizes = _enumerate_interface_batch_sizes(50.0, 50.0)
        assert 50.0 in sizes
        assert len(sizes) == 1

    def test_enumerate_custom_range(self):
        """Test enumeration with custom range."""
        from features.interface_molecules.service import _enumerate_interface_batch_sizes

        sizes = _enumerate_interface_batch_sizes(40.0, 80.0)
        # With step=10: 40, 50, 60, 70, 80
        assert 40.0 in sizes
        assert 50.0 in sizes
        assert 60.0 in sizes
        assert 70.0 in sizes
        assert 80.0 in sizes

    def test_enumerate_returns_sorted_list(self):
        """Test that returned sizes are sorted."""
        from features.interface_molecules.service import _enumerate_interface_batch_sizes

        sizes = _enumerate_interface_batch_sizes(35.0, 80.0)
        assert sizes == sorted(sizes)


class TestBuildCellSourceHash:
    """Tests for the _build_cell_source_hash helper function."""

    def test_same_params_produce_same_hash(self):
        """Test that identical parameters produce the same hash."""
        from features.interface_molecules.service import _build_cell_source_hash

        hash1 = _build_cell_source_hash("NaCl", 40.0, 40.0, 10.0, 2.16, "ppf")
        hash2 = _build_cell_source_hash("NaCl", 40.0, 40.0, 10.0, 2.16, "ppf")
        assert hash1 == hash2

    def test_different_params_produce_different_hash(self):
        """Test that different parameters produce different hashes."""
        from features.interface_molecules.service import _build_cell_source_hash

        hash1 = _build_cell_source_hash("NaCl", 40.0, 40.0, 10.0, 2.16, "ppf")
        hash2 = _build_cell_source_hash("H2O", 40.0, 40.0, 10.0, 2.16, "ppf")
        hash3 = _build_cell_source_hash("NaCl", 50.0, 50.0, 10.0, 2.16, "ppf")
        hash4 = _build_cell_source_hash("NaCl", 40.0, 40.0, 10.0, 1.0, "ppf")

        assert hash1 != hash2  # different mol_id
        assert hash1 != hash3  # different size
        assert hash1 != hash4  # different density


class TestBatchGenerateInterfaceMoleculeCells:
    """Tests for batch_generate_interface_molecule_cells orchestration."""

    @pytest.fixture
    def mock_molecule_info(self):
        """Mock molecule info."""
        return {
            "NaCl": {
                "category": "deicing",
                "name": "Sodium Chloride",
                "formula": "NaCl",
                "atom_count": 2,
                "molecular_weight": 58.44,
                "elements": ["Na", "Cl"],
            },
        }

    @pytest.mark.asyncio
    async def test_batch_generate_creates_new_cells(self, mock_molecule_info):
        """Test that batch generation creates new cells when none exist."""
        with (
            patch(
                "features.interface_molecules.service.get_interface_molecule_info",
                return_value=mock_molecule_info,
            ),
            patch(
                "features.interface_molecules.service._get_existing_interface_cell",
                return_value=None,
            ),
            patch(
                "features.interface_molecules.service.create_interface_molecule_cell",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            # Setup mock to return a cell response
            mock_create.return_value = InterfaceMoleculeCellResponse(
                cell_id="ifc_test001",
                name="NaCl_d2.16_35x35x10",
                status="ready",
                mol_id="NaCl",
                atom_count=100,
                molecule_count=50,
                target_density=2.16,
                boundary_mode="ppf",
                lx_angstrom=35.0,
                ly_angstrom=35.0,
                lz_angstrom=10.0,
            )

            from features.interface_molecules.service import (
                batch_generate_interface_molecule_cells,
            )

            request = InterfaceMoleculeBatchGenerateRequest(
                mol_id="NaCl",
                xy_min=35.0,
                xy_max=35.0,  # Single size
                lz_angstrom=10.0,
                target_density=2.16,
            )

            result = await batch_generate_interface_molecule_cells(request)

            assert result.mol_id == "NaCl"
            assert result.mol_name == "Sodium Chloride"
            assert result.generated_count == 1
            assert result.skipped_count == 0
            assert len(result.cells) == 1
            mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_batch_generate_skips_existing_cells(self, mock_molecule_info):
        """Test that batch generation skips cells that already exist."""
        existing_cell = {
            "cell_id": "ifc_existing",
            "name": "existing_cell",
            "status": "ready",
            "mol_id": "NaCl",
            "atom_count": 100,
            "molecule_count": 50,
            "target_density": 2.16,
            "boundary_mode": "ppf",
            "lx_angstrom": 35.0,
            "ly_angstrom": 35.0,
            "lz_angstrom": 10.0,
        }

        with (
            patch(
                "features.interface_molecules.service.get_interface_molecule_info",
                return_value=mock_molecule_info,
            ),
            patch(
                "features.interface_molecules.service._get_existing_interface_cell",
                return_value=existing_cell,
            ),
            patch(
                "features.interface_molecules.service.create_interface_molecule_cell",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            from features.interface_molecules.service import (
                batch_generate_interface_molecule_cells,
            )

            request = InterfaceMoleculeBatchGenerateRequest(
                mol_id="NaCl",
                xy_min=35.0,
                xy_max=35.0,
                lz_angstrom=10.0,
                target_density=2.16,
            )

            result = await batch_generate_interface_molecule_cells(request)

            assert result.generated_count == 0
            assert result.skipped_count == 1
            mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_batch_generate_handles_multiple_sizes(self, mock_molecule_info):
        """Test that batch generation handles multiple sizes."""
        call_count = 0

        async def mock_create_cell(req):
            nonlocal call_count
            call_count += 1
            return InterfaceMoleculeCellResponse(
                cell_id=f"ifc_test{call_count:03d}",
                name=req.name,
                status="ready",
                mol_id=req.mol_id,
                atom_count=100,
                molecule_count=50,
                target_density=req.target_density,
                boundary_mode=req.boundary_mode.value,
                lx_angstrom=req.lx_angstrom,
                ly_angstrom=req.ly_angstrom,
                lz_angstrom=req.lz_angstrom,
            )

        with (
            patch(
                "features.interface_molecules.service.get_interface_molecule_info",
                return_value=mock_molecule_info,
            ),
            patch(
                "features.interface_molecules.service._get_existing_interface_cell",
                return_value=None,
            ),
            patch(
                "features.interface_molecules.service.create_interface_molecule_cell",
                side_effect=mock_create_cell,
            ),
        ):
            from features.interface_molecules.service import (
                batch_generate_interface_molecule_cells,
            )

            request = InterfaceMoleculeBatchGenerateRequest(
                mol_id="NaCl",
                xy_min=35.0,
                xy_max=55.0,  # Should generate 35, 45, 55 (step=10)
                lz_angstrom=10.0,
                target_density=2.16,
            )

            result = await batch_generate_interface_molecule_cells(request)

            assert result.generated_count == 3
            assert result.skipped_count == 0
            assert len(result.cells) == 3

    @pytest.mark.asyncio
    async def test_batch_generate_raises_for_unknown_molecule(self):
        """Test that batch generation raises error for unknown molecule."""
        with patch(
            "features.interface_molecules.service.get_interface_molecule_info",
            return_value={},  # Empty - no molecules
        ):
            from contracts.errors import ContractError
            from features.interface_molecules.service import (
                batch_generate_interface_molecule_cells,
            )

            request = InterfaceMoleculeBatchGenerateRequest(
                mol_id="UnknownMol",
                target_density=1.0,
            )

            with pytest.raises(ContractError) as exc_info:
                await batch_generate_interface_molecule_cells(request)

            assert "not found" in str(exc_info.value).lower()


class TestBatchFailureSchema:
    """Tests for failed_count and failures[] in batch response."""

    @pytest.fixture
    def mock_molecule_info(self):
        """Mock molecule info for NaCl."""
        return {
            "NaCl": {
                "category": "deicing",
                "name": "Sodium Chloride",
                "formula": "NaCl",
                "atom_count": 2,
                "molecular_weight": 58.44,
                "elements": ["Na", "Cl"],
            },
        }

    @pytest.mark.asyncio
    async def test_batch_failures_populated_on_invalid_request(self, mock_molecule_info):
        """When create_interface_molecule_cell raises INVALID_REQUEST,
        the failure is captured in failed_count and failures[]."""
        from contracts.errors import ContractError, ErrorCode
        from features.interface_molecules.service import (
            batch_generate_interface_molecule_cells,
        )

        async def mock_create_fail(req):
            raise ContractError(
                ErrorCode.INVALID_REQUEST,
                f"Unsupported molecule for size {req.lx_angstrom}",
            )

        with (
            patch(
                "features.interface_molecules.service.get_interface_molecule_info",
                return_value=mock_molecule_info,
            ),
            patch(
                "features.interface_molecules.service._get_existing_interface_cell",
                return_value=None,
            ),
            patch(
                "features.interface_molecules.service.create_interface_molecule_cell",
                side_effect=mock_create_fail,
            ),
        ):
            request = InterfaceMoleculeBatchGenerateRequest(
                mol_id="NaCl",
                xy_min=35.0,
                xy_max=55.0,  # 3 sizes: 35, 45, 55
                lz_angstrom=10.0,
                target_density=2.16,
            )

            result = await batch_generate_interface_molecule_cells(request)

        assert result.failed_count > 0
        assert result.failed_count == len(result.failures)
        assert result.generated_count == 0
        assert result.skipped_count == 0

        # Each failure item has the required fields
        for failure in result.failures:
            assert failure.lx_angstrom > 0
            assert failure.ly_angstrom > 0
            assert failure.lz_angstrom > 0
            assert failure.error_code == "E1007"
            assert len(failure.message) > 0

    @pytest.mark.asyncio
    async def test_batch_counts_sum_equals_total_sizes(self, mock_molecule_info):
        """generated + skipped + failed == total enumerated sizes."""
        from contracts.errors import ContractError, ErrorCode
        from features.interface_molecules.service import (
            _enumerate_interface_batch_sizes,
            batch_generate_interface_molecule_cells,
        )

        call_count = 0

        async def mock_create_mixed(req):
            """Fail on the second size (45), succeed on others."""
            nonlocal call_count
            call_count += 1
            if req.lx_angstrom == 45.0:
                raise ContractError(
                    ErrorCode.INVALID_REQUEST,
                    "Unsupported at 45 Angstrom",
                )
            return InterfaceMoleculeCellResponse(
                cell_id=f"ifc_ok{call_count:03d}",
                name=req.name,
                status="ready",
                mol_id=req.mol_id,
                atom_count=100,
                molecule_count=50,
                target_density=req.target_density,
                boundary_mode=req.boundary_mode.value,
                lx_angstrom=req.lx_angstrom,
                ly_angstrom=req.ly_angstrom,
                lz_angstrom=req.lz_angstrom,
            )

        existing_cell_35 = {
            "cell_id": "ifc_existing35",
            "name": "existing_35",
            "status": "ready",
            "mol_id": "NaCl",
            "atom_count": 100,
            "molecule_count": 50,
            "target_density": 2.16,
            "boundary_mode": "ppf",
            "lx_angstrom": 35.0,
            "ly_angstrom": 35.0,
            "lz_angstrom": 10.0,
        }

        def mock_get_existing(mol_id, lx, ly, lz, target_density, boundary_mode):
            """Return existing cell for 35 Angstrom only."""
            if lx == 35.0:
                return existing_cell_35
            return None

        with (
            patch(
                "features.interface_molecules.service.get_interface_molecule_info",
                return_value=mock_molecule_info,
            ),
            patch(
                "features.interface_molecules.service._get_existing_interface_cell",
                side_effect=mock_get_existing,
            ),
            patch(
                "features.interface_molecules.service.create_interface_molecule_cell",
                side_effect=mock_create_mixed,
            ),
        ):
            request = InterfaceMoleculeBatchGenerateRequest(
                mol_id="NaCl",
                xy_min=35.0,
                xy_max=55.0,  # sizes: 35, 45, 55
                lz_angstrom=10.0,
                target_density=2.16,
            )

            result = await batch_generate_interface_molecule_cells(request)

        total_sizes = len(_enumerate_interface_batch_sizes(35.0, 55.0))
        assert result.generated_count + result.skipped_count + result.failed_count == total_sizes

        # Verify individual counts
        assert result.skipped_count == 1  # 35 was existing
        assert result.failed_count == 1  # 45 failed
        assert result.generated_count == 1  # 55 succeeded

    @pytest.mark.asyncio
    async def test_batch_failure_item_schema_fields(self, mock_molecule_info):
        """Each BatchFailureItem has lx_angstrom, ly_angstrom, lz_angstrom,
        error_code, and message."""
        from api.schemas.interface_molecules import BatchFailureItem
        from contracts.errors import ContractError, ErrorCode
        from features.interface_molecules.service import (
            batch_generate_interface_molecule_cells,
        )

        async def mock_create_fail(req):
            raise ContractError(
                ErrorCode.INVALID_REQUEST,
                "Topology unsupported",
            )

        with (
            patch(
                "features.interface_molecules.service.get_interface_molecule_info",
                return_value=mock_molecule_info,
            ),
            patch(
                "features.interface_molecules.service._get_existing_interface_cell",
                return_value=None,
            ),
            patch(
                "features.interface_molecules.service.create_interface_molecule_cell",
                side_effect=mock_create_fail,
            ),
        ):
            request = InterfaceMoleculeBatchGenerateRequest(
                mol_id="NaCl",
                xy_min=40.0,
                xy_max=40.0,  # single size
                lz_angstrom=10.0,
                target_density=2.16,
            )

            result = await batch_generate_interface_molecule_cells(request)

        assert len(result.failures) == 1
        failure = result.failures[0]

        # Verify it is a BatchFailureItem with all required fields
        assert isinstance(failure, BatchFailureItem)
        assert failure.lx_angstrom == 40.0
        assert failure.ly_angstrom == 40.0
        assert failure.lz_angstrom == 10.0
        assert failure.error_code == str(ErrorCode.INVALID_REQUEST)
        assert "Topology unsupported" in failure.message
