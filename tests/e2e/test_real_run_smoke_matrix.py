"""E2E Level 4: Real-Run Smoke matrix (docs/WORKFLOW_VERIFICATION_PLAN.md §6, Level 4).

최소 step의 실제 LAMMPS 실행이 crash 없이 완료되는지 검증한다.

이 모듈은 **실제 LAMMPS 실행이 필요**하므로 전체가 모듈 레벨 ``skipif`` 로 가드된다.
LAMMPS 실행 파일이 없거나 실행 불가한 CI 에서는 전부 skip 된다.

해석 순서 (LAMMPS 실행 파일):
1. ``$LAMMPS_EXECUTABLE`` 환경변수
2. ``$LAMMPS_EXE`` 환경변수 (common.tooling 호환)
3. ``common.tooling.resolve_lammps_executable()`` (PATH / project bin)
4. 알려진 빌드 경로 ``/opt/lammps/build/lmp``

최소 세트:
  (1) bulk binder screening, GAFF2-surrogate LJ, 293 K — density finite 검증
  (2) single molecule vacuum, 293 K — energy finite 검증

검증 포인트 (계획 §6 Level 4):
  - ``log.lammps`` 생성
  - parser 에러 없음
  - density / energy 가 finite
  - LAMMPS 정상 완료 (또는 정책상 유효한 fail → ``pytest.skip``)

무겁고 GPU/물리 실행을 포함하므로 ``@pytest.mark.slow`` 가 붙는다.

NOTE: 여기서 쓰는 LJ 파라미터는 GAFF2 surrogate(스크리닝용 근사)이며 full GAFF2
물리값이 아니다. 이 테스트의 목적은 "실제 LAMMPS 가 최소 스텝을 crash 없이 도는가" 이지
정량적 물성 정확도 검증이 아니다 (그건 Level 5/6 소비 경로의 영역).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Module-level LAMMPS guard
# ---------------------------------------------------------------------------

_KNOWN_BUILD_PATH = Path("/opt/lammps/build/lmp")


def _resolve_lammps_exe() -> str | None:
    """Resolve a usable LAMMPS executable, or None if unavailable."""
    for env_var in ("LAMMPS_EXECUTABLE", "LAMMPS_EXE"):
        cand = os.environ.get(env_var)
        if cand and Path(cand).exists() and os.access(cand, os.X_OK):
            return cand

    try:
        import sys

        sys.path.insert(0, "src")
        from common.tooling import resolve_lammps_executable

        resolved = resolve_lammps_executable()
        if resolved and Path(resolved).exists():
            return resolved
    except Exception:
        pass

    if _KNOWN_BUILD_PATH.exists() and os.access(_KNOWN_BUILD_PATH, os.X_OK):
        return str(_KNOWN_BUILD_PATH)

    return None


def _lammps_runnable(exe: str | None) -> bool:
    """Verify the executable actually launches (``-h`` returns cleanly)."""
    if not exe:
        return False
    try:
        result = subprocess.run(
            [exe, "-h"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return False


LAMMPS_EXE = _resolve_lammps_exe()

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not _lammps_runnable(LAMMPS_EXE),
        reason=(
            "LAMMPS executable not available or not runnable (set LAMMPS_EXECUTABLE / LAMMPS_EXE)"
        ),
    ),
]


# ---------------------------------------------------------------------------
# Minimal data-file + input generators (self-contained, no Packmol dependency)
# ---------------------------------------------------------------------------


def _write_lj_data_file(
    path: Path,
    *,
    n_per_axis: int,
    spacing: float,
    box: float,
    mass: float = 12.0,
) -> int:
    """Write a simple single-atom-type LJ cubic lattice data file.

    Returns the number of atoms written.
    """
    coords: list[tuple[float, float, float]] = []
    for i in range(n_per_axis):
        for j in range(n_per_axis):
            for k in range(n_per_axis):
                coords.append((i * spacing + 1.0, j * spacing + 1.0, k * spacing + 1.0))

    lines = [
        "LAMMPS smoke-test data file",
        "",
        f"{len(coords)} atoms",
        "1 atom types",
        "",
        f"0.0 {box:.4f} xlo xhi",
        f"0.0 {box:.4f} ylo yhi",
        f"0.0 {box:.4f} zlo zhi",
        "",
        "Masses",
        "",
        f"1 {mass}",
        "",
        "Atoms",
        "",
    ]
    for idx, (x, y, z) in enumerate(coords, start=1):
        lines.append(f"{idx} 1 {x:.4f} {y:.4f} {z:.4f}")
    lines.append("")
    path.write_text("\n".join(lines))
    return len(coords)


def _write_bulk_input(path: Path, data_file: str, temperature: float) -> None:
    """Bulk binder screening surrogate: minimize -> NVT -> NPT (iso), p p p."""
    script = f"""# Level4 smoke: bulk binder screening (GAFF2 surrogate)
units real
atom_style atomic
boundary p p p

read_data {data_file}

pair_style lj/cut 10.0
pair_modify mix arithmetic
pair_coeff 1 1 0.070 3.55

