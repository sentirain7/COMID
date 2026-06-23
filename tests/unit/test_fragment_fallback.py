"""Tests for fragment-based GAFF2 fallback."""
from pathlib import Path


class TestFragmentFallbackApplicability:
    def test_unsupported_element_returns_none(self):
        """P-containing molecule should return None."""
        from forcefield.fragment_fallback import generate_fragment_fallback_artifact

        result = generate_fragment_fallback_artifact(
            Path("data/molecules/additives/PPA.mol"), "PPA", 0
        )
        assert result is None

    def test_cnt_produces_valid_gaff2_artifact(self):
        """Neutral all-carbon CNT should type via fragment fallback (the
        canonical SCF-pathological case)."""
        import pytest

        from forcefield.fragment_fallback import generate_fragment_fallback_artifact

        mol = Path("data/molecules/additives/Carbon_Nano_Tube.mol")
        if not mol.exists():
            pytest.skip("CNT structure not present")
        art = generate_fragment_fallback_artifact(mol, "Carbon_Nano_Tube", 0)
        assert art is not None
        assert art["generator"] == "fragment_fallback_gaff2"
        assert art["ff_family"] == "organic_gaff2"
        assert art["atoms"], "expected typed atoms"
        # GAFF2-native types -> mixing-rule compatible; near-neutral by symmetry
        assert {a["ff_type"] for a in art["atoms"]} <= {"ca", "ha", "c3", "hc"}
        assert abs(sum(a.get("charge", 0.0) for a in art["atoms"])) < 1e-3


class TestFragmentFallbackProfile:
    def test_profile_registered(self):
        from features.molecules.artifact_service import SUPPORTED_GENERATION_PROFILES

        assert "fragment_fallback" in SUPPORTED_GENERATION_PROFILES


class TestFragmentPipelineChargeOverride:
    """The fragment_fallback profile now runs the canonical antechamber(-c gas)
    ->parmchk2->tleap->parmed pipeline (so it gets full GAFF2 dihedrals), then
    overwrites the Gasteiger charges with fragment-reference AM1-BCC values.
    These cover the charge-override helper without needing AmberTools."""

    def test_charges_spread_evenly_not_dumped_on_one_atom(self):
        """A CNT-like 60 ca + 20 ha set sums far from neutral in the reference
        table; the residual MUST be spread uniformly (legacy fragment behaviour),
        never collapsed onto one atom (the AM1-BCC normaliser's tiny-residual
        strategy, which would put an unphysical bulk charge on a single carbon)."""
        from features.molecules.artifact_service import _apply_fragment_reference_charges

        atoms = [{"element": "C", "ff_type": "ca", "charge": 9.9} for _ in range(60)]
        atoms += [{"element": "H", "ff_type": "ha", "charge": 9.9} for _ in range(20)]
        out = _apply_fragment_reference_charges(atoms, 0)

        assert abs(sum(a["charge"] for a in out)) < 1e-6  # neutral
        # no single atom carries an unphysical bulk charge (the +5e bug)
        assert max(abs(a["charge"]) for a in out) < 0.5
        ca = next(a["charge"] for a in out if a["ff_type"] == "ca")
        ha = next(a["charge"] for a in out if a["ff_type"] == "ha")
        assert ca < 0 < ha  # AM1-BCC reference: ca negative, ha positive

    def test_unknown_type_defaults_zero_then_normalised(self):
        from features.molecules.artifact_service import _apply_fragment_reference_charges

        atoms = [{"element": "C", "ff_type": "zz_unknown", "charge": 1.0} for _ in range(4)]
        out = _apply_fragment_reference_charges(atoms, 0)
        assert all(abs(a["charge"]) < 1e-6 for a in out)


class TestFragmentEligibilityGate:
    def test_rejects_non_chons(self):
        import pytest

        from features.molecules.artifact_service import _assert_fragment_fallback_eligible
        from features.molecules.exceptions import ArtifactGenerationError

        ppa = Path("data/molecules/additives/PPA.mol")
        if not ppa.exists():
            pytest.skip("PPA structure not present")
        with pytest.raises(ArtifactGenerationError):
            _assert_fragment_fallback_eligible(ppa, "PPA", 0)

    def test_accepts_neutral_chons(self):
        import pytest

        from features.molecules.artifact_service import _assert_fragment_fallback_eligible

        cnt = Path("data/molecules/additives/Carbon_Nano_Tube.mol")
        if not cnt.exists():
            pytest.skip("CNT structure not present")
        # neutral all-carbon -> eligible -> no exception
        _assert_fragment_fallback_eligible(cnt, "Carbon_Nano_Tube", 0)


class TestFragmentFallbackGovernance:
    def test_fragment_stack_blocks_submit(self):
        from contracts.policies.stack_governance import is_workflow_allowed

        assert is_workflow_allowed("gaff2_fragment_fallback_v1", "submit") is False
        assert is_workflow_allowed("gaff2_fragment_fallback_v1", "build") is True
        assert is_workflow_allowed("gaff2_fragment_fallback_v1", "benchmark") is True

    def test_fragment_generator_triggers_fallback_stack(self):
        from contracts.policies.forcefield import build_ff_provenance

        sources = [{"mol_id": "test", "source_id": "test", "generator": "fragment_fallback_gaff2"}]
        result = build_ff_provenance(study_type="bulk", organic_sources=sources)
        assert result["metadata"]["stack_id"] == "gaff2_fragment_fallback_v1"

    def test_curated_stays_validated(self):
        from contracts.policies.forcefield import build_ff_provenance

        sources = [{"mol_id": "CNT", "source_id": "CNT", "generator": "curated_carbon_sp2"}]
        result = build_ff_provenance(study_type="bulk", organic_sources=sources)
        assert result["metadata"]["stack_id"] == "gaff2_am1bcc_v1"


