"""Phase 4 — v00.99.41: scripts ↔ service AmberTools pipeline unification.

Verifies that the standalone subprocess pipeline that used to live in
``scripts/generate_gaff2_artifact.py`` and
``scripts/batch_generate_gaff2_artifacts.py`` has been removed; both
scripts now forward into ``features.molecules.artifact_service`` so the
CLI and the API never call AmberTools through divergent code paths.

Also covers the new ``generation_profile`` parameter on
``generate_gaff2_artifact`` (baseline / sqm_robust) — Phase 4 only ships
the API surface; Phase 5 wires the admin retry policy.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from features.molecules.artifact_service import (
    SUPPORTED_GENERATION_PROFILES,
    generate_gaff2_artifact,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# scripts/ is not a package (src/scripts shadows it on sys.path) — load the
# CLI module directly from its path, same pattern as
# test_cleanup_orphan_experiment_refs.py.
_CLI_PATH = REPO_ROOT / "scripts" / "generate_gaff2_artifact.py"
_CLI_SPEC = importlib.util.spec_from_file_location(
    "generate_gaff2_artifact_cli_test_module", _CLI_PATH
)
assert _CLI_SPEC and _CLI_SPEC.loader
cli = importlib.util.module_from_spec(_CLI_SPEC)
_CLI_SPEC.loader.exec_module(cli)
SCRIPT_PATHS = [
    REPO_ROOT / "scripts" / "generate_gaff2_artifact.py",
    REPO_ROOT / "scripts" / "batch_generate_gaff2_artifacts.py",
]

# Banned subprocess invocations: scripts must not call AmberTools directly.
_BANNED_TOOLS = ("antechamber", "parmchk2", "tleap")


class TestNoStandaloneAmberToolsPipeline:
    """Each script must delegate to artifact_service rather than wrapping
    subprocess calls itself."""

    @pytest.mark.parametrize("script_path", SCRIPT_PATHS)
    def test_script_does_not_invoke_ambertools_directly(self, script_path: Path) -> None:
        text = script_path.read_text()
        # subprocess.run([... "antechamber"...) or similar
        for tool in _BANNED_TOOLS:
            pattern = re.compile(
                rf"subprocess\.(run|Popen|check_call|check_output)\([^)]*\b{tool}\b",
                re.DOTALL,
            )
            assert not pattern.search(text), (
                f"{script_path.name} still calls {tool} via subprocess directly. "
                "Phase 4 requires routing all AmberTools invocation through "
                "features.molecules.artifact_service."
            )

    @pytest.mark.parametrize("script_path", SCRIPT_PATHS)
    def test_script_imports_artifact_service(self, script_path: Path) -> None:
        text = script_path.read_text()
        # Either direct import OR the deprecated wrapper that re-execs into the
        # canonical CLI is acceptable.
        if script_path.name == "batch_generate_gaff2_artifacts.py":
            # Deprecated wrapper: must forward to generate_gaff2_artifact.py.
            assert "generate_gaff2_artifact.py" in text
            assert "os.execv" in text or "subprocess.run" in text or "import" in text
            return
        assert "from features.molecules.artifact_service" in text


class TestGenerationProfileApi:
    """``generate_gaff2_artifact`` exposes a ``generation_profile`` kwarg."""

    def test_supported_profiles_contains_baseline_and_sqm_robust(self):
        assert "baseline" in SUPPORTED_GENERATION_PROFILES
        assert "sqm_robust" in SUPPORTED_GENERATION_PROFILES

    def test_unknown_profile_rejected(self, tmp_path: Path):
        dummy = tmp_path / "x.mol"
        dummy.write_text("")
        with pytest.raises(ValueError, match="generation_profile"):
            generate_gaff2_artifact(
                mol_path=dummy,
                mol_id="Toluene",
                generation_profile="aggressive",
            )

    def test_passthrough_short_circuits_before_profile_validation(self, tmp_path: Path):
        """passthrough rejection happens after profile validation but before
        AmberTools — so a valid profile + passthrough mol still fails fast
        with PASSTHROUGH_UNSUPPORTED, not ValueError.

        The catalog no longer carries passthrough entries (carbon
        allotropes moved to organic_gaff2 + fragment fallback, v01.00.12+),
        so the passthrough mode is injected through the explicit
        ``ff_assignment.parameterization`` channel of the resolver.
        """
        from features.molecules.exceptions import (
            ArtifactFailureCode,
            ArtifactGenerationError,
        )

        dummy = tmp_path / "Carbon_Nano_Tube.mol"
        dummy.write_text("")
        with pytest.raises(ArtifactGenerationError) as exc_info:
            generate_gaff2_artifact(
                mol_path=dummy,
                mol_id="Carbon_Nano_Tube",
                generation_profile="sqm_robust",
                ff_assignment={
                    "route": "organic_curated_artifact",
                    "source_id": "Carbon_Nano_Tube",
                    "parameterization": {"mode": "organic_gaff2_passthrough"},
                },
            )
        assert exc_info.value.failure_code == ArtifactFailureCode.PASSTHROUGH_UNSUPPORTED


class TestSqmRobustOptionFidelity:
    """sqm_robust must inject the documented -ek convergence options.

    The exact option string is operator-facing (admin retry policy in
    Phase 5 and the FF Parameters page), so any drift here changes the
    science of the retry. Pin it character-for-character.
    """

    EXPECTED_EK_STRING = (
        "vshift=0.1, scfconv=1.0d-9, itrmax=500, maxcyc=2000, "
        "ndiis_attempts=200, ndiis_matrices=6, tight_p_conv=0, "
        "pseudo_diag=1, grms_tol=0.0005"
    )

    def test_baseline_does_not_inject_ek(self, tmp_path: Path, monkeypatch):
        from features.molecules import artifact_service
        from features.molecules.exceptions import ArtifactGenerationError

        # Force the path-existence check to pass.
        dummy = tmp_path / "Toluene.mol"
        dummy.write_text("mock mol")

        captured: dict[str, list[str]] = {}

        def _fake_run(cmd, **kwargs):
            captured.setdefault("cmds", []).append(list(cmd))
            # Stop after antechamber stage. RuntimeError from the subprocess
            # runner is wrapped by the service into ArtifactGenerationError.
            raise RuntimeError("stop after antechamber")

        monkeypatch.setattr(
            artifact_service,
            "_run_subprocess_with_group_kill",
            _fake_run,
        )
        with pytest.raises(ArtifactGenerationError):
            artifact_service.generate_gaff2_artifact(
                mol_path=dummy,
                mol_id="Toluene",
                generation_profile="baseline",
            )
        assert captured["cmds"], "antechamber must have been invoked once"
        first = captured["cmds"][0]
        assert "-ek" not in first

    def test_sqm_robust_injects_exact_ek_string(self, tmp_path: Path, monkeypatch):
        from features.molecules import artifact_service
        from features.molecules.exceptions import ArtifactGenerationError

        dummy = tmp_path / "Toluene.mol"
        dummy.write_text("mock mol")

        captured: dict[str, list[str]] = {}

        def _fake_run(cmd, **kwargs):
            captured.setdefault("cmds", []).append(list(cmd))
            raise RuntimeError("stop after antechamber")

        monkeypatch.setattr(
            artifact_service,
            "_run_subprocess_with_group_kill",
            _fake_run,
        )
        with pytest.raises(ArtifactGenerationError):
            artifact_service.generate_gaff2_artifact(
                mol_path=dummy,
                mol_id="Toluene",
                generation_profile="sqm_robust",
            )

        cmd = captured["cmds"][0]
        assert "-ek" in cmd, "sqm_robust must add -ek to antechamber"
        ek_idx = cmd.index("-ek")
        assert cmd[ek_idx + 1] == self.EXPECTED_EK_STRING


class TestCliEntryPoints:
    """CLI parses flags without invoking AmberTools when --diagnose-only
    or --dry-run is given."""

    def test_batch_sqm_robust_filters_to_eligible_rows_only(
        self, monkeypatch, tmp_path, capsys
    ) -> None:
        """v00.99.42 — `batch --profile sqm_robust` must only queue rows
        whose latest sidecar failure_code is sqm_timeout / sqm_nonconverged.
        Other rows must be reported as `admin_policy_blocked` and never
        forwarded to the worker.
        """
        from features.molecules import artifact_service
        from features.molecules.admin_status import AdminStatusStore
        from features.molecules.exceptions import (
            ArtifactFailureCode,
            ArtifactGenerationError,
        )

        monkeypatch.setenv("ASPHALT_ANTECHAMBER_ADMIN", "1")
        monkeypatch.setattr(artifact_service, "ARTIFACT_DIR", tmp_path)

        # Two pending rows: only "Toluene" has prior sqm_timeout sidecar.
        AdminStatusStore(tmp_path).record_failure(
            "Toluene",
            ArtifactGenerationError(
                stage="antechamber",
                failure_code=ArtifactFailureCode.SQM_TIMEOUT,
            ),
        )

        def _fake_pending():
            return [
                {
                    "mol_id": "Toluene",
                    "source_id": "Toluene",
                    "is_complete": False,
                    "artifact_type": "organic",
                    "atom_count": 15,
                    "consumer_ids": ["Toluene"],
                },
                {
                    "mol_id": "Methanol",
                    "source_id": "Methanol",
                    "is_complete": False,
                    "artifact_type": "organic",
                    "atom_count": 6,
                    "consumer_ids": ["Methanol"],
                },
            ]

        monkeypatch.setattr(artifact_service, "get_pending_molecules", _fake_pending)

        captured_pending: dict[str, list[dict]] = {}

        def _fake_run_parallel_batch(pending, max_workers=None, **kwargs):
            captured_pending["pending"] = list(pending)
            return {
                "total": len(pending),
                "success": len(pending),
                "failed": 0,
                "skipped": 0,
                "cancelled": False,
                "details": [],
                "max_workers": max_workers or 1,
            }

        monkeypatch.setattr(artifact_service, "run_parallel_batch", _fake_run_parallel_batch)
        monkeypatch.setattr(
            "sys.argv",
            [
                "generate_gaff2_artifact.py",
                "--profile",
                "sqm_robust",
                "batch",
                "--workers",
                "1",
            ],
        )
        monkeypatch.setattr(cli, "_check_tools", lambda: None)
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 0

        # Only Toluene must reach the worker; Methanol skipped at gating.
        forwarded = captured_pending.get("pending") or []
        assert {row["mol_id"] for row in forwarded} == {"Toluene"}

        out = capsys.readouterr().out
        assert "admin_policy_blocked" in out
        assert "Methanol" in out

    def test_single_diagnose_only_does_not_require_ambertools(self, monkeypatch, capsys) -> None:
        monkeypatch.setenv("ASPHALT_ANTECHAMBER_ADMIN", "1")
        monkeypatch.setattr(
            "sys.argv",
            ["generate_gaff2_artifact.py", "single", "--mol-id", "Toluene", "--diagnose-only"],
        )
        # Must not call _check_tools (which would fail in CI without AmberTools).
        called_check_tools = {"v": False}

        def _fake_check_tools() -> None:
            called_check_tools["v"] = True

        monkeypatch.setattr(cli, "_check_tools", _fake_check_tools)

        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 0
        assert called_check_tools["v"] is False, (
            "--diagnose-only must skip AmberTools availability check"
        )
        captured = capsys.readouterr()
        assert "source_id" in captured.out
        assert "Toluene" in captured.out
