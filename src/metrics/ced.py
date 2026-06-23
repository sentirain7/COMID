"""
Cohesive Energy Density (CED) calculator.

Calculates CED using the E_intra subtraction method.

Coverage modes control how missing E_intra values are handled:
- ``exact_required`` (default): All molecules must have an exact
  temperature match. Any approximate or missing → return None.
- ``allow_tolerance``: Approximate temperature matches (within
  DB-level tolerance) are accepted. Missing → return None.
- ``allow_missing_pe_over_v``: Like allow_tolerance, but truly missing
  molecules fall back to PE/V (E_intra treated as 0 for them).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from common.logging import get_logger
from common.units import energy_to_ced
from contracts.schema_enums import coerce_e_intra_method
from contracts.schemas import EIntraKey, MetricResult
from parsers.stats_utils import (
    apply_time_window,
    compute_mean_std,
    get_default_dt_fs,
    get_default_thermo_interval,
    get_default_window_ps,
)

if TYPE_CHECKING:
    from metrics.e_intra_store import EIntraStore

logger = get_logger("metrics.ced")

# Calculation version for metadata tracking
_CED_CALC_VERSION = "v00.99.31"

# Valid coverage modes
CoverageMode = Literal["exact_required", "allow_tolerance", "allow_missing_pe_over_v"]


class CEDCalculator:
    """
    Calculator for Cohesive Energy Density.

    Uses the formula:
    CED = -(E_total - sum(n_i * E_intra_i)) / V

    where E_intra_i is the intramolecular energy of molecule type i.
    Sign is flipped so CED is a positive material property.
    """

    def __init__(
        self,
        e_intra_store: EIntraStore | None = None,
        *,
        coverage_mode: CoverageMode = "exact_required",
    ):
        """Initialize CED calculator.

        Args:
            e_intra_store: E_intra cache store for looking up values.
            coverage_mode: How to handle missing / approximate E_intra values.
                ``"exact_required"`` (default) — fail-closed if any molecule
                lacks an exact temperature match.
                ``"allow_tolerance"`` — accept approximate temperature matches
                (within DB-level tolerance); fail if truly missing.
                ``"allow_missing_pe_over_v"`` — like allow_tolerance, but
                truly missing molecules fall back to PE/V (E_intra = 0).
        """
        if coverage_mode not in ("exact_required", "allow_tolerance", "allow_missing_pe_over_v"):
            raise ValueError(
                f"Invalid coverage_mode={coverage_mode!r}. "
                "Must be one of: exact_required, allow_tolerance, allow_missing_pe_over_v"
            )
        self.e_intra_store = e_intra_store
        self.coverage_mode: CoverageMode = coverage_mode

    def calculate(
        self,
        total_pe: float,
        volume_A3: float,
        mol_counts: dict[str, int],
        e_intra_values: dict[str, float],
    ) -> float:
        """Calculate CED in MJ/m³ (positive value).

        Args:
            total_pe: Total potential energy (kcal/mol)
            volume_A3: System volume (Angstrom³)
            mol_counts: Dictionary of molecule_id -> count
            e_intra_values: Dictionary of molecule_id -> E_intra

        Returns:
            CED in MJ/m³
        """
        total_e_intra = 0.0
        for mol_id, count in mol_counts.items():
            if mol_id in e_intra_values:
                total_e_intra += count * e_intra_values[mol_id]

        e_cohesive = total_pe - total_e_intra
        return energy_to_ced(e_cohesive, volume_A3)

    def calculate_from_thermo(
        self,
        thermo_data: dict[str, list[float]],
        mol_counts: dict[str, int],
        ff_name: str,
        ff_version: str,
        window_ps: float | None = None,
        dt_fs: float | None = None,
        thermo_interval: int | None = None,
        use_window_ps: bool = True,
        skip_fraction: float | None = None,
        temperature_K: float = 298.0,
        e_intra_method: str = "single_molecule_vacuum",
    ) -> MetricResult | None:
        """
        Calculate CED from thermo data.

        Args:
            thermo_data: Thermodynamic data from log parser
            mol_counts: Molecule counts
            ff_name: Force field name
            ff_version: Force field version
            window_ps: Time window from end for averaging (ps). Default from SSOT.
            dt_fs: Timestep in femtoseconds. Default from SSOT.
            thermo_interval: Steps between thermo outputs. Default: 1000.
            use_window_ps: If True, use window_ps method. If False, use skip_fraction.
                          Default: True (new behavior).
            skip_fraction: Deprecated. Fraction of data to skip from start.
                          Only used if use_window_ps=False.
            e_intra_method: E_intra method tag for lookup (PR 2 v4 — Method 1
                ``single_molecule_vacuum`` is the legacy default; pass
                ``single_molecule_vacuum_adaptive_cutoff`` for Method 1a).
                The lookup is method-aware so 1 / 1a / 2 cache rows do not
                cross-contaminate.  All molecules in ``mol_counts`` must
                resolve via the same method (mixing is fail-closed).

        Returns:
            MetricResult for CED or None if calculation fails
        """
        # Get potential energy
        pe_col = None
        for col in ["PotEng", "PE", "E_pot"]:
            if col in thermo_data:
                pe_col = col
                break

        if pe_col is None or not thermo_data[pe_col]:
            logger.warning("No potential energy data found")
            return None

        # Get volume
        vol_col = None
        for col in ["Volume", "Vol", "V"]:
            if col in thermo_data:
                vol_col = col
                break

        if vol_col is None or not thermo_data[vol_col]:
            logger.warning("No volume data found")
            return None

        # Use SSOT defaults
        eff_dt_fs = dt_fs if dt_fs is not None else get_default_dt_fs()
        eff_thermo_interval = (
            thermo_interval if thermo_interval is not None else get_default_thermo_interval()
        )
        eff_window_ps = window_ps if window_ps is not None else get_default_window_ps()

        # Apply windowing based on mode
        if use_window_ps:
            pe_values = apply_time_window(
                thermo_data[pe_col],
                window_ps=eff_window_ps,
                dt_fs=eff_dt_fs,
                thermo_interval=eff_thermo_interval,
            )
            vol_values = apply_time_window(
                thermo_data[vol_col],
                window_ps=eff_window_ps,
                dt_fs=eff_dt_fs,
                thermo_interval=eff_thermo_interval,
            )
            window_method = "window_ps"
        else:
            # Legacy mode with skip_fraction
            eff_skip_fraction = skip_fraction if skip_fraction is not None else 0.2
            pe_values = apply_time_window(
                thermo_data[pe_col],
                skip_fraction=eff_skip_fraction,
            )
            vol_values = apply_time_window(
                thermo_data[vol_col],
                skip_fraction=eff_skip_fraction,
            )
            window_method = "skip_fraction"

        if not pe_values or not vol_values:
            logger.warning("No data after windowing")
            return None

        avg_pe, _ = compute_mean_std(pe_values)
        avg_vol, _ = compute_mean_std(vol_values)

        # -----------------------------------------------------------------
        # E_intra lookup — classify each molecule into exact / approx / missing
        # -----------------------------------------------------------------
        exact_matches: dict[str, float] = {}  # mol_id -> e_intra (exact T match)
        approx_matches: dict[str, float] = {}  # mol_id -> e_intra (tolerance T match)
        matched_temperatures: dict[str, float] = {}  # mol_id -> actual matched T
        missing_mols: list[str] = []  # mol_ids with no match at all

        method_enum = coerce_e_intra_method(e_intra_method)
        if self.e_intra_store and mol_counts:
            for mol_id in mol_counts:
                key = EIntraKey(
                    mol_id=mol_id,
                    ff_name=ff_name,
                    ff_version=ff_version,
                    temperature_K=temperature_K,
                    method=method_enum,
                )
                result = self.e_intra_store.get(key)
                if result is None:
                    missing_mols.append(mol_id)
                elif abs(result.temperature_K - temperature_K) < 0.1:
                    # DB returned an exact temperature match
                    exact_matches[mol_id] = result.e_intra
                    matched_temperatures[mol_id] = result.temperature_K
                else:
                    # DB returned a tolerance-based approximate match
                    approx_matches[mol_id] = result.e_intra
                    matched_temperatures[mol_id] = result.temperature_K
        elif mol_counts:
            # No store at all — all molecules are missing
            missing_mols = list(mol_counts.keys())

        # -----------------------------------------------------------------
        # Coverage-mode gating
        # -----------------------------------------------------------------
        n_exact = len(exact_matches)
        n_approx = len(approx_matches)
        n_missing = len(missing_mols)
        n_total = len(mol_counts) if mol_counts else 0

        coverage_info = {
            "coverage_mode": self.coverage_mode,
            "has_mol_counts": bool(mol_counts),
            "molecule_type_count": n_total,
            "molecule_instance_count": int(sum(mol_counts.values())) if mol_counts else 0,
            "exact_count": n_exact,
            "approximate_count": n_approx,
            "missing_molecules": missing_mols,
            "matched_temperatures_k": matched_temperatures,
            "e_intra_coverage": f"{n_exact + n_approx}/{n_total}",
            # PR 2 (Method 1a SSOT): record the E_intra method used for this
            # CED calculation so consumers (ML, API) can detect drift and
            # block method mixing.  All molecules in a single CED call share
            # the same method by construction (single ``e_intra_method`` arg).
            "e_intra_method": e_intra_method,
        }

        if self.coverage_mode == "exact_required":
            # Fail-closed: ANY approximate or missing → None
            if n_approx > 0 or n_missing > 0:
                logger.warning(
                    "CED fail-closed (exact_required): approx=%d, missing=%d, molecules=%s",
                    n_approx,
                    n_missing,
                    missing_mols or list(approx_matches.keys()),
                )
                return None
            e_intra_values = dict(exact_matches)
            is_exact = True

        elif self.coverage_mode == "allow_tolerance":
            # Accept approximate, but fail on missing
            if n_missing > 0:
                logger.warning(
                    "CED fail-closed (allow_tolerance): missing=%d, molecules=%s",
                    n_missing,
                    missing_mols,
                )
                return None
            e_intra_values = {**exact_matches, **approx_matches}
            is_exact = n_approx == 0

        elif self.coverage_mode == "allow_missing_pe_over_v":
            # Use whatever we have; missing molecules contribute E_intra=0
            e_intra_values = {**exact_matches, **approx_matches}
            is_exact = n_approx == 0 and n_missing == 0
            if n_missing > 0:
                logger.warning(
                    "CED partial coverage (allow_missing_pe_over_v): "
                    "missing=%d molecules %s — E_intra=0 fallback (PE/V overestimate)",
                    n_missing,
                    missing_mols,
                )
        else:
            # Should never reach here due to __init__ validation
            raise ValueError(f"Invalid coverage_mode={self.coverage_mode!r}")

        # -----------------------------------------------------------------
        # Compute CED (mean)
        # -----------------------------------------------------------------
        ced_mpa = self.calculate(avg_pe, avg_vol, mol_counts, e_intra_values)

        # Calculate CED time series for standard deviation
        total_e_intra = sum(mol_counts.get(m, 0) * e_intra_values.get(m, 0.0) for m in mol_counts)
        ced_values: list[float] = []
        for pe, vol in zip(pe_values, vol_values, strict=False):
            if vol > 0:
                ced = energy_to_ced(pe - total_e_intra, vol)
                ced_values.append(ced)

        _, std_dev = compute_mean_std(ced_values)

        # -----------------------------------------------------------------
        # Build provenance metadata
        # -----------------------------------------------------------------
        calc_info: dict[str, object] = {
            "has_e_intra": bool(e_intra_values),
            "is_exact": is_exact,
            "n_samples": len(pe_values),
            "window_method": window_method,
            "calc_version": _CED_CALC_VERSION,
            **coverage_info,
        }

        if use_window_ps:
            calc_info["window_ps"] = eff_window_ps
        else:
            calc_info["skip_fraction"] = skip_fraction if skip_fraction is not None else 0.2

        return MetricResult(
            metric_name="cohesive_energy_density",
            namespace="bulk_ff_gaff2",
            value=ced_mpa,
            unit="MJ/m3",
            uncertainty=std_dev,
            array_summary=calc_info,
        )

    def validate_ced(self, ced_mj_m3: float) -> bool:
        """
        Validate CED is in reasonable range.

        Args:
            ced_mj_m3: CED in MJ/m³

        Returns:
            True if valid
        """
        # Typical CED for organic materials: 200-600 MJ/m³
        # Asphalt/bitumen typically 300-500 MJ/m³
        return 100.0 < ced_mj_m3 < 1000.0

    def calculate_layer_profile_from_thermo(
        self,
        thermo_data: dict[str, list[float]],
        *,
        mol_counts_by_layer: dict[str, dict[str, int]],
        layer_volumes_A3: dict[str, float],
        layer_labels: list[str],
        ff_name: str,
        ff_version: str,
        window_ps: float | None = None,
        dt_fs: float | None = None,
        thermo_interval: int | None = None,
        temperature_K: float = 298.0,
        e_intra_method: str = "single_molecule_vacuum",
    ) -> MetricResult | None:
        """Calculate a per-layer CED profile for binder-backed layered systems.

        The profile is fail-closed:
        - every binder-backed layer must have a valid potential-energy column
        - every molecule in those layers must resolve via the requested
          ``e_intra_method``
        - every binder-backed layer must have a positive physical volume

        Non-binder layers may remain visible in ``layer_labels`` but are
        omitted from the profile rows if they have no per-layer molecule-count
        provenance.
        """
        if not (mol_counts_by_layer and layer_volumes_A3 and layer_labels):
            return None

        eff_dt_fs = dt_fs if dt_fs is not None else get_default_dt_fs()
        eff_thermo_interval = (
            thermo_interval if thermo_interval is not None else get_default_thermo_interval()
        )
        eff_window_ps = window_ps if window_ps is not None else get_default_window_ps()

        exact_matches_by_layer: dict[str, dict[str, float]] = {}
        matched_temperatures_by_layer: dict[str, dict[str, float]] = {}
        missing_by_layer: dict[str, list[str]] = {}

        if self.e_intra_store is None:
            return None

        eligible_labels = [label for label in layer_labels if mol_counts_by_layer.get(label)]
        if not eligible_labels:
            return None

        method_enum = coerce_e_intra_method(e_intra_method)
        for layer_label in eligible_labels:
            exact_matches_by_layer[layer_label] = {}
            matched_temperatures_by_layer[layer_label] = {}
            missing_mols: list[str] = []
            for mol_id in mol_counts_by_layer.get(layer_label, {}):
                key = EIntraKey(
                    mol_id=mol_id,
                    ff_name=ff_name,
                    ff_version=ff_version,
                    temperature_K=temperature_K,
                    method=method_enum,
                )
                result = self.e_intra_store.get(key)
                if result is None or abs(result.temperature_K - temperature_K) >= 0.1:
                    missing_mols.append(mol_id)
                    continue
                exact_matches_by_layer[layer_label][mol_id] = result.e_intra
                matched_temperatures_by_layer[layer_label][mol_id] = result.temperature_K
            if missing_mols:
                missing_by_layer[layer_label] = missing_mols

        if missing_by_layer:
            logger.warning(
                "Layered CED profile fail-closed: missing E_intra for layers=%s",
                missing_by_layer,
            )
            return None

        rows: list[dict[str, float | int | str]] = []
        omitted_labels: list[str] = []
        for idx, layer_label in enumerate(layer_labels):
            mol_counts = mol_counts_by_layer.get(layer_label) or {}
            if not mol_counts:
                omitted_labels.append(layer_label)
                continue
            volume_A3 = float(layer_volumes_A3.get(layer_label, 0.0) or 0.0)
            if volume_A3 <= 0.0:
                logger.warning(
                    "Layered CED profile fail-closed: invalid volume for layer=%s", layer_label
                )
                return None
            pe_col = f"c_pe_layer_{idx}"
            pe_values = thermo_data.get(pe_col) or []
            if not pe_values:
                logger.warning("Layered CED profile fail-closed: missing thermo column %s", pe_col)
                return None
            windowed_pe = apply_time_window(
                pe_values,
                window_ps=eff_window_ps,
                dt_fs=eff_dt_fs,
                thermo_interval=eff_thermo_interval,
            )
            if not windowed_pe:
                logger.warning(
                    "Layered CED profile fail-closed: no samples after windowing for layer=%s",
                    layer_label,
                )
                return None
            avg_pe, _ = compute_mean_std(windowed_pe)
            total_e_intra = sum(
                int(mol_counts[mol_id]) * exact_matches_by_layer[layer_label][mol_id]
                for mol_id in mol_counts
            )
            ced_value = energy_to_ced(avg_pe - total_e_intra, volume_A3)
            rows.append(
                {
                    "layer_index": idx,
                    "layer_label": layer_label,
                    "ced_MJ_m3": ced_value,
                    "volume_A3": volume_A3,
                }
            )

        if not rows:
            return None

        return MetricResult(
            metric_name="cohesive_energy_density_profile",
            namespace="layer",
            value=None,
            unit="[index, label, MJ/m3, angstrom3]",
            array_summary={
                "e_intra_method": e_intra_method,
                "calc_version": _CED_CALC_VERSION,
                "layer_count": len(layer_labels),
                "profile_scope": "binder_backed_layers",
                "omitted_layer_labels": omitted_labels,
                "matched_temperatures_k": matched_temperatures_by_layer,
                "coverage_mode": "exact_required",
                "profile_rows": rows,
            },
        )
