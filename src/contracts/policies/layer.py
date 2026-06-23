"""
Layer policy - SSOT for inter-layer gap settings in layered structures.

This policy defines default values and validation bounds for the gap
between layers in multi-layer (2-5 layer) structure compositions.
"""

from pydantic import BaseModel, Field


class LayerPolicy(BaseModel):
    """Policy for inter-layer gap and XY tolerance in layered structure compositions.

    Default gap of 2.0 A is standard for MD layer stacking to avoid
    atom overlap while maintaining realistic interfacial distances.
    """

    inter_layer_gap_angstrom: float = Field(2.0, description="Default inter-layer gap (Angstrom)")
    gap_min_angstrom: float = Field(0.0, ge=0, description="Minimum allowed gap (Angstrom)")
    gap_max_angstrom: float = Field(20.0, gt=0, description="Maximum allowed gap (Angstrom)")
    xy_tolerance_pct: float = Field(5.0, description="Default XY tolerance (%)")
    xy_tolerance_pct_min: float = Field(0.1, gt=0, description="Min XY tolerance (%)")
    xy_tolerance_pct_max: float = Field(50.0, gt=0, description="Max XY tolerance (%)")
    rescale_warn_pct: float = Field(
        5.0,
        description="Warn when affine rescale factor exceeds this (%). "
        "Amorphous layers are affine-rescaled to match crystal XY.",
    )
    rescale_max_pct: float = Field(
        10.0,
        description="Hard limit: reject combination when rescale exceeds this (%)",
    )
    z_vacuum_angstrom: float = Field(
        20.0,
        description="Submit-only vacuum buffer above/below slab for kspace slab correction (Angstrom)",
    )
    z_vacuum_min_angstrom: float = Field(0.0, ge=0, description="Minimum z-vacuum (Angstrom)")
    z_vacuum_max_angstrom: float = Field(200.0, gt=0, description="Maximum z-vacuum (Angstrom)")

    # ── Slab geometry adequacy (build gate, 보완 #5) ──
    # XY/Z 종횡비: 얇은 XY 위에 두꺼운 슬랩을 쌓으면 주기적 XY 방향 자기상호작용이
    # 과도해진다. warn(권장 하한) < ratio 는 경고, hard(절대 하한) 미만은 빌드 거부.
    min_xy_to_z_ratio_warn: float = Field(
        1.2, gt=0, description="Recommended lower bound for min(Lx,Ly)/total_Lz (warn)"
    )
    min_xy_to_z_ratio_hard: float = Field(
        0.5, gt=0, description="Hard lower bound for min(Lx,Ly)/total_Lz (fail/build gate)"
    )
    # 진공/슬랩두께 비율: p p f 고정경계에서 z 진공은 자유표면 완화·원자 이탈
    # 방지·인장 변형 공간을 확보한다(슬랩이 진공을 다 채우면 위 역할이 사라짐).
    # 주의: kspace_modify slab 3.0(EW3DC) 자체는 솔버가 셀을 z로 3배 확장해 이미지
    # 간격을 보장하므로 in-box 진공에 의존하지 않는다 — 이 비율은 EW3DC 유효성이
    # 아니라 위 물리적 여유 공간에 대한 보수적 하한이다. total_vacuum = 2×z_vacuum.
    min_vacuum_to_slab_ratio_warn: float = Field(
        1.0, gt=0, description="Recommended lower bound for (2*z_vacuum)/slab_thickness (warn)"
    )
    min_vacuum_to_slab_ratio_hard: float = Field(
        0.3, gt=0, description="Hard lower bound for (2*z_vacuum)/slab_thickness (fail/build gate)"
    )

    def get_defaults_dict(self) -> dict:
        """Return default layer settings as a dictionary.

        Returns:
            Dictionary with default layer gap and XY tolerance settings
            for frontend/API consumption.
        """
        return {
            "inter_layer_gap_angstrom": self.inter_layer_gap_angstrom,
            "xy_tolerance_pct": self.xy_tolerance_pct,
            "z_vacuum_angstrom": self.z_vacuum_angstrom,
        }

    def get_bounds_dict(self) -> dict:
        """Return validation bounds as a dictionary.

        Returns:
            Dictionary with min/max bounds for frontend validation.
        """
        return {
            "gap_angstrom": {
                "min": self.gap_min_angstrom,
                "max": self.gap_max_angstrom,
            },
            "xy_tolerance_pct": {
                "min": self.xy_tolerance_pct_min,
                "max": self.xy_tolerance_pct_max,
            },
            "z_vacuum_angstrom": {
                "min": self.z_vacuum_min_angstrom,
                "max": self.z_vacuum_max_angstrom,
            },
        }


# SSOT: Single source of truth for layer policy
DEFAULT_LAYER_POLICY = LayerPolicy()
