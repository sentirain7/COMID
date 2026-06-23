"""Temperature policy (SSOT).

All default temperature sets for binder-cell batch jobs, single-molecule
E_intra acquisition, and frontend initial values should derive from
these constants.
"""

# Full temperature sweep for binder-cell screening (20 K interval, 213–433 K).
# This is the single source of truth used by:
#   - BatchJobBinderCellRequest default
#   - Single Molecule batch submit default
#   - Molecules E_intra coverage required_count
#   - Frontend temperature presets (via /experiments/defaults API)
DEFAULT_BINDER_CELL_BATCH_TEMPERATURES_K: list[float] = [
    213.0,
    233.0,
    253.0,
    273.0,
    293.0,
    313.0,
    333.0,
    353.0,
    373.0,
    393.0,
    413.0,
    433.0,
]

# Priority temperatures submitted first when queue ordering matters.
DEFAULT_TEMPERATURE_PRIORITY_K: list[float] = [293.0, 313.0]

# Full set of selectable temperatures in UI (10 K interval, 213–433 K).
# Superset of DEFAULT_BINDER_CELL_BATCH_TEMPERATURES_K.
# Users can pick any of these; batch defaults pre-select the 20 K subset.
AVAILABLE_TEMPERATURE_OPTIONS_K: list[float] = [
    float(213 + i * 10)
    for i in range(23)  # 213, 223, 233, ..., 433
]