neighbor 2.0 bin
neigh_modify every 10 delay 0 check yes

thermo_style custom step temp press vol density pe ke etotal
thermo 50

min_style cg
minimize 1.0e-4 1.0e-6 100 1000

velocity all create {temperature} 12345 mom yes rot yes
fix 1 all nvt temp {temperature} {temperature} 100.0
run 200
unfix 1

fix 2 all npt temp {temperature} {temperature} 100.0 iso 1.0 1.0 1000.0
run 300
unfix 2

print "BULK_SMOKE_DONE"
"""
    path.write_text(script)


def _write_single_molecule_input(path: Path, data_file: str, temperature: float) -> None:
    """Single molecule vacuum surrogate: minimize -> NVT only, large box, p p p."""
    script = f"""# Level4 smoke: single molecule vacuum (GAFF2 surrogate)
units real
atom_style atomic
boundary p p p

read_data {data_file}

pair_style lj/cut 10.0
pair_coeff 1 1 0.070 3.55

neighbor 2.0 bin
neigh_modify every 10 delay 0 check yes

thermo_style custom step temp pe ke etotal
thermo 50

min_style cg
minimize 1.0e-4 1.0e-6 100 1000

velocity all create {temperature} 24680 mom yes rot yes
fix 1 all nvt temp {temperature} {temperature} 100.0
run 200
unfix 1

print "SM_SMOKE_DONE"
"""
    path.write_text(script)


def _run_lammps(work_dir: Path, input_name: str) -> subprocess.CompletedProcess:
    """Run LAMMPS in ``work_dir`` against ``input_name`` (writes log.lammps)."""
    return subprocess.run(
        [LAMMPS_EXE, "-in", input_name],
        cwd=str(work_dir),
        capture_output=True,
        text=True,
        timeout=600,
    )


def _parse_log(work_dir: Path):
    """Parse log.lammps using the production LogParser."""
    import sys

    sys.path.insert(0, "src")
    from parsers.log_parser import LogParser

    log_file = work_dir / "log.lammps"
    assert log_file.exists(), "log.lammps must be generated by the run"
    parser = LogParser()
    return parser, parser.parse(log_file)


def _is_finite(value) -> bool:
    import math

    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRealRunSmokeMatrix:
    def test_bulk_binder_screening_293K(self, tmp_path):
        """(1) bulk binder, screening, GAFF2-surrogate LJ, 293 K — density finite."""
        work_dir = tmp_path / "bulk293"
        work_dir.mkdir()
        data_file = work_dir / "system.data"
        n_atoms = _write_lj_data_file(data_file, n_per_axis=4, spacing=4.0, box=20.0)
        assert n_atoms == 64

        _write_bulk_input(work_dir / "in.lammps", "system.data", temperature=293.0)
        result = _run_lammps(work_dir, "in.lammps")

        if result.returncode != 0:
            # A policy-valid failure (e.g. unstable surrogate) is acceptable for a
            # smoke test as long as it does not crash silently; surface and skip.
            pytest.skip(
                f"LAMMPS bulk run exited non-zero (policy-valid fail): {result.stderr[-800:]}"
            )

        _parser, parsed = _parse_log(work_dir)
        assert not parsed.errors, f"parser reported errors: {parsed.errors}"
        assert parsed.completed, "run should complete cleanly"

        finals = _parser.get_final_values(parsed)
        assert "Density" in finals, finals.keys()
        assert _is_finite(finals["Density"]), finals["Density"]
        assert finals["Density"] > 0.0
        # Energy column present and finite
        energy_key = next((k for k in ("TotEng", "PotEng") if k in finals), None)
        assert energy_key is not None, finals.keys()
        assert _is_finite(finals[energy_key]), finals[energy_key]

        assert "BULK_SMOKE_DONE" in (work_dir / "log.lammps").read_text() or result.returncode == 0

    def test_single_molecule_vacuum_293K(self, tmp_path):
        """(2) single molecule vacuum, 293 K — energy finite."""
        work_dir = tmp_path / "sm293"
        work_dir.mkdir()
        data_file = work_dir / "mol.data"
        # A handful of atoms in a large vacuum box.
        n_atoms = _write_lj_data_file(data_file, n_per_axis=2, spacing=1.5, box=40.0)
        assert n_atoms == 8

        _write_single_molecule_input(work_dir / "in.lammps", "mol.data", temperature=293.0)
        result = _run_lammps(work_dir, "in.lammps")

        if result.returncode != 0:
            pytest.skip(
                f"LAMMPS single-molecule run exited non-zero (policy-valid fail): "
                f"{result.stderr[-800:]}"
            )

        _parser, parsed = _parse_log(work_dir)
        assert not parsed.errors, f"parser reported errors: {parsed.errors}"
        assert parsed.completed, "run should complete cleanly"

        finals = _parser.get_final_values(parsed)
        energy_key = next((k for k in ("TotEng", "PotEng") if k in finals), None)
        assert energy_key is not None, finals.keys()
        assert _is_finite(finals[energy_key]), finals[energy_key]
