"""Tests for features.jobs.chain_resolver."""

from unittest.mock import MagicMock

from features.jobs.chain_resolver import (
    derive_chain_key_from_request,
    has_injected_equilibration,
    resolve_chain_key,
)

# ---------------------------------------------------------------------------
# resolve_chain_key
# ---------------------------------------------------------------------------


class TestResolveChainKey:
    """Test resolve_chain_key priority logic."""

    def test_metadata_chain_key_highest_priority(self):
        """metadata_json['chain_key'] takes priority over everything."""
        request = MagicMock()
        request.study_type.value = "layer_bulkff"
        metadata = {"chain_key": "layer"}

        result = resolve_chain_key(
            protocol_request=request,
            run_tier="screening",
            metadata_json=metadata,
        )
        assert result == "layer"

    def test_protocol_request_layer(self):
        """LAYER_BULKFF study_type without tensile -> 'layer'."""
        from contracts.schemas import RunTier, StudyType

        request = MagicMock()
        request.run_tier = RunTier.SCREENING
        request.study_type = StudyType.LAYER_BULKFF
        request.tensile_spec = None

        result = resolve_chain_key(protocol_request=request, run_tier="screening")
        assert result == "layer"

    def test_protocol_request_tensile_layer(self):
        """LAYER_BULKFF with enabled tensile_spec -> 'tensile_layer'."""
        from contracts.schemas import RunTier, StudyType

        request = MagicMock()
        request.run_tier = RunTier.SCREENING
        request.study_type = StudyType.LAYER_BULKFF
        tensile = MagicMock()
        tensile.enabled = True
        request.tensile_spec = tensile

        result = resolve_chain_key(protocol_request=request, run_tier="screening")
        assert result == "tensile_layer"

    def test_protocol_request_bulk(self):
        """BULK study_type -> falls through to run_tier value."""
        from contracts.schemas import RunTier, StudyType

        request = MagicMock()
        request.run_tier = RunTier.CONFIRM
        request.study_type = StudyType.BULK

        result = resolve_chain_key(protocol_request=request)
        assert result == "confirm"

    def test_fallback_to_run_tier(self):
        """No metadata, no request -> use run_tier string."""
        result = resolve_chain_key(run_tier="viscosity")
        assert result == "viscosity"

    def test_fallback_default(self):
        """No arguments -> 'screening'."""
        result = resolve_chain_key()
        assert result == "screening"

    def test_metadata_non_string_chain_key_ignored(self):
        """Non-string chain_key in metadata is ignored."""
        result = resolve_chain_key(
            run_tier="confirm",
            metadata_json={"chain_key": 123},
        )
        assert result == "confirm"

    def test_metadata_empty_chain_key_ignored(self):
        """Empty string chain_key in metadata is ignored."""
        result = resolve_chain_key(
            run_tier="confirm",
            metadata_json={"chain_key": ""},
        )
        assert result == "confirm"


# ---------------------------------------------------------------------------
# derive_chain_key_from_request
# ---------------------------------------------------------------------------


class TestDeriveChainKeyFromRequest:
    """Test derive_chain_key_from_request mirrors protocol_chain.py logic."""

    def test_bulk_screening(self):
        from contracts.schemas import RunTier, StudyType

        request = MagicMock()
        request.run_tier = RunTier.SCREENING
        request.study_type = StudyType.BULK
        assert derive_chain_key_from_request(request) == "screening"

    def test_layer_no_tensile(self):
        from contracts.schemas import RunTier, StudyType

        request = MagicMock()
        request.run_tier = RunTier.SCREENING
        request.study_type = StudyType.LAYER_BULKFF
        request.tensile_spec = None
        assert derive_chain_key_from_request(request) == "layer"

    def test_layer_tensile_disabled(self):
        from contracts.schemas import RunTier, StudyType

        request = MagicMock()
        request.run_tier = RunTier.SCREENING
        request.study_type = StudyType.LAYER_BULKFF
        tensile = MagicMock()
        tensile.enabled = False
        request.tensile_spec = tensile
        assert derive_chain_key_from_request(request) == "layer"

    def test_layer_tensile_enabled(self):
        from contracts.schemas import RunTier, StudyType

        request = MagicMock()
        request.run_tier = RunTier.CONFIRM
        request.study_type = StudyType.LAYER_BULKFF
        tensile = MagicMock()
        tensile.enabled = True
        request.tensile_spec = tensile
        assert derive_chain_key_from_request(request) == "tensile_layer"

    def test_layer_tensile_quasi_static(self):
        from contracts.schemas import RunTier, StudyType, TensileMode

        request = MagicMock()
        request.run_tier = RunTier.SCREENING
        request.study_type = StudyType.LAYER_BULKFF
        tensile = MagicMock()
        tensile.enabled = True
        tensile.mode = TensileMode.QUASI_STATIC
        request.tensile_spec = tensile
        assert derive_chain_key_from_request(request) == "tensile_layer_qs"


# ---------------------------------------------------------------------------
# has_injected_equilibration
# ---------------------------------------------------------------------------


class TestHasInjectedEquilibration:
    """Test has_injected_equilibration detection."""

    def test_metadata_flag_true(self):
        assert has_injected_equilibration(metadata_json={"has_equilibration": True})

    def test_metadata_flag_false(self):
        assert not has_injected_equilibration(metadata_json={"has_equilibration": False})

    def test_metadata_flag_absent(self):
        assert not has_injected_equilibration(metadata_json={"source": "test"})

    def test_protocol_request_enabled(self):
        request = MagicMock()
        eq = MagicMock()
        eq.enabled = True
        request.equilibration_settings = eq

        assert has_injected_equilibration(protocol_request=request)

    def test_protocol_request_disabled(self):
        request = MagicMock()
        eq = MagicMock()
        eq.enabled = False
        request.equilibration_settings = eq

        assert not has_injected_equilibration(protocol_request=request)

    def test_protocol_request_no_eq(self):
        request = MagicMock()
        request.equilibration_settings = None

        assert not has_injected_equilibration(protocol_request=request)

    def test_no_sources(self):
        assert not has_injected_equilibration()

    def test_metadata_priority_over_request(self):
        """metadata flag should take priority over request."""
        request = MagicMock()
        eq = MagicMock()
        eq.enabled = True
        request.equilibration_settings = eq

        # metadata says False -> should return False despite request saying True
        assert not has_injected_equilibration(
            protocol_request=request,
            metadata_json={"has_equilibration": False},
        )
