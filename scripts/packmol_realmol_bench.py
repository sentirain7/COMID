"""실제 라이브러리 분자로 packmol 벤치 (mol_count 경로 = amorphous/batch와 동일).

packmol_wallclock_bench.py(wt% + stale mock 무작위 좌표 blob)가 미수렴했던 것과
달리, StructureBuilder의 mol_count 경로(_prepare_packmol_input_mol_count의
MOL→XYZ 변환으로 실제 물리적 분자 기하)를 그대로 타서 수렴 시간을 비교한다.
StructureBuilder.build를 호출하되 packmol 단계만 측정하고 직후 중단.
"""

import os
import tempfile
import time
from pathlib import Path

from builder.molecule_db_loader import create_molecule_db
from builder.structure_builder import StructureBuilder
from contracts.schema_enums import MoleculeCategory
from orchestrator.request_factory import create_build_request

DENSITY = float(os.environ.get("BENCH_DENSITY", "0.5"))
TARGET_ATOMS = int(os.environ.get("BENCH_ATOMS", "3000"))
SINGLE = os.environ.get("BENCH_SINGLE", "0") == "1"  # 단일 컴포넌트(asphaltene만)


def first_real(db, category: str):
    for spec in db.get_by_category(MoleculeCategory(category)):
        if not str(getattr(spec, "topology_hash", "")).startswith("mock"):
            return spec
    return None


def main() -> int:
    db = create_molecule_db(allow_mock=True)

    cats = ["asphaltene"] if SINGLE else ["asphaltene", "resin", "aromatic", "saturate"]
    per_cat_atoms = TARGET_ATOMS / len(cats)
    mol_counts: dict[str, int] = {}
    for cat in cats:
        spec = first_real(db, cat)
        if spec is None:
            print(f"[bench] {cat}: 실제 분자 없음 — 중단")
            return 2
        count = max(1, int(round(per_cat_atoms / spec.atom_count)))
        mol_counts[spec.mol_id] = count
        print(f"[bench] {cat:10s} {spec.mol_id:24s} atoms={spec.atom_count:3d} x{count}")

    req = create_build_request(
        composition={k: float(v) for k, v in mol_counts.items()},
        composition_mode="mol_count",
        target_atoms=TARGET_ATOMS,
        initial_density=DENSITY,
        seed=42,
    )

    work_dir = Path(tempfile.mkdtemp(prefix="realbench_"))
    builder = StructureBuilder(molecule_db=db, work_dir=work_dir)
    print(
        f"[bench] mol_count mode density={DENSITY} timeout={builder.packmol.timeout}s "
        f"tolerance={builder.packmol.tolerance}",
        flush=True,
    )

    orig = builder.packmol.pack
    captured: dict = {}

    def timed(*a, **k):
        t0 = time.monotonic()
        r = orig(*a, **k)
        dt = time.monotonic() - t0
        captured.update(dt=dt, success=r.success)
        print(
            f"[bench] RESULT real-molecules(mol_count) density={DENSITY} dt={dt:.1f}s "
            f"success={r.success} box={r.box_dimensions} err={r.error_message}",
            flush=True,
        )
        raise SystemExit(0)

    builder.packmol.pack = timed
    try:
        builder.build(req)
    except SystemExit:
        pass
    return 0 if captured.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
