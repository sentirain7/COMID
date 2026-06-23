"""Unit tests for interface molecule schema validation."""

import pytest
from pydantic import ValidationError

from api.schemas.interface_molecules import (
    InterfaceMoleculeBatchGenerateRequest,
    InterfaceMoleculeBatchGenerateResponse,
    InterfaceMoleculeCellCreateRequest,
    InterfaceMoleculeCellResponse,
)
from contracts.schemas import AmorphousBoundaryMode


class TestInterfaceMoleculeBatchGenerateRequest:
    """Tests for batch generation request schema."""

    def test_valid_request_with_defaults(self):
        """Test that a valid request with defaults is accepted."""
        req = InterfaceMoleculeBatchGenerateRequest(
            mol_id="NaCl",
            target_density=2.16,
        )
        assert req.mol_id == "NaCl"
        assert req.xy_min == 35.0  # default
        assert req.xy_max == 60.0  # default
        assert req.lz_angstrom == 10.0  # default
        assert req.target_density == 2.16
        assert req.boundary_mode == AmorphousBoundaryMode.PPF  # default

    def test_valid_request_with_custom_range(self):
        """Test that a valid request with custom XY range is accepted."""
        req = InterfaceMoleculeBatchGenerateRequest(
            mol_id="H2O",
            xy_min=40.0,
            xy_max=80.0,
            lz_angstrom=15.0,
            target_density=1.0,
            boundary_mode=AmorphousBoundaryMode.PPP,
        )
        assert req.xy_min == 40.0
        assert req.xy_max == 80.0
        assert req.lz_angstrom == 15.0
        assert req.boundary_mode == AmorphousBoundaryMode.PPP

    def test_xy_max_less_than_xy_min_raises_error(self):
        """Test that xy_max < xy_min raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            InterfaceMoleculeBatchGenerateRequest(
                mol_id="NaCl",
                xy_min=60.0,
                xy_max=35.0,
                target_density=2.16,
            )
        # Check error message contains the validation failure
        errors = exc_info.value.errors()
        assert len(errors) >= 1
        assert "xy_max" in str(errors) or "xy_min" in str(errors)

    def test_xy_max_equals_xy_min_is_valid(self):
        """Test that xy_max == xy_min is valid (single size)."""
        req = InterfaceMoleculeBatchGenerateRequest(
            mol_id="NaCl",
            xy_min=50.0,
            xy_max=50.0,
            target_density=2.16,
        )
        assert req.xy_min == req.xy_max == 50.0

    def test_mol_id_required(self):
        """Test that mol_id is required."""
        with pytest.raises(ValidationError) as exc_info:
            InterfaceMoleculeBatchGenerateRequest(target_density=1.0)
        errors = exc_info.value.errors()
        assert any("mol_id" in str(e) for e in errors)

    def test_mol_id_min_length(self):
        """Test that mol_id cannot be empty."""
        with pytest.raises(ValidationError) as exc_info:
            InterfaceMoleculeBatchGenerateRequest(mol_id="", target_density=1.0)
        errors = exc_info.value.errors()
        assert any("mol_id" in str(e) or "min_length" in str(e) for e in errors)

    def test_target_density_required(self):
        """Test that target_density is required (no default)."""
        with pytest.raises(ValidationError) as exc_info:
            InterfaceMoleculeBatchGenerateRequest(mol_id="NaCl")
        errors = exc_info.value.errors()
        assert any("target_density" in str(e) for e in errors)

    def test_target_density_must_be_positive(self):
        """Test that target_density must be > 0."""
        with pytest.raises(ValidationError) as exc_info:
            InterfaceMoleculeBatchGenerateRequest(
                mol_id="NaCl",
                target_density=0.0,
            )
        errors = exc_info.value.errors()
        assert any("target_density" in str(e) or "greater_than" in str(e) for e in errors)

    def test_xy_min_must_be_positive(self):
        """Test that xy_min must be > 0."""
        with pytest.raises(ValidationError) as exc_info:
            InterfaceMoleculeBatchGenerateRequest(
                mol_id="NaCl",
                xy_min=0.0,
                target_density=2.16,
            )
        errors = exc_info.value.errors()
        assert any("xy_min" in str(e) or "greater_than" in str(e) for e in errors)

    def test_lz_must_be_positive(self):
        """Test that lz_angstrom must be > 0."""
        with pytest.raises(ValidationError) as exc_info:
            InterfaceMoleculeBatchGenerateRequest(
                mol_id="NaCl",
                lz_angstrom=-5.0,
                target_density=2.16,
            )
        errors = exc_info.value.errors()
        assert any("lz_angstrom" in str(e) or "greater_than" in str(e) for e in errors)


class TestInterfaceMoleculeCellCreateRequest:
    """Tests for cell create request schema."""

    def test_valid_create_request(self):
        """Test that a valid create request is accepted."""
        req = InterfaceMoleculeCellCreateRequest(
            name="test_cell",
            mol_id="H2O",
            lx_angstrom=40.0,
            ly_angstrom=40.0,
            lz_angstrom=10.0,
            target_density=1.0,
        )
        assert req.name == "test_cell"
        assert req.mol_id == "H2O"

    def test_name_min_length(self):
        """Test that name cannot be empty."""
        with pytest.raises(ValidationError) as exc_info:
            InterfaceMoleculeCellCreateRequest(
                name="",
                mol_id="H2O",
                target_density=1.0,
            )
        errors = exc_info.value.errors()
        assert any("name" in str(e) or "min_length" in str(e) for e in errors)


class TestInterfaceMoleculeBatchGenerateResponse:
    """Tests for batch generation response schema."""

    def test_response_serialization(self):
        """Test that response can be serialized."""
        resp = InterfaceMoleculeBatchGenerateResponse(
            mol_id="NaCl",
            mol_name="Sodium Chloride",
            generated_count=3,
            skipped_count=1,
            cells=[],
        )
        data = resp.model_dump()
        assert data["mol_id"] == "NaCl"
        assert data["generated_count"] == 3
        assert data["skipped_count"] == 1

    def test_response_with_cells(self):
        """Test response with cell list."""
        cell = InterfaceMoleculeCellResponse(
            cell_id="ifc_test001",
            name="test_cell",
            status="ready",
            mol_id="NaCl",
            atom_count=100,
            molecule_count=50,
            target_density=2.16,
            boundary_mode="ppf",
            lx_angstrom=40.0,
            ly_angstrom=40.0,
            lz_angstrom=10.0,
        )
        resp = InterfaceMoleculeBatchGenerateResponse(
            mol_id="NaCl",
            mol_name="Sodium Chloride",
            generated_count=1,
            skipped_count=0,
            cells=[cell],
        )
        assert len(resp.cells) == 1
        assert resp.cells[0].cell_id == "ifc_test001"