class TestFailureHistorySkip:
    """Logic ②: route a molecule with a prior SCF-failure / fragment verdict
    straight to fragment_fallback, skipping the ~2h of doomed antechamber."""

    class _Sidecar:
        def __init__(self, generation_profile="", failure_code=None):
            self.generation_profile = generation_profile
            self.failure_code = failure_code

    class _Store:
        def __init__(self, sidecar):
            self._sidecar = sidecar

        def get(self, source_id):
            return self._sidecar

    def _skip(self, sidecar):
        from features.molecules.artifact_runtime import _should_skip_to_fragment

        return _should_skip_to_fragment(self._Store(sidecar), "X")

    def test_skip_on_prior_fragment_success(self):
        assert self._skip(self._Sidecar(generation_profile="fragment_fallback")) is True

    def test_skip_on_sqm_robust_scf_timeout(self):
        assert (
            self._skip(self._Sidecar(generation_profile="sqm_robust", failure_code="sqm_timeout"))
            is True
        )

    def test_no_skip_on_normal_baseline(self):
        assert self._skip(self._Sidecar(generation_profile="baseline")) is False

    def test_no_skip_without_history(self):
        assert self._skip(None) is False

    def test_no_skip_on_non_scf_failure(self):
        # sqm_robust failed for a non-SCF reason → not a "needs fragment" verdict
        assert (
            self._skip(
                self._Sidecar(generation_profile="sqm_robust", failure_code="antechamber_failed")
            )
            is False
        )

    def test_policy_default_on(self):
        from contracts.policies.ff_generation import DEFAULT_FF_GENERATION_POLICY

        assert DEFAULT_FF_GENERATION_POLICY.skip_to_fragment_on_prior_scf_failure is True


class TestEfficiencyLayer:
    """v01.06.20 efficiency layer: bounded timeouts + size pre-screen."""

    def test_timeout_policy_values(self):
        from contracts.policies.ff_generation import DEFAULT_FF_GENERATION_POLICY as p

        assert p.baseline_timeout_s == 600
        # sqm_robust cut from the legacy 7200s to cap non-convergent waste
        assert p.sqm_robust_timeout_s < 7200
        assert p.sqm_robust_timeout_s == 1800

    def test_prescreen_threshold_above_largest_convergent(self):
        """Threshold MUST sit above the largest molecule that converges in this
        project (Polymer_PolyEthylene, 212 atoms) so no good FF is degraded."""
        from contracts.policies.ff_generation import DEFAULT_FF_GENERATION_POLICY as p

        assert p.prescreen_max_atoms > 212

    def test_prescreen_false_below_threshold(self):
        import pytest

        from features.molecules.artifact_runtime import _should_prescreen_to_fragment

        cnt = Path("data/molecules/additives/Carbon_Nano_Tube.mol")
        if not cnt.exists():
            pytest.skip("CNT structure not present")
        # 80 atoms < 300 -> not pre-screened (handled by failure-history skip instead)
        assert _should_prescreen_to_fragment(cnt) is False

    def test_prescreen_true_above_threshold(self, monkeypatch):
        import pytest

        import contracts.policies.ff_generation as ffgen
        from contracts.policies.ff_generation import FFGenerationPolicy
        from features.molecules import artifact_runtime

        cnt = Path("data/molecules/additives/Carbon_Nano_Tube.mol")
        if not cnt.exists():
            pytest.skip("CNT structure not present")
        # lower the threshold below CNT's 80 atoms -> now pre-screened
        monkeypatch.setattr(ffgen, "DEFAULT_FF_GENERATION_POLICY", FFGenerationPolicy(prescreen_max_atoms=50))
        assert artifact_runtime._should_prescreen_to_fragment(cnt) is True

    def test_prescreen_disabled_is_noop(self, monkeypatch):
        import pytest

        import contracts.policies.ff_generation as ffgen
        from contracts.policies.ff_generation import FFGenerationPolicy
        from features.molecules import artifact_runtime

        cnt = Path("data/molecules/additives/Carbon_Nano_Tube.mol")
        if not cnt.exists():
            pytest.skip("CNT structure not present")
        monkeypatch.setattr(
            ffgen,
            "DEFAULT_FF_GENERATION_POLICY",
            FFGenerationPolicy(prescreen_to_fragment_enabled=False, prescreen_max_atoms=50),
        )
        assert artifact_runtime._should_prescreen_to_fragment(cnt) is False

    def test_prescreen_skips_non_chons(self, monkeypatch):
        """Large non-CHONS molecules are NOT routed to fragment (it can't handle
        them); they fall through to the normal chain / fail-closed."""
        import pytest

        import contracts.policies.ff_generation as ffgen
        from contracts.policies.ff_generation import FFGenerationPolicy
        from features.molecules import artifact_runtime

        ppa = Path("data/molecules/additives/PPA.mol")
        if not ppa.exists():
            pytest.skip("PPA structure not present")
        monkeypatch.setattr(ffgen, "DEFAULT_FF_GENERATION_POLICY", FFGenerationPolicy(prescreen_max_atoms=1))
        # PPA contains P -> not CHONS -> not pre-screened even when over threshold
        assert artifact_runtime._should_prescreen_to_fragment(ppa) is False
