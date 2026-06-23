"""water 층 interface cell 자동 프로비저닝 (수분손상 트랙, 계획 §2/P6).

wet 계면 layered 실험이 필요로 하는 water 층을 기존
``create_interface_molecule_cell``(Packmol 즉시 빌드, source_hash dedupe)로
보장한다. XY는 parent binder box에 맞춰 affine rescale 한도를 피한다.
"""

from common.logging import get_logger

logger = get_logger(__name__)


async def ensure_water_interface_cell(
    lx_angstrom: float,
    ly_angstrom: float,
    *,
    mol_id: str = "H2O",
    thickness_angstrom: float = 10.0,
    target_density: float = 1.0,
    seed: int | None = None,
) -> str:
    """지정 크기의 water interface cell을 보장하고 cell_id를 반환한다.

    기존 ``create_interface_molecule_cell``이 source_hash로 동일 파라미터
    셀을 dedupe하므로, 같은 크기의 wet 실험이 반복돼도 셀은 1회만 생성된다.

    Args:
        lx_angstrom: water 층 X 크기 (보통 parent binder box_lx)
        ly_angstrom: water 층 Y 크기 (보통 parent binder box_ly)
        mol_id: water 분자 ID (정책 SSOT)
        thickness_angstrom: 층 두께 (Z)
        target_density: 목표 밀도 (g/cm3)
        seed: Packmol seed (None = 자동)

    Returns:
        interface molecule cell ID (layered source_id로 사용)
    """
    from api.schemas import InterfaceMoleculeCellCreateRequest
    from features.interface_molecules.service import create_interface_molecule_cell

    request = InterfaceMoleculeCellCreateRequest(
        name=f"water-{mol_id}-{lx_angstrom:.0f}x{ly_angstrom:.0f}x{thickness_angstrom:.0f}",
        mol_id=mol_id,
        lx_angstrom=float(lx_angstrom),
        ly_angstrom=float(ly_angstrom),
        lz_angstrom=float(thickness_angstrom),
        target_density=float(target_density),
        seed=seed,
    )
    response = await create_interface_molecule_cell(request)
    logger.info(
        "Water interface cell ensured: %s (%.0fx%.0fx%.0f Å)",
        response.cell_id,
        lx_angstrom,
        ly_angstrom,
        thickness_angstrom,
    )
    return response.cell_id
