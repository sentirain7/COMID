"""역설계 batch 조성 SSOT 경로의 실빌드 packmol 실측 (§5 검증).

_submit_binder_cell이 쓰는 _batch_binder_composition(YAML SSOT + 첨가제 주입)
→ create_build_request(initial_density=None, batch 기본) → StructureBuilder
경로를 그대로 타서 packmol 단계만 시간 측정한다. batch 기본값(density 0.5,
PACKMOL_TIMEOUT_S 기본 1200s)으로 1200s 내 수렴하는지가 핵심 확인점.

환경:
  BENCH_ADDITIVE   첨가제 mol_id (기본 없음). 예: SBS_3_7
  BENCH_ADDITIVE_WT 첨가제 wt% (기본 5.0)
  BENCH_BINDER     binder_type (기본 AAA1)
  PACKMOL_TIMEOUT_S PackmolWrapper가 직접 읽음 (기본 1200)
"""

import os
import tempfile
import time
from pathlib import Path

from builder.molecule_db_loader import create_molecule_db
from builder.structure_builder import StructureBuilder
from features.inverse_design_pipeline.execution import _batch_binder_composition
from orchestrator.request_factory import create_build_request

BINDER = os.environ.get("BENCH_BINDER", "AAA1")
ADDITIVE = os.environ.get("BENCH_ADDITIVE") or None
ADDITIVE_WT = float(os.environ.get("BENCH_ADDITIVE_WT", "5.0"))


def main() -> int:
    mol_counts, sara = _batch_binder_composition(
        binder_type=BINDER,
        additive_mol_id=ADDITIVE,
        additive_wt=ADDITIVE_WT if ADDITIVE else 0.0,
        temperature_k=293.0,
    )
    print(
        f"[bench] {BINDER}"
        + (f"+{ADDITIVE}@{ADDITIVE_WT}wt%" if ADDITIVE else " (무첨가)")
        + f": {len(mol_counts)}종 {sum(int(v) for v in mol_counts.values())}분자",
        flush=True,
    )

    req = create_build_request(
        composition={k: float(v) for k, v in mol_counts.items()},
        composition_mode="mol_count",
        seed=42,
        tier="screening",
        initial_density=None,  # batch 기본 (BuildRequest 기본 밀도)
    )

    db = create_molecule_db(allow_mock=True)
    work_dir = Path(tempfile.mkdtemp(prefix="invbatch_"))
    builder = StructureBuilder(molecule_db=db, work_dir=work_dir)
    print(
        f"[bench] mol_count density(batch기본) timeout={builder.packmol.timeout}s "
        f"tolerance={builder.packmol.tolerance}",
        flush=True,
    )

    orig = builder.packmol.pack
    cap: dict = {}

    def timed(*a, **k):
        t0 = time.monotonic()
        r = orig(*a, **k)
        cap.update(dt=time.monotonic() - t0, success=r.success)
        print(
            f"[bench] RESULT {BINDER}{'+' + ADDITIVE if ADDITIVE else ''} "
            f"dt={cap['dt']:.1f}s success={r.success} box={r.box_dimensions} "
            f"err={r.error_message}",
            flush=True,
        )
        raise SystemExit(0)

    builder.packmol.pack = timed
    try:
        builder.build(req)
    except SystemExit:
        pass
    return 0 if cap.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
