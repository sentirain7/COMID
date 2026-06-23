"""v00.99.96 — strict FF readiness semantic contract.

Previously (v00.99.30) a missing or incomplete organic curated GAFF2
artifact was reported as a *warning* with ``is_submittable=True``
because the build pipeline auto-regenerated via
``ensure_organic_artifact``. Under the explicit-generation policy
introduced in v00.99.96 the build path is strict observe-only — it
does NOT regenerate — so any FF that is not already on disk must
surface as **blocked** at preview/validate time. Database >
Single Molecule / FF Parameters is the only supported entry point
for generation.

These tests lock the new semantic so a future regression cannot
silently re-open the gate:

* ``resolve_ff_hint`` → ``is_submittable=False`` + ``blocked_reason``
  when the organic curated artifact is missing or incomplete.
* ``collect_binder_ff_issues`` → the same readiness shape is
  classified as ``blocked_items`` (not ``warning_items``).
* ``artifact_warning`` is still populated for display compatibility,
  but it is no longer the authoritative gate.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@contextmanager
def _stub_resolve_ff_hint(mapping):
    """Redirect resolve_ff_hint to a dict lookup for eligibility tests."""
    from features.molecules import catalog

    def _fake(mol_id: str):
        if mol_id in mapping:
            base = {
                "ff_hint": "gaff2",
                "ff_display_label": "GAFF2",
                "parameterization_mode": None,
                "submit_ff_type": "bulk_ff_gaff2",
            }
            base.update(mapping[mol_id])
            return base
        raise KeyError(mol_id)

    with patch.object(catalog, "resolve_ff_hint", side_effect=_fake):
        yield


# ---------------------------------------------------------------------------
# resolve_ff_hint strict semantic
# ---------------------------------------------------------------------------


class TestResolveFFHintStrict:
    """Organic curated artifact readiness must fail-closed."""

    def _patched_readiness(self, *, exists: bool, complete: bool):
        """Stub _get_organic_artifact_readiness to the desired state."""
        return {
            "exists": exists,
            "complete": complete,
            "source_id": "Toluene",
            "blocked_reason": (
                None
                if (exists and complete)
                else f"Artifact {'incomplete' if exists else 'not found'} for 'Toluene'."
            ),
        }

    def _db_stub(self):
        """Minimal MoleculeDB stub that yields an organic curated mol."""

        class _DB:
            def get_additive_definition(self, mol_id):
                return None

            def get_ff_assignment(self, mol_id):
                return {
                    "route": "organic_curated_artifact",
                    "status": "active",
                    "source_id": "Toluene",
                    "canonical_smiles": "Cc1ccccc1",
                    "formal_charge": 0,
                }

            def get_additives_load_error(self):
                return None

            def get_ff_assignment_load_error(self):
                return None

        return _DB()

    def test_artifact_complete_keeps_submittable(self):
        from features.molecules import catalog

        with (
            patch("api.deps.get_molecule_db", return_value=self._db_stub()),
            patch.object(
                catalog,
                "_get_organic_artifact_readiness",
                return_value=self._patched_readiness(exists=True, complete=True),
            ),
        ):
            hint = catalog.resolve_ff_hint("Toluene")
        assert hint["is_submittable"] is True
        assert hint["blocked_reason"] is None
        assert hint["artifact_warning"] is None
        assert hint["ff_display_label"] == "GAFF2"

    def test_artifact_missing_blocks_submit(self):
        from features.molecules import catalog

        with (
            patch("api.deps.get_molecule_db", return_value=self._db_stub()),
            patch.object(
                catalog,
                "_get_organic_artifact_readiness",
                return_value=self._patched_readiness(exists=False, complete=False),
            ),
        ):
            hint = catalog.resolve_ff_hint("Toluene")
        assert hint["is_submittable"] is False, (
            "v00.99.96: a missing organic artifact must block submit; the "
            "build pipeline no longer auto-generates so preview/validate "
            "is the only gate."
        )
        assert "Generate" in (hint["blocked_reason"] or "")
        assert "Toluene" in (hint["blocked_reason"] or "")
        # Display-only warning is still populated so existing UI that reads
        # artifact_warning keeps showing a consistent message.
        assert hint["artifact_warning"] is not None
        assert hint["ff_display_label"] == "GAFF2 (not generated)"

    def test_artifact_incomplete_blocks_submit(self):
        from features.molecules import catalog

        with (
            patch("api.deps.get_molecule_db", return_value=self._db_stub()),
            patch.object(
                catalog,
                "_get_organic_artifact_readiness",
                return_value=self._patched_readiness(exists=True, complete=False),
            ),
        ):
            hint = catalog.resolve_ff_hint("Toluene")
        assert hint["is_submittable"] is False
        assert "incomplete" in (hint["artifact_warning"] or "").lower()


# ---------------------------------------------------------------------------
# collect_binder_ff_issues strict semantic
# ---------------------------------------------------------------------------


class TestCollectBinderFFIssuesStrict:
    """Missing organic artifact must land in blocked_items, not warning_items."""

    def test_production_shape_blocks(self):
        """With the v00.99.96 resolve_ff_hint shape (is_submittable=False +
        artifact_warning set) the aggregator routes to blocked_items."""
        from forcefield.eligibility import collect_binder_ff_issues

        mapping = {
            "Toluene": {
                "is_submittable": False,
                "blocked_reason": (
                    "Artifact not found for 'Toluene'. "
                    "Generate via Molecules catalog before submit."
                ),
                "artifact_warning": "Artifact not found for 'Toluene'.",
                "route": "organic_curated_artifact",
                "status": "active",
            },
        }
        with _stub_resolve_ff_hint(mapping):
            result = collect_binder_ff_issues(
                mol_ids=["Toluene"],
                additive_ids=[],
            )
        assert result["has_blocked"] is True
        blocked_ids = [i["item_id"] for i in result["blocked_items"]]
        assert "Toluene" in blocked_ids
        assert result["warning_items"] == []

    def test_complete_artifact_passes(self):
        from forcefield.eligibility import collect_binder_ff_issues

        mapping = {
            "Toluene": {
                "is_submittable": True,
                "blocked_reason": None,
                "artifact_warning": None,
                "route": "organic_curated_artifact",
                "status": "active",
            },
        }
        with _stub_resolve_ff_hint(mapping):
            result = collect_binder_ff_issues(
                mol_ids=["Toluene"],
                additive_ids=[],
            )
        assert result["has_blocked"] is False
        assert result["blocked_items"] == []
        assert result["warning_items"] == []

    def test_message_surfaces_generate_guidance(self):
        """blocked_items[].message must include Molecules catalog
        guidance so the operator knows where to go."""
        from forcefield.eligibility import collect_binder_ff_issues

        mapping = {
            "Toluene": {
                "is_submittable": False,
                "blocked_reason": (
                    "Artifact not found for 'Toluene'. "
                    "Generate via Molecules catalog before submit."
                ),
                "artifact_warning": "Artifact not found for 'Toluene'.",
                "route": "organic_curated_artifact",
                "status": "active",
            },
        }
        with _stub_resolve_ff_hint(mapping):
            result = collect_binder_ff_issues(
                mol_ids=["Toluene"],
                additive_ids=[],
            )
        msg = result["blocked_items"][0]["message"]
        assert "Generate" in msg
        assert "Molecules catalog" in msg


# ---------------------------------------------------------------------------
# Batch binder FF gate now includes binder molecules
# ---------------------------------------------------------------------------


class TestBatchBinderGateCoversBinderMolecules:
    """Prior to v00.99.96 the batch validate/create FF gate only inspected
    additive_ids — binder molecules (SARA components) were unchecked and
    a missing organic artifact would only surface at build time. This
    test locks the new behaviour: binder molecules are enumerated from
    the combinatorial product and passed through the same gate."""

    def test_enumerate_helper_returns_union(self):
        from features.batch_job_binder_cell import service as batch_service

        class _DB:
            def get_temperature_code(self, config, temp):
                return f"{int(temp):04d}"

            def get_binder_composition_with_aging(self, config, **kwargs):
                # Fake: each combination yields 2 binder mols, one shared
                # across all combinations, one unique per combination.
                binder_type = kwargs["binder_type"]
                aging = kwargs["aging"]
                temp_code = kwargs["temp_code"]
                return {
                    "COMMON-SAT": 10,
                    f"{binder_type}-{aging}-{temp_code}": 5,
                }

        with (
            patch("api.deps.get_molecule_db", return_value=_DB()),
            patch("api.deps.get_aging_config", return_value={"fake": True}),
        ):
            mol_ids = batch_service._enumerate_batch_binder_mol_ids(
                binder_types=["AAA1"],
                structure_sizes=["X1"],
                aging_states=["non_aging", "short_aging"],
                temperatures_k=[293.0, 313.0],
            )
        # 1 shared + (2 aging × 2 temp) unique = 5 total
        assert "COMMON-SAT" in mol_ids
        assert len(mol_ids) == 5

    def test_enumerate_empty_axis_returns_empty(self):
        """Safety: if any axis is empty the helper returns [] rather than
        fabricating defaults. The runner's own validation will reject the
        request before any FF gate is applied."""
        from features.batch_job_binder_cell import service as batch_service

        with (
            patch("api.deps.get_aging_config", return_value={"fake": True}),
        ):
            assert (
                batch_service._enumerate_batch_binder_mol_ids(
                    binder_types=[],
                    structure_sizes=["X1"],
                    aging_states=["non_aging"],
                    temperatures_k=[293.0],
                )
                == []
            )
