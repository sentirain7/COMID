"""역설계 파이프라인 실(實) E2E smoke 드라이버.

BOOTSTRAP 콜드스타트 1사이클을 실제 LAMMPS로 실증한다:
  preview_plan(시드 N개) → plan 다운스케일(entry 오버라이드: target_atoms·
  stage_duration) → approve_and_run(실제 제출) → 완료 폴링 → get_results.

전제: Redis + Celery worker(simulation.screening 큐) 가동,
LAMMPS_EXECUTABLE 설정. 물성 정확도 검증이 아니라 "전 구간이 실제로
도는가"의 검증이다 (Level 4 smoke 철학).

사용:
  PYTHONPATH=src:packages python scripts/run_inverse_pipeline_smoke.py \
      [--seeds 2] [--atoms 3000] [--nvt-ps 20] [--npt-ps 30] [--no-submit]
"""

import argparse
import asyncio
import json
import sys
import time

from contracts.policies.inverse_pipeline import (
    DEFAULT_INVERSE_PIPELINE_POLICY,
    ColdStartPolicy,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=2, help="BOOTSTRAP 시드 후보 수")
    parser.add_argument("--atoms", type=int, default=3000, help="binder cell 원자 수")
    parser.add_argument("--nvt-ps", type=float, default=20.0)
    parser.add_argument("--npt-ps", type=float, default=30.0)
    parser.add_argument(
        "--initial-density",
        type=float,
        default=0.35,
        help="초기 패킹 밀도 (작은 셀은 낮춰야 Packmol 수렴이 빠름)",
    )
    parser.add_argument("--poll-s", type=float, default=20.0, help="상태 폴링 간격(초)")
    parser.add_argument("--timeout-min", type=float, default=90.0, help="전체 타임아웃(분)")
    parser.add_argument("--no-submit", action="store_true", help="계획 미리보기까지만 (제출 없음)")
    return parser.parse_args()


def build_smoke_policy(n_seeds: int):
    """시드 수만 줄인 정책 — preview/approve 양쪽에 동일하게 전달(스냅샷 일치)."""
    return DEFAULT_INVERSE_PIPELINE_POLICY.model_copy(
        update={
            "cold_start": ColdStartPolicy(
                n_min_labels=DEFAULT_INVERSE_PIPELINE_POLICY.cold_start.n_min_labels,
                seed_batch_size=n_seeds,
                seed_rng_seed=DEFAULT_INVERSE_PIPELINE_POLICY.cold_start.seed_rng_seed,
            )
        }
    )


def downscale_plan(
    plan: dict, *, atoms: int, nvt_ps: float, npt_ps: float, initial_density: float | None = None
) -> dict:
    """plan 문서를 smoke 규모로 다운스케일하고 그대로 반환 (해시는 호출자가 재계산).

    plan 문서는 클라이언트 소유(§4.6) — 수정 후 재해시는 변조가 아니라
    명시적 사용자 결정이며 approve는 회신된 문서 기준으로 실행한다.
    """
    overrides = [
        {"stage_name": "nvt_equilibration", "duration_ps": nvt_ps},
        {"stage_name": "npt_production", "duration_ps": npt_ps},
    ]
    for entry in plan.get("experiments", []):
        if entry.get("kind") == "binder_cell":
            entry["target_atoms"] = atoms
            entry["stage_duration_overrides"] = overrides
            if initial_density:
                entry["initial_density"] = initial_density
    return plan


async def main() -> int:
    args = parse_args()

    from api.schemas import InverseDesignRequest
    from api.schemas.recommendations import PropertyTargetItem
    from features.inverse_design_pipeline import service
    from features.inverse_design_pipeline.execution import approve_and_run
    from features.inverse_design_pipeline.results import get_results

    policy = build_smoke_policy(args.seeds)

    request = InverseDesignRequest(
        custom_targets=[
            PropertyTargetItem(metric_name="density", target_min=0.95, direction="maximize")
        ],
        temperature_k_fixed=293.0,
    )

    print(f"[1/4] preview_plan — BOOTSTRAP 시드 {args.seeds}개 기대")
    preview = await service.preview_plan(request, policy=policy)
    plan = preview["plan"]
    print(
        f"      mode={plan['mode']} candidates={len(plan['candidates'])} "
        f"experiments={len(plan['experiments'])}"
    )
    if plan["mode"] != "bootstrap":
        print("      주의: BO 모드로 판정됨 (champion 존재) — smoke는 계속 진행")

    plan = downscale_plan(
        plan,
        atoms=args.atoms,
        nvt_ps=args.nvt_ps,
        npt_ps=args.npt_ps,
        initial_density=args.initial_density,
    )
    plan_hash = service.compute_plan_hash(plan)
    print(
        f"[2/4] 다운스케일 완료 — atoms={args.atoms}, "
        f"nvt={args.nvt_ps}ps, npt={args.npt_ps}ps, hash={plan_hash}"
    )

    for entry in plan["experiments"]:
        candidate = plan["candidates"][entry["candidate_index"]]
        comp = candidate.get("composition", {})
        sara = "/".join(f"{comp.get(k, 0.0):.1f}" for k in ("asphaltene", "resin", "aromatic", "saturate"))
        binder = candidate.get("binder_type", "?")
        preset = entry.get("protocol_preset", "?")
        size = entry.get("structure_size", "?")
        print(
            f"      {entry['plan_exp_id']} {entry['kind']} T={entry['temperature_k']}K "
            f"binder={binder} {size} preset={preset} action={entry['action']} SARA={sara}"
        )

    if args.no_submit:
        print("[--no-submit] 제출 생략 — dry-run 종료")
        return 0

    print("[3/4] approve_and_run — 실제 제출")
    approval = approve_and_run(plan, plan_hash, policy=policy)
    pipeline_id = approval["pipeline_id"]
    print(f"      pipeline_id={pipeline_id} counts={approval['counts']}")
    for member in approval["members"]:
        print(
            f"      {member['plan_exp_id']}: {member['action']} → {member.get('exp_id')}"
            + (f" [오류: {member.get('error')}]" if member.get("error") else "")
        )
    if approval["counts"].get("error"):
        print("      제출 오류 존재 — 진행하되 결과 확인 필요")
    if not any(m["action"] == "submitted" for m in approval["members"]):
        print("      제출된 실험이 없어 종료")
        return 1

    print(f"[4/4] 완료 폴링 (간격 {args.poll_s}s, 타임아웃 {args.timeout_min}min)")
    from features.inverse_design_pipeline.execution import get_progress

    terminal = {"completed", "failed", "cancelled", "timeout"}
    deadline = time.monotonic() + args.timeout_min * 60.0
    while True:
        progress = get_progress(pipeline_id)
        counts = progress["status_counts"]
        print(f"      [{time.strftime('%H:%M:%S')}] {counts}")
        if progress["total"] > 0 and all(
            m["effective_status"] in terminal for m in progress["members"]
        ):
            break
        if time.monotonic() > deadline:
            print("      타임아웃 — 현재 상태로 결과 출력")
            break
        time.sleep(args.poll_s)

    results = get_results(pipeline_id, policy=policy)
    print("\n==== RESULTS ====")
    print(
        json.dumps(
            {
                "pipeline_id": results["pipeline_id"],
                "completed": f"{results['completed_experiments']}/{results['total_experiments']}",
                "candidates": [
                    {
                        "candidate_index": c["candidate_index"],
                        "per_target": c["per_target"],
                        "targets_satisfied": c["targets_satisfied"],
                    }
                    for c in results["candidates"]
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    ok = results["completed_experiments"] > 0
    print("\nSMOKE", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
