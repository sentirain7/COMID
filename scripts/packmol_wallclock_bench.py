"""Packmol wall-clock 실측 벤치 (역설계 무첨가 wt% 경로 재현).

보고서 INVERSE_PIPELINE_E2E_SMOKE_FINDINGS §4의 실패 조건(SARA 대표분자,
target_atoms, initial_density)을 그대로 재현하되 packmol 단계만 시간 측정하고
직후 중단한다 (antechamber typing은 packmol 이후라 스킵 가능).

환경변수:
  BENCH_ATOMS   (default 3000)
  BENCH_DENSITY (default 0.5)
  PACKMOL_TIMEOUT_S (PackmolWrapper가 직접 읽음)

사용:
  source ~/anaconda3/etc/profile.d/conda.sh && conda activate asphalt_env
  PYTHONPATH=src:packages BENCH_DENSITY=0.5 python scripts/packmol_wallclock_bench.py
"""

import os
import tempfile
import time
from pathlib import Path

from builder.structure_builder import StructureBuilder
from orchestrator.request_factory import create_build_request

ATOMS = int(os.environ.get("BENCH_ATOMS", "3000"))
DENSITY = float(os.environ.get("BENCH_DENSITY", "0.5"))

# 대표적 AAA1-유사 SARA 조성 (합 100)
COMPOSITION = {"asphaltene": 15.0, "resin": 25.0, "aromatic": 35.0, "saturate": 25.0}


def main() -> int:
    req = create_build_request(
        composition=COMPOSITION,
        composition_mode="wt_percent",
        target_atoms=ATOMS,
        initial_density=DENSITY,
        seed=42,
    )
    work_dir = Path(tempfile.mkdtemp(prefix="packbench_"))
    builder = StructureBuilder(work_dir=work_dir)

    print(
        f"[bench] atoms={ATOMS} density={DENSITY} "
        f"packmol_timeout={builder.packmol.timeout}s tolerance={builder.packmol.tolerance} "
        f"maxit={builder.packmol.maxit} work_dir={work_dir}",
        flush=True,
    )

    orig_pack = builder.packmol.pack
    captured: dict = {}

    def timed_pack(*args, **kwargs):
        t0 = time.monotonic()
        result = orig_pack(*args, **kwargs)
        dt = time.monotonic() - t0
        captured.update(
            dt=dt,
            success=result.success,
            box=result.box_dimensions,
            err=result.error_message,
        )
        n_mol = sum(m.count for m in kwargs.get("molecules", args[0] if args else []))
        print(
            f"[bench] RESULT density={DENSITY} dt={dt:.1f}s success={result.success} "
            f"n_molecules={n_mol} box={result.box_dimensions} err={result.error_message}",
            flush=True,
        )
        # packmol 측정 완료 — 무거운 typing 단계 스킵
        raise SystemExit(0)

    builder.packmol.pack = timed_pack
    try:
        builder.build(req)
    except SystemExit:
        pass
    return 0 if captured.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
