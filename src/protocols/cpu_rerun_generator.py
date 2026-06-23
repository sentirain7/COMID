"""CPU rerun 스크립트 생성기 (기존 SSOT 재사용)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from common.logging import get_logger
from contracts.schemas import GroupEnergySpec, StudyType

if TYPE_CHECKING:
    pass

logger = get_logger("protocols.cpu_rerun_generator")


class CPURerunGenerator:
    """CPU-only rerun 스크립트 생성 (non-KOKKOS).

    GPU KOKKOS 모드에서는 compute group/group의 kspace yes 옵션이 지원되지 않음.
    정밀한 E_inter 계산을 위해 CPU-only 모드로 trajectory를 rerun하여
    long-range Coulomb 기여분을 포함한 정확한 그룹 간 에너지를 계산.
    """

    def generate(
        self,
        data_file: Path,
        trajectory_file: Path,
        group_energy_spec: GroupEnergySpec,
        output_dir: Path,
        study_type: StudyType = StudyType.BULK,
        ff_config_key: str = "bulk_ff_gaff2",
    ) -> Path:
        """CPU rerun 스크립트 생성.

        Args:
            data_file: LAMMPS data file path (absolute)
            trajectory_file: Trajectory dump file path (absolute)
            group_energy_spec: Group energy specification
            output_dir: Output directory for rerun script
            study_type: Study type for boundary settings
            ff_config_key: Force field config key

        Returns:
            Path to generated in.rerun_einter file

        Note:
            Finding #6: 파일 경로 안정화
            data/dump 파일이 output_dir 외부에 있으면 심링크를 생성하여
            LAMMPS가 안전하게 접근할 수 있도록 함.
        """
        import os

        from .lammps_force_field import generate_group_energy_commands, generate_organic_ff

        # Ensure output_dir exists
        output_dir.mkdir(parents=True, exist_ok=True)

        # Resolve file paths - create symlinks if files are outside output_dir
        def _ensure_accessible(src_file: Path, link_name: str) -> str:
            """Ensure file is accessible from output_dir, return relative name."""
            src_file = src_file.resolve()
            output_dir_resolved = output_dir.resolve()

            # Check if file is already in output_dir
            try:
                rel_path = src_file.relative_to(output_dir_resolved)
                return str(rel_path)
            except ValueError:
                pass  # File is outside output_dir

            # Create symlink in output_dir
            link_path = output_dir_resolved / link_name
            if link_path.exists() or link_path.is_symlink():
                link_path.unlink()
            os.symlink(src_file, link_path)
            logger.debug(f"Created symlink: {link_path} -> {src_file}")
            return link_name

        data_name = _ensure_accessible(data_file, "data.rerun.lammps")
        traj_name = _ensure_accessible(trajectory_file, "dump.rerun.lammpstrj")

        lines = [
            "# CPU Rerun for Precise E_inter Analysis",
            "# Mode: cpu_rerun_precise",
            "# WARNING: GPU/KOKKOS 옵션 사용 금지 (CPU-only for kspace precision)",
            "",
            "units real",
            "atom_style full",
        ]

        # Boundary — study_type 정책 재사용
        if study_type == StudyType.LAYER_BULKFF:
            lines.append("boundary p p f")
        else:
            lines.append("boundary p p p")

        lines.append("")

        # Force field — 기존 SSOT 재사용
        ff_block = generate_organic_ff(
            ff_config_key,
            has_charges=True,
            has_bonds=True,
            study_type=study_type,
        )
        lines.append(ff_block)
        lines.append("")

        # Read data (use resolved name)
        lines.extend(
            [
                f"read_data {data_name}",
                "",
                "neighbor 2.0 bin",
                "neigh_modify delay 0 every 1 check yes",
                "",
            ]
        )

        # Group definitions + compute group/group WITH kspace yes (CPU rerun 핵심)
        group_cmds = generate_group_energy_commands(
            group_energy_spec,
            include_kspace=True,
        )
        lines.append(group_cmds)
        lines.append("")

        # Thermo output
        gg_cols = " ".join(f"c_gg_{p.label}" for p in group_energy_spec.pairs)
        lines.extend(
            [
                f"thermo_style custom step temp pe ke etotal vol {gg_cols}",
                "thermo 1",
                "",
                "# Rerun command (Codex v4: post no dump x y z box yes format native)",
                f"rerun {traj_name} post no dump x y z box yes format native",
            ]
        )

        output_path = output_dir / "in.rerun_einter"
        output_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"Generated CPU rerun script: {output_path}")
        return output_path


DEFAULT_CPU_RERUN_GENERATOR = CPURerunGenerator()
