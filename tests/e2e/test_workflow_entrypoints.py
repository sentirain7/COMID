"""E2E Level 0: 시작 진입점 계약 매트릭스 (docs/WORKFLOW_VERIFICATION_PLAN.md §6 Level 0, §8).

13개 시작 진입점 각각에 대해

  (a) 최소 정상 요청  → 2xx 수락 또는 정책상 명확한 거절(blocked/no_gaps 등)
  (b) 음성 케이스      → 잘못된 입력으로 422/400

을 거는 라우트 존재성 + 최소 계약 검증이다. enum / 기본 온도는
``contracts/policies/temperature.py`` SSOT 를 따른다.

검증 대상 진입점 (실제 라우트):
 1. POST /experiments
 2. POST /experiments/single-molecule/batch
 3. POST /batch-job/binder-cell  (+ /batch-job/binder-cell/validate)
 4. POST /layered-structures/preview
 5. POST /layered-structures/submit
 6. POST /interface-molecule-cells
 7. POST /interface-molecule-cells/batch-generate-async   (실제: -async, 202)
 8. POST /crystal-structures
 9. POST /crystal-structures/batch-generate
10. POST /amorphous-cells
11. POST /campaigns/waves/submit
12. POST /additive-coverage/generate-wave

이미 tests/api/ 와 기존 e2e 가 잘 커버하는 진입점(crystal/amorphous/layered/batch/
campaign)은 라우트 존재 + 최소 계약만 가볍게 확인하고, 미커버 진입점(single-molecule
batch, interface 단건, additive-coverage)은 더 꼼꼼히 본다.

Mock 경계: Celery/GPU 제출(``api.deps.get_job_manager``), dashboard GPU 조회,
single-molecule FF/mol lookup, interface packmol/topology 만 mock. 라우터 → service
→ repository → SQLite 는 전부 실제로 탄다. LAMMPS / Celery worker / packmol /
antechamber 바이너리 없이 통과한다.

공통 fixture(``e2e_client``, 대표 상수)는 ``tests/e2e/conftest.py`` 에서 가져온다.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.e2e.conftest import (
    FF_TYPE,
    SAMPLE_TEMPERATURES_K,
)

# Valid minimal bulk-experiment composition (sums to 1.0).
_VALID_COMPOSITION = {
    "asphaltene_wt": 0.2,
    "resin_wt": 0.3,
    "aromatic_wt": 0.35,
    "saturate_wt": 0.15,
}


def _write_minimal_data_file(path: Path, *, lx: float, ly: float, lz: float) -> None:
    """2-atom full-style LAMMPS data file (interface topology mock 출력용)."""
    lines = [
        "LAMMPS data file - entrypoint test",
        "",
        "2 atoms",
        "0 bonds",
        "0 angles",
        "0 dihedrals",
        "0 impropers",
        "",
        "1 atom types",
        "0 bond types",
        "0 angle types",
        "0 dihedral types",
        "0 improper types",
        "",
        f"0.0 {lx:.6f} xlo xhi",
        f"0.0 {ly:.6f} ylo yhi",
        f"0.0 {lz:.6f} zlo zhi",
        "",
        "Masses",
        "",
        "1 12.011 # C",
        "",
        "Atoms # full",
        "",
        f"1 1 1 0.0 {lx * 0.25:.3f} {ly * 0.25:.3f} {lz * 0.5:.3f}",
        f"2 1 1 0.0 {lx * 0.75:.3f} {ly * 0.75:.3f} {lz * 0.5:.3f}",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _no_ff_block():
    """FF eligibility gate 를 통과(unblocked)시키는 patch context."""
    return patch(
        "forcefield.eligibility.collect_binder_ff_issues",
        return_value={"blocked_items": [], "warning_items": [], "has_blocked": False},
    )


async def _fake_precompute(_request):
    """antechamber typing/charge 경계 mock (성공 응답)."""
    return SimpleNamespace(failed=0, cached=0, computed=1, details=[])


async def _fake_submit_molecule_experiment(_request, **kwargs):
    """MD 안정화 제출 경계 mock: exp_id_override 보존."""
    exp_id = kwargs.get("exp_id_override") or "amor_exp_entrypoint_fallback"
    return SimpleNamespace(exp_id=exp_id, job_id="job-amorphous-001", status="queued")


class TestWorkflowEntrypoints:
    """Level 0 — 13 진입점 × (정상 2xx / 음성 422·400) 매트릭스."""

    # ==================================================================
    # 1. POST /experiments  (bulk single experiment)
    # ==================================================================

    def test_experiments_minimal_accepts(self, e2e_client):
        resp = e2e_client.post(
            "/experiments",
            json={
                "composition": _VALID_COMPOSITION,
                "target_atoms": 5000,
                "temperature_K": 293.0,
                "run_tier": "screening",
                "ff_type": FF_TYPE,
                "seed": 4242,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["exp_id"]
        assert body["status"] in {"queued", "pending"}
        assert e2e_client.fake_job_manager.submit_calls

    def test_experiments_rejects_invalid_temperature(self, e2e_client):
        # temperature_K below schema bound (ge=200) → 422.
        resp = e2e_client.post(
            "/experiments",
            json={"composition": _VALID_COMPOSITION, "temperature_K": -5.0},
        )
        assert resp.status_code == 422, resp.text

    def test_experiments_rejects_out_of_range_target_atoms(self, e2e_client):
        # target_atoms below ge=1000 → 422.
        resp = e2e_client.post(
            "/experiments",
            json={"composition": _VALID_COMPOSITION, "target_atoms": -10},
        )
        assert resp.status_code == 422, resp.text

    # ==================================================================
    # 2. POST /experiments/single-molecule/batch  (E_intra temp scan)
    # ==================================================================

    def _single_molecule_patches(self):
        """FF resolution(server SSOT) + mol lookup 경계 mock — DB 쓰기는 실제."""
        mol_db = SimpleNamespace(
            get=lambda _mol_id: SimpleNamespace(atom_count=42),
            get_temperature_code=lambda _config, _temp: "0293",
        )
        return (
            patch("api.deps.get_molecule_db", return_value=mol_db),
            patch(
                "features.molecules.catalog.resolve_ff_hint",
                return_value={
                    "submit_ff_type": FF_TYPE,
                    "is_submittable": True,
                    "blocked_reason": None,
                    "ff_hint": "gaff2",
                    "ff_display_label": "GAFF2",
                },
            ),
        )

    def test_single_molecule_batch_minimal_accepts(self, e2e_client):
        temps = list(SAMPLE_TEMPERATURES_K)
        mol_db_patch, ff_patch = self._single_molecule_patches()
        with mol_db_patch, ff_patch:
            resp = e2e_client.post(
                "/experiments/single-molecule/batch",
                json={
                    "selected_mol_id": "U-AS-Thio",
                    "temperatures_k": temps,
                    "ff_type": FF_TYPE,
                    "force_recompute": False,
                },
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # 실제 규칙: 온도당 정확히 1 제출.
        assert body["total"] == len(temps)
        assert body["submitted"] == len(temps), body
        assert {it["temperature_K"] for it in body["items"]} == set(temps)

    def test_single_molecule_batch_rejects_empty_mol_id(self, e2e_client):
        # selected_mol_id min_length=1 → 빈 문자열은 422.
        resp = e2e_client.post(
            "/experiments/single-molecule/batch",
            json={"selected_mol_id": "", "temperatures_k": [293.0]},
        )
        assert resp.status_code == 422, resp.text

    def test_single_molecule_batch_rejects_missing_mol_id(self, e2e_client):
        # selected_mol_id 필수 → 누락 시 422.
        resp = e2e_client.post(
            "/experiments/single-molecule/batch",
            json={"temperatures_k": [293.0]},
        )
        assert resp.status_code == 422, resp.text

    # ==================================================================
    # 3. POST /batch-job/binder-cell  (+ /validate)
    # ==================================================================

    def test_batch_binder_cell_validate_minimal_accepts(self, e2e_client):
        # validate 는 dry-run (DB 쓰기 없음) — 라우트 존재 + 조합 카운트만 확인.
        payload = {
            "binder_types": ["AAA1", "AAK1"],
            "structure_sizes": ["X1"],
            "temperatures_k": [293.0, 313.0],
            "aging_states": ["non_aging"],
            "tier": "screening",
            "ff_type": FF_TYPE,
            "seed": 7777,
            "similar_existing_action": "unspecified",
        }
        with _no_ff_block():
            resp = e2e_client.post("/batch-job/binder-cell/validate", json=payload)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 4, body  # 2 binder × 2 temp

    def test_batch_binder_cell_minimal_accepts(self, e2e_client):
        payload = {
            "binder_types": ["AAA1"],
            "structure_sizes": ["X1"],
            "temperatures_k": [293.0],
            "aging_states": ["non_aging"],
            "tier": "screening",
            "ff_type": FF_TYPE,
            "seed": 7778,
            "similar_existing_action": "unspecified",
        }
        with _no_ff_block():
            resp = e2e_client.post("/batch-job/binder-cell", json=payload)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 1
        assert body["submitted"] == 1, body

    def test_batch_binder_cell_rejects_invalid_tier(self, e2e_client):
        # tier 는 RunTier enum — 잘못된 값은 422.
        resp = e2e_client.post(
            "/batch-job/binder-cell",
            json={
                "binder_types": ["AAA1"],
                "temperatures_k": [293.0],
                "tier": "__not_a_tier__",
            },
        )
        assert resp.status_code == 422, resp.text

    def test_batch_binder_cell_rejects_missing_binder_types(self, e2e_client):
        # binder_types 필수 → 누락 시 422.
        resp = e2e_client.post(
            "/batch-job/binder-cell",
            json={"temperatures_k": [293.0]},
        )
        assert resp.status_code == 422, resp.text

    # ==================================================================
    # 4. POST /layered-structures/preview
    # ==================================================================

    def test_layered_preview_unknown_sources_returns_404(self, e2e_client):
        # 존재하지 않는 source id → 404 + E7001 (정책상 명확한 거절).
        resp = e2e_client.post(
            "/layered-structures/preview",
            json={
                "layers": [
                    {"source_type": "amorphous_cell", "source_id": "amor_nope"},
                    {"source_type": "crystal_structure", "source_id": "crys_nope"},
                ],
            },
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["code"] == "E7001"

    def test_layered_preview_rejects_invalid_source_type(self, e2e_client):
        # source_type 은 LayerSourceType enum — 잘못된 값은 422.
        resp = e2e_client.post(
            "/layered-structures/preview",
            json={"layers": [{"source_type": "__bogus__", "source_id": "x"}]},
        )
        assert resp.status_code == 422, resp.text

    # ==================================================================
    # 5. POST /layered-structures/submit
    # ==================================================================

    def test_layered_submit_unknown_sources_returns_404(self, e2e_client):
        # submit 도 source 해석 단계에서 404 거절 (라우트 존재 + 계약).
        resp = e2e_client.post(
            "/layered-structures/submit",
            json={
                "layers": [
                    {"source_type": "amorphous_cell", "source_id": "amor_nope"},
                    {"source_type": "crystal_structure", "source_id": "crys_nope"},
                ],
                "name": "EntrypointLayered",
                "run_tier": "screening",
                "ff_type": FF_TYPE,
                "temperature_K": 298.0,
                "seed": 21,
            },
        )
        assert resp.status_code == 404, resp.text

    def test_layered_submit_rejects_empty_layers(self, e2e_client):
        # 빈 layers → 422 (min layers 정책).
        resp = e2e_client.post(
            "/layered-structures/submit",
            json={
                "layers": [],
                "run_tier": "screening",
                "ff_type": FF_TYPE,
                "temperature_K": 298.0,
            },
        )
        assert resp.status_code == 422, resp.text

    # ==================================================================
    # 6. POST /interface-molecule-cells  (single create)
    # ==================================================================

    def _interface_create_patches(self, monkeypatch):
        """Packmol 바이너리 + GAFF2 토폴로지 경계 mock (외부 도구)."""
        from builder.packmol_wrapper import PackmolResult, PackmolWrapper

        def _fake_pack(
            _self, molecules, output_file, total_mass_g_mol, box_dimensions, work_dir, **_kw
        ):
            bx, by, bz = box_dimensions
            lines = ["3", "mock packed interface cell"]
            for frac in (0.3, 0.5, 0.7):
                lines.append(f"O {bx * frac:.4f} {by * frac:.4f} {bz * 0.5:.4f}")
            Path(output_file).write_text("\n".join(lines) + "\n", encoding="utf-8")
            return PackmolResult(
                success=True,
                output_file=Path(output_file),
                log="mock packmol",
                box_dimensions=box_dimensions,
            )

        def _fake_topology(
            _mol_path,
            _mol_id,
            _molecule_count,
            _packed_xyz_path,
            output_data_path,
            box_dimensions,
            *_args,
            **_kwargs,
        ):
            _write_minimal_data_file(
                Path(output_data_path),
                lx=float(box_dimensions[0]),
                ly=float(box_dimensions[1]),
                lz=float(box_dimensions[2]),
            )
            return Path(output_data_path)

        monkeypatch.setattr(PackmolWrapper, "pack", _fake_pack)
        monkeypatch.setattr(
            "builder.topology_helpers.generate_single_component_topology",
            _fake_topology,
        )

    def test_interface_cell_minimal_accepts(self, e2e_client, monkeypatch):
        self._interface_create_patches(monkeypatch)
        resp = e2e_client.post(
            "/interface-molecule-cells",
            json={
                "name": "EntrypointWaterFilm",
                "mol_id": "H2O",
                "lx_angstrom": 30.0,
                "ly_angstrom": 30.0,
                "lz_angstrom": 10.0,
                "target_density": 0.5,
                "boundary_mode": "ppf",
                "seed": 7,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["cell_id"].startswith("ifc_")
        assert body["status"] == "ready"
        assert body["mol_id"] == "H2O"

    def test_interface_cell_rejects_missing_mol_id(self, e2e_client):
        # mol_id 필수(min_length=1) → 누락 시 422.
        resp = e2e_client.post(
            "/interface-molecule-cells",
            json={
                "name": "NoMol",
                "lx_angstrom": 30.0,
                "ly_angstrom": 30.0,
                "lz_angstrom": 10.0,
                "target_density": 0.5,
                "boundary_mode": "ppf",
            },
        )
        assert resp.status_code == 422, resp.text

    def test_interface_cell_rejects_nonpositive_box(self, e2e_client):
        # lx_angstrom gt=0 → 음수/0 은 422.
        resp = e2e_client.post(
            "/interface-molecule-cells",
            json={
                "name": "NegBox",
                "mol_id": "H2O",
                "lx_angstrom": -10.0,
                "ly_angstrom": 30.0,
                "lz_angstrom": 10.0,
                "target_density": 0.5,
            },
        )
        assert resp.status_code == 422, resp.text

    # ==================================================================
    # 7. POST /interface-molecule-cells/batch-generate-async  (202)
    # ==================================================================

    def test_interface_batch_generate_async_accepts(self, e2e_client):
        # 비동기 배치: 즉시 202 + batch_id (worker 는 background, 실행 안 탐).
        resp = e2e_client.post(
            "/interface-molecule-cells/batch-generate-async",
            json={
                "mol_id": "H2O",
                "xy_min": 30.0,
                "xy_max": 40.0,
                "lz_angstrom": 10.0,
                "target_density": 0.5,
                "boundary_mode": "ppf",
            },
        )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["status"] == "accepted"
        assert body["batch_id"]
        assert body["poll_url"].endswith(body["batch_id"])

    def test_interface_batch_generate_async_rejects_bad_xy_range(self, e2e_client):
        # xy_max < xy_min → model_validator 422.
        resp = e2e_client.post(
            "/interface-molecule-cells/batch-generate-async",
            json={
                "mol_id": "H2O",
                "xy_min": 50.0,
                "xy_max": 30.0,
                "target_density": 0.5,
            },
        )
        assert resp.status_code == 422, resp.text

    # ==================================================================
    # 8. POST /crystal-structures  (single create)
    # ==================================================================

    def test_crystal_structure_minimal_accepts(self, e2e_client):
        resp = e2e_client.post(
            "/crystal-structures",
            json={
                "name": "EntrypointQuartz",
                "source_type": "preset",
                "material": "SiO2",
                "surface": "001",
                "thickness_angstrom": 8.0,
                "xy_size_angstrom": 12.0,
                "nx": 1,
                "ny": 1,
                "nz": 1,
                "hydroxylated": False,
                "hydroxyl_density": 4.6,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["crystal_id"].startswith("crys_")
        assert body["atom_count"] > 0

    def test_crystal_structure_rejects_invalid_material(self, e2e_client):
        # material 은 CrystalMaterial enum → 잘못된 값은 422.
        resp = e2e_client.post(
            "/crystal-structures",
            json={
                "name": "BadMaterial",
                "source_type": "preset",
                "material": "__unobtainium__",
                "surface": "001",
            },
        )
        assert resp.status_code == 422, resp.text

    # ==================================================================
    # 9. POST /crystal-structures/batch-generate
    # ==================================================================

    def test_crystal_batch_generate_minimal_accepts(self, e2e_client):
        # 동기 배치(deprecated 이지만 활성 라우트) — supercell 묶음 생성.
        resp = e2e_client.post(
            "/crystal-structures/batch-generate",
            json={
                "material": "SiO2",
                "surface": "001",
                "thickness_angstrom": 8.0,
                "xy_min": 12.0,
                "xy_max": 16.0,
                "hydroxylated": False,
                "hydroxyl_density": 4.6,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["material"] == "SiO2"
        assert body["generated_count"] >= 1

    def test_crystal_batch_generate_rejects_invalid_material(self, e2e_client):
        resp = e2e_client.post(
            "/crystal-structures/batch-generate",
            json={"material": "__nope__", "surface": "001"},
        )
        assert resp.status_code == 422, resp.text

    # ==================================================================
    # 10. POST /amorphous-cells
    # ==================================================================

    def test_amorphous_cell_minimal_accepts(self, e2e_client):
        # amorphous 안정화 제출 경계 mock (antechamber/MD) → queued 응답.
        with (
            patch(
                "features.amorphous_cells.service.precompute_typing_charge",
                _fake_precompute,
            ),
            patch(
                "features.amorphous_cells.service.submit_molecule_experiment",
                _fake_submit_molecule_experiment,
            ),
        ):
            resp = e2e_client.post(
                "/amorphous-cells",
                json={
                    "name": "EntrypointAmorphous",
                    "component_mol_id": "Ethanol",
                    "lx_angstrom": 30.0,
                    "ly_angstrom": 30.0,
                    "lz_angstrom": 12.0,
                    "initial_density": 0.8,
                    "boundary_mode": "ppf",
                    "ff_type": FF_TYPE,
                    "temperature_K": 298.0,
                    "seed": 11,
                },
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["amorphous_id"].startswith("amor_")
        assert body["status"] == "queued"
        assert body["stabilization_exp_id"]

    def test_amorphous_cell_rejects_nonpositive_box(self, e2e_client):
        resp = e2e_client.post(
            "/amorphous-cells",
            json={
                "component_mol_id": "Ethanol",
                "lx_angstrom": 0.0,
                "ly_angstrom": 30.0,
                "lz_angstrom": 12.0,
                "boundary_mode": "ppf",
            },
        )
        assert resp.status_code == 422, resp.text

    # ==================================================================
    # 11. POST /campaigns/waves/submit
    # ==================================================================

    def test_campaign_wave_submit_minimal_accepts(self, e2e_client):
        # wave 제출은 binder-cell batch 로 연결되므로 FF gate unblock + 단일 조합.
        with _no_ff_block():
            resp = e2e_client.post(
                "/campaigns/waves/submit",
                json={
                    "campaign_name": "entrypoint_pilot",
                    "wave_no": 1,
                    "binder_types": ["AAA1"],
                    "additive_types": [],
                    "additive_concentrations": [],
                },
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["wave_no"] == 1
        assert body["campaign_id"]

    def test_campaign_wave_submit_rejects_out_of_range_wave_no(self, e2e_client):
        # wave_no ge=1, le=4 → 0 또는 5 는 422.
        resp = e2e_client.post(
            "/campaigns/waves/submit",
            json={"campaign_name": "bad", "wave_no": 99},
        )
        assert resp.status_code == 422, resp.text

    def test_campaign_wave_submit_rejects_missing_wave_no(self, e2e_client):
        # wave_no 필수 → 누락 시 422.
        resp = e2e_client.post(
            "/campaigns/waves/submit",
            json={"campaign_name": "bad"},
        )
        assert resp.status_code == 422, resp.text

    # ==================================================================
    # 12. POST /additive-coverage/generate-wave
    # ==================================================================

    def test_additive_coverage_generate_wave_minimal_accepts(self, e2e_client):
        # auto_submit=False (default) → DB 쓰기/Celery 없이 planned/no_gaps 거절.
        resp = e2e_client.post(
            "/additive-coverage/generate-wave",
            json={"max_jobs": 3, "auto_submit": False},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # gap 이 있으면 planned, 없으면 no_gaps — 둘 다 명확한 정책 응답.
        assert body["status"] in {"planned", "no_gaps"}, body
        if body["status"] == "planned":
            assert body["estimated_jobs"] >= 0
            assert "spec" in body

    def test_additive_coverage_generate_wave_rejects_bad_type(self, e2e_client):
        # max_jobs 는 int — 비정수 문자열은 422.
        resp = e2e_client.post(
            "/additive-coverage/generate-wave",
            json={"max_jobs": "not_an_int"},
        )
        assert resp.status_code == 422, resp.text

    # ==================================================================
    # 13. POST /inverse-design/plan (역설계 파이프라인 dry-run, P3)
    # ==================================================================

    def test_inverse_pipeline_plan_minimal_accepts(self, e2e_client):
        # dry-run: champion 부재 + 라벨 0 → BOOTSTRAP 계획, 제출/DB 쓰기 없음.
        resp = e2e_client.post(
            "/inverse-design/plan",
            json={"custom_targets": [{"metric_name": "density", "target_min": 0.95}]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["plan_hash"]
        assert body["plan"]["mode"] in {"bootstrap", "bo"}
        assert body["plan"]["experiments"]

    def test_inverse_pipeline_plan_rejects_empty_targets(self, e2e_client):
        resp = e2e_client.post("/inverse-design/plan", json={"custom_targets": []})
        assert resp.status_code == 422, resp.text

    def test_inverse_pipeline_approve_rejects_tampered_plan(self, e2e_client):
        plan_resp = e2e_client.post(
            "/inverse-design/plan",
            json={"custom_targets": [{"metric_name": "density", "target_min": 0.95}]},
        ).json()
        tampered = dict(plan_resp["plan"])
        tampered["mode"] = "tampered"
        resp = e2e_client.post(
            "/inverse-design/plan/approve",
            json={"plan": tampered, "plan_hash": plan_resp["plan_hash"]},
        )
        assert resp.status_code == 400, resp.text
