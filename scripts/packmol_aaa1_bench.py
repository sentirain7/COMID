"""AAA1 정의 바인더 조성(다양한 분자)으로 packmol 벤치 — batch 경로 재현.

batch(AdditiveBatchJobBinderCellRunner)가 성공시킨 정확한 조성
(get_binder_composition_with_aging의 12종 다양한 분자)을 density 0.5로 패킹해,
역설계의 4종 큰 대표분자(미수렴@0.5)와 대조한다. 다양한 크기 분자가
packing 난이도를 낮추는지 확인.
"""

import os
import tempfile
import time
from pathlib import Path

from api.deps import get_aging_config
from builder.molecule_db_loader import create_molecule_db
from builder.structure_builder import StructureBuilder
from orchestrator.request_factory import create_build_request

DENSITY = float(os.environ.get("BENCH_DENSITY", "0.5"))


def main() -> int:
    db = create_molecule_db(allow_mock=True)
    config = get_aging_config()

    temp_code = db.get_temperature_code(config, 293.0)
    mol_counts = db.get_binder_composition_with_aging(
        config, binder_type="AAA1", size="X1", aging="non_aging", temp_code=temp_code
    )
    total = sum(int(v) for v in mol_counts.values())
    print(f"[bench] AAA1 X1 조성: {len(mol_counts)}종 {total}분자")
    for mid, cnt in mol_counts.items():
        print(f"        {mid:24s} x{cnt}")

    req = create_build_request(
        composition={k: float(v) for k, v in mol_counts.items()},
        composition_mode="mol_count",
        seed=42,
        tier="screening",
        initial_density=DENSITY,
    )

    work_dir = Path(tempfile.mkdtemp(prefix="aaa1bench_"))
    builder = StructureBuilder(molecule_db=db, work_dir=work_dir)
    print(f"[bench] density={DENSITY} timeout={builder.packmol.timeout}s", flush=True)

    orig = builder.packmol.pack
    cap: dict = {}

    def timed(*a, **k):
        t0 = time.monotonic()
        r = orig(*a, **k)
        cap.update(dt=time.monotonic() - t0, success=r.success)
        print(
            f"[bench] RESULT AAA1(다양한분자) density={DENSITY} dt={cap['dt']:.1f}s "
            f"success={r.success} box={r.box_dimensions} err={r.error_message}",
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
