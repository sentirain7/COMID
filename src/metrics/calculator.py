"""
Main metric calculator.

Coordinates calculation of all metrics from LAMMPS output.
"""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from metrics.e_intra_store import EIntraStore

from common.logging import get_logger
from contracts.interfaces import AbstractMetricCalculator
from contracts.policies.failure import DEFAULT_FAILURE_POLICY
from contracts.policies.forcefield import get_ff_version
from contracts.policies.metrics import MetricsRegistry
from contracts.policies.tier import DEFAULT_TIER_POLICY
from contracts.schemas import GroupEnergySpec, LAMMPSRunResult, MetricResult, ThermoData
from metrics.array_storage import ArrayStorage
from metrics.bulk_modulus import BulkModulusCalculator
from metrics.ced import CEDCalculator, CoverageMode
from metrics.density import DensityCalculator, DensityTimeSeries
from metrics.e_inter import EInterCalculator
from metrics.msd import MSDCalculator
from metrics.rdf import RDFCalculator
from metrics.rdf_pairtype import PairTypeRDFCalculator
from metrics.tensile_metrics import TensileMetricCalculator
from metrics.trajectory_metrics import (
    calculate_msd_metrics,
    calculate_pair_rdf_metrics,
    calculate_rdf_metrics,
)
from metrics.viscosity import ViscosityCalculator
from parsers.dump_parser import DumpParser
from parsers.log_parser import LogParser
from parsers.thermo_extractor import ThermoExtractor

logger = get_logger("metrics.calculator")


# Canonical mapping from thermo extractor keys to metric registry names.
# Shared between calculate() and tests.
ENERGY_COMPONENT_MAP: dict[str, str] = {
    "E_bond": "e_bond",
    "E_angle": "e_angle",
    "E_dihed": "e_dihed",
    "E_imp": "e_improper",
    "E_vdwl": "e_vdwl",
    "E_coul": "e_coul",
    "E_pair": "e_pair",
    "E_mol": "e_mol",
    "E_long": "e_long",
}


class MetricCalculator(AbstractMetricCalculator):
    """
    Main calculator for all MD metrics.

    Implements IMetricCalculator interface.
    """

    def __init__(
        self,
        registry: MetricsRegistry | None = None,
        e_intra_store: "EIntraStore | None" = None,
        array_storage: ArrayStorage | None = None,
        window_ps: float | None = None,
        dt_fs: float = 1.0,
        thermo_interval: int = 1000,
        ced_coverage_mode: CoverageMode = "exact_required",
        bulk_e_intra_method: str | None = None,
    ):
        """
        Initialize metric calculator.

        Args:
            registry: Metrics registry for validation
            e_intra_store: E_intra cache store
            array_storage: Array metric storage for RDF/MSD curves
            window_ps: Time window from end for averaging (ps).
                       Default: from tier policy (200 ps).
            dt_fs: Timestep in femtoseconds
            thermo_interval: Steps between thermo outputs
            ced_coverage_mode: CED coverage mode for exact/approximate handling.
            bulk_e_intra_method: PR 2 (Method 1a SSOT, Codex Round 3) — explicit
                override for bulk CED's E_intra method tag.  Resolution order
                in ``calculate()`` is run_result → metadata_json → this
                override → ``"single_molecule_vacuum"``.  Pass when the
                caller knows the method from the experiment record itself
                rather than relying on ambient env.
        """
        self.registry = registry or MetricsRegistry()
        self.e_intra_store = e_intra_store
        self.bulk_e_intra_method = bulk_e_intra_method
        self.array_storage = array_storage

        # Get default window from tier policy
        if window_ps is None:
            window_ps = DEFAULT_TIER_POLICY.convergence_criteria.density_window_ps

        self.window_ps = window_ps
        self.dt_fs = dt_fs
        self.thermo_interval = thermo_interval

        # Initialize component calculators
        self.log_parser = LogParser()
        self.thermo_extractor = ThermoExtractor(
            window_ps=window_ps,
            dt_fs=dt_fs,
            thermo_interval=thermo_interval,
        )
        self.density_calc = DensityCalculator()
        self.bulk_modulus_calc = BulkModulusCalculator()
        self.ced_calc = CEDCalculator(
            e_intra_store=e_intra_store,
            coverage_mode=ced_coverage_mode,
        )
        self.rdf_calc = RDFCalculator(registry=self.registry)
        self.msd_calc = MSDCalculator(registry=self.registry)
        self.viscosity_calc = ViscosityCalculator(registry=self.registry)
        self.e_inter_calc = EInterCalculator(
            registry=self.registry,
            window_ps=window_ps,
            dt_fs=dt_fs,
            thermo_interval=thermo_interval,
        )
        self.pair_rdf_calc = PairTypeRDFCalculator(registry=self.registry)
        self.tensile_calc = TensileMetricCalculator()
        self.dump_parser = DumpParser()
        self._calculation_metadata: dict[str, str | float | None] = {}

    def get_calculation_metadata(self) -> dict[str, str | float | None]:
        """Return metadata collected during the last calculate() call.

        Includes viscosity parse status, error messages, and partial
        results that should be persisted on the experiment record.

        Returns:
            Metadata dict (empty if calculate() has not been called).
        """
        return self._calculation_metadata.copy()

    def calculate(self, run_result: LAMMPSRunResult) -> list[MetricResult]:
        """
        Calculate all metrics from LAMMPS run result.

        Args:
            run_result: Result from LAMMPS run

        Returns:
            List of MetricResult objects
        """
        self._calculation_metadata = {}
        metrics = []

        # Parse log file
        log_path = Path(run_result.log_file)
        if log_path.exists():
            log_result = self.log_parser.parse(log_path)
            thermo_data = log_result.thermo_data

            # Extract thermo summary
            summary = self.thermo_extractor.extract_summary(thermo_data)

            # Calculate density
            if summary.density_gcc > 0:
                density_metric = self.density_calc.create_metric(
                    density_gcc=summary.density_gcc,
                    std_dev=summary.density_std,
                    temperature_K=summary.temperature_K,
                    pressure_atm=summary.pressure_atm,
                )
                metrics.append(density_metric)

            # Calculate temperature metric
            if summary.temperature_K > 0:
                metrics.append(
                    MetricResult(
                        metric_name="temperature",
                        value=summary.temperature_K,
                        unit="K",
                        namespace="bulk_ff_gaff2",
                    )
                )

            # Isothermal bulk modulus from NPT volume fluctuations
            # (reuses the same trailing window as the density average)
            if summary.temperature_K > 0:
                volume_series = self.thermo_extractor.extract_column(
                    thermo_data, ["Volume", "Vol", "V"]
                )
                bm_result = self.bulk_modulus_calc.compute(
                    volume_series_A3=volume_series,
                    temperature_K=summary.temperature_K,
                )
                bm_metric = self.bulk_modulus_calc.create_metric(bm_result)
                if bm_metric is not None:
                    metrics.append(bm_metric)

            # Calculate pressure metric
            metrics.append(
                MetricResult(
                    metric_name="pressure",
                    value=summary.pressure_atm,
                    unit="atm",
                    namespace="bulk_ff_gaff2",
                )
            )

            # Calculate energy metrics
            energy_components = self.thermo_extractor.extract_energy_components(thermo_data)

            if "PotEng" in energy_components:
                metrics.append(
                    MetricResult(
                        metric_name="potential_energy",
                        value=energy_components["PotEng"],
                        unit="kcal/mol",
                        namespace="bulk_ff_gaff2",
                    )
                )

            if "TotEng" in energy_components:
                metrics.append(
                    MetricResult(
                        metric_name="total_energy",
                        value=energy_components["TotEng"],
                        unit="kcal/mol",
                        namespace="bulk_ff_gaff2",
                    )
                )

            # Kinetic energy
            if "KinEng" in energy_components:
                metrics.append(
                    MetricResult(
                        metric_name="kinetic_energy",
                        value=energy_components["KinEng"],
                        unit="kcal/mol",
                        namespace="bulk_ff_gaff2",
                    )
                )

            # Energy component metrics (present when thermo_style includes decomposition)
            for canon_key, metric_name in ENERGY_COMPONENT_MAP.items():
                if canon_key in energy_components:
                    metrics.append(
                        MetricResult(
                            metric_name=metric_name,
                            value=energy_components[canon_key],
                            unit="kcal/mol",
                            namespace="bulk_ff_gaff2",
                        )
                    )

            # Energy density metrics (energy per unit volume)
            if summary.volume_A3 > 0:
                if "PotEng" in energy_components:
                    metrics.append(
                        MetricResult(
                            metric_name="potential_energy_density",
                            value=energy_components["PotEng"] / summary.volume_A3,
                            unit="kcal/mol/A3",
                            namespace="bulk_ff_gaff2",
                        )
                    )
                if "KinEng" in energy_components:
                    metrics.append(
                        MetricResult(
                            metric_name="kinetic_energy_density",
                            value=energy_components["KinEng"] / summary.volume_A3,
                            unit="kcal/mol/A3",
                            namespace="bulk_ff_gaff2",
                        )
                    )
                if "TotEng" in energy_components:
                    metrics.append(
                        MetricResult(
                            metric_name="total_energy_density",
                            value=energy_components["TotEng"] / summary.volume_A3,
                            unit="kcal/mol/A3",
                            namespace="bulk_ff_gaff2",
                        )
                    )

            # Calculate RDF from dump files
            if run_result.dump_files:
                try:
                    rdf_metrics = self._calculate_rdf(
                        dump_files=run_result.dump_files,
                        exp_id=run_result.exp_id,
                    )
                    metrics.extend(rdf_metrics)
                except Exception as e:
                    logger.warning(f"RDF calculation failed: {e}")

            # Calculate MSD from dump files
            if run_result.dump_files:
                try:
                    msd_metrics = self._calculate_msd(
                        dump_files=run_result.dump_files,
                        exp_id=run_result.exp_id,
                    )
                    metrics.extend(msd_metrics)
                except Exception as e:
                    logger.warning(f"MSD calculation failed: {e}")

            # Calculate viscosity from f_viscosity thermo column (RNEMD)
            try:
                visc_metrics, visc_metadata = self._calculate_viscosity(
                    thermo_data=thermo_data,
                    log_path=log_path,
                    run_result=run_result,
                )
                metrics.extend(visc_metrics)
                self._calculation_metadata.update(visc_metadata)
                if visc_metadata.get("viscosity_parse_status") == "failed":
                    logger.info(f"Viscosity not computed: {visc_metadata.get('viscosity_error')}")
            except Exception as e:
                logger.warning(f"Viscosity calculation failed: {e}")

            # Calculate CED — skip for single_molecule_vacuum
            # (single molecule has no intermolecular interactions; CED is undefined.
            # The vacuum run IS the source of E_intra, so CED would be circular.)
            raw_study = getattr(run_result, "study_type", "bulk")
            study_type_str = raw_study.value if hasattr(raw_study, "value") else str(raw_study)
            if study_type_str != "single_molecule_vacuum":
                try:
                    mol_counts = getattr(run_result, "mol_counts", None) or {}
                    if study_type_str == "layer_bulkff" and not mol_counts:
                        logger.warning(
                            "Skipping CED for layered run without mol_counts provenance (exp=%s)",
                            getattr(run_result, "exp_id", "?"),
                        )
                        ced_metric = None
                    else:
                        # PR 2 (Method 1a SSOT, Codex Round 3): resolve the bulk
                        # read method from explicit data, not ambient env:
                        #   1. ``run_result.e_intra_method`` (input-generation SSOT)
                        #   2. ``run_result.metadata_json["e_intra_method"]``
                        #   3. ``self.bulk_e_intra_method`` (explicit override)
                        #   4. legacy default ``single_molecule_vacuum``
                        # The env-driven path was removed because process state
                        # is not the right SSOT for *reads* — the experiment /
                        # run carries its own method tag.
                        bulk_e_intra_method = (
                            getattr(run_result, "e_intra_method", None)
                            or (getattr(run_result, "metadata_json", None) or {}).get(
                                "e_intra_method"
                            )
                            or getattr(self, "bulk_e_intra_method", None)
                            or "single_molecule_vacuum"
                        )
                        ced_metric = self.ced_calc.calculate_from_thermo(
                            thermo_data=thermo_data,
                            mol_counts=mol_counts,
                            ff_name=getattr(run_result, "force_field", None) or "GAFF2",
                            ff_version=getattr(run_result, "ff_version", None) or get_ff_version(),
                            window_ps=self.window_ps,
                            dt_fs=self.dt_fs,
                            thermo_interval=self.thermo_interval,
                            use_window_ps=True,
                            temperature_K=getattr(run_result, "temperature_K", 298.0),
                            e_intra_method=bulk_e_intra_method,
                        )
                    if ced_metric:
                        metrics.append(ced_metric)
                except Exception as e:
                    logger.warning(f"CED calculation failed: {e}")
            else:
                logger.info(
                    "Skipping CED for single_molecule_vacuum (exp=%s)",
                    getattr(run_result, "exp_id", "?"),
                )

            # Calculate layered per-layer CED profile (binder-backed layers only)
            try:
                layer_profile_metric = self._calculate_layer_ced_profile(
                    thermo_data=thermo_data,
                    run_result=run_result,
                )
                if layer_profile_metric is not None:
                    metrics.append(layer_profile_metric)
            except Exception as e:
                logger.warning(f"Layered CED profile calculation failed: {e}")

            # Calculate E_inter from c_gg_* thermo columns (Phase 4.2)
            try:
                spec = run_result.group_energy_spec
                e_inter_metrics = self._calculate_e_inter(
                    thermo_data=thermo_data,
                    atom_counts=spec.atom_counts if spec else None,
                    additive_pair_label=spec.additive_pair_label if spec else None,
                    layer_index=getattr(run_result, "layer_index", None),
                    interface_index=getattr(run_result, "interface_index", None),
                )
                metrics.extend(e_inter_metrics)
            except Exception as e:
                logger.warning(f"E_inter calculation failed: {e}")

            # Layer interaction v2 (array metrics, Phase 5)
            if (
                spec
                and spec.group_selectors
                and spec.layer_count
                and spec.layer_count >= 2
                and study_type_str == "layer_bulkff"
            ):
                try:
                    layer_metrics = self._calculate_layer_interactions(
                        thermo_data=thermo_data,
                        group_spec=spec,
                        interface_area_nm2=getattr(run_result, "interface_area_nm2", None),
                        run_result=run_result,
                    )
                    metrics.extend(layer_metrics)
                except Exception as e:
                    logger.warning("Layer interaction v2 calculation failed: %s", e)

            # Calculate pair-type RDF with input validation (Phase 4.2)
            spec = run_result.group_energy_spec
            if run_result.dump_files and spec and spec.groups and len(spec.groups) >= 2:
                try:
                    group_assignments = self._build_group_assignments_from_dump(
                        dump_files=run_result.dump_files,
                        group_energy_spec=spec,
                    )
                    if group_assignments:
                        pair_rdf_metrics = self._calculate_pair_rdf(
                            dump_files=run_result.dump_files,
                            group_assignments=group_assignments,
                            exp_id=run_result.exp_id,
                        )
                        metrics.extend(pair_rdf_metrics)
                except Exception as e:
                    logger.warning(f"Pair RDF calculation failed: {e}")

            # Calculate tensile metrics from stress_strain_*.dat (Phase 4.3)
            try:
                tensile_metrics = self._calculate_tensile(run_result)
                metrics.extend(tensile_metrics)
            except Exception as e:
                logger.warning(f"Tensile metric calculation failed: {e}")

            # Store thermo_log as Parquet (Curve Analysis Phase 2)
            if self.array_storage is not None and run_result.exp_id is not None:
                try:
                    thermo_metric = self._store_thermo_log(
                        thermo_data=thermo_data,
                        exp_id=run_result.exp_id,
                    )
                    if thermo_metric is not None:
                        metrics.append(thermo_metric)
                except Exception as e:
                    logger.warning(f"Thermo log storage failed: {e}")

        return metrics

    def calculate_density(self, thermo_data: ThermoData) -> MetricResult:
        """
        Calculate density metric from thermo data.

        Args:
            thermo_data: LAMMPS thermo data

        Returns:
            MetricResult for density
        """
        summary = self.thermo_extractor.extract_summary(thermo_data.model_dump())
        return self.density_calc.create_metric(
            density_gcc=summary.density_gcc,
            std_dev=summary.density_std,
            temperature_K=summary.temperature_K,
            pressure_atm=summary.pressure_atm,
        )

    def calculate_ced(
        self,
        thermo_data: ThermoData,
        mol_counts: dict[str, int],
        ff_name: str,
        ff_version: str,
        use_window_ps: bool = True,
        temperature_K: float = 298.0,
        e_intra_method: str = "single_molecule_vacuum",
    ) -> MetricResult:
        """
        Calculate CED metric from thermo data (BULK-ONLY low-level helper).

        IMPORTANT: This helper is intended for bulk systems where intermolecular
        interactions exist. It does NOT apply the study_type gate that the main
        ``calculate()`` method uses to skip CED for ``single_molecule_vacuum``
        runs. Callers must ensure they only invoke this for bulk-equivalent
        systems; otherwise the result is physically meaningless.

        Args:
            thermo_data: LAMMPS thermo data
            mol_counts: Molecule counts
            ff_name: Force field name
            ff_version: Force field version
            use_window_ps: If True, use window_ps method. If False, use skip_fraction.
            temperature_K: Temperature for exact E_intra lookup.
            e_intra_method: E_intra method tag (PR 2 SSOT).  Defaults to
                Method 1 vacuum baseline so existing callers keep behaviour.

        Returns:
            MetricResult for CED
        """
        ced_result = self.ced_calc.calculate_from_thermo(
            thermo_data=thermo_data.model_dump(),
            mol_counts=mol_counts,
            ff_name=ff_name,
            ff_version=ff_version,
            window_ps=self.window_ps,
            dt_fs=self.dt_fs,
            thermo_interval=self.thermo_interval,
            use_window_ps=use_window_ps,
            temperature_K=temperature_K,
            e_intra_method=e_intra_method,
        )
        if ced_result is None:
            raise ValueError("CED calculation returned None")
        return ced_result

    def _calculate_layer_ced_profile(
        self,
        *,
        thermo_data: dict[str, list[float]],
        run_result: LAMMPSRunResult,
    ) -> MetricResult | None:
        """Calculate binder-backed per-layer CED profile for layered runs."""
        study_type = getattr(run_result, "study_type", "")
        study_type_str = study_type.value if hasattr(study_type, "value") else str(study_type)
        if study_type_str != "layer_bulkff":
            return None
        if not self.array_storage:
            logger.warning("Layered CED profile skipped: array_storage not available")
            return None
        exp_id = getattr(run_result, "exp_id", None)
        if not exp_id:
            logger.warning("Layered CED profile skipped: exp_id not available")
            return None
        layer_labels = list(getattr(run_result, "layer_labels", None) or [])
        mol_counts_by_layer = dict(getattr(run_result, "mol_counts_by_layer", None) or {})
        layer_volumes_A3 = dict(getattr(run_result, "layer_volumes_A3", None) or {})
        if not (layer_labels and mol_counts_by_layer and layer_volumes_A3):
            return None

        metric = self.ced_calc.calculate_layer_profile_from_thermo(
            thermo_data,
            mol_counts_by_layer=mol_counts_by_layer,
            layer_volumes_A3=layer_volumes_A3,
            layer_labels=layer_labels,
            ff_name=getattr(run_result, "force_field", None) or "GAFF2",
            ff_version=getattr(run_result, "ff_version", None) or get_ff_version(),
            window_ps=self.window_ps,
            dt_fs=self.dt_fs,
            thermo_interval=self.thermo_interval,
            temperature_K=getattr(run_result, "temperature_K", 298.0),
            e_intra_method=(
                getattr(run_result, "e_intra_method", None)
                or (getattr(run_result, "metadata_json", None) or {}).get("e_intra_method")
                or getattr(self, "bulk_e_intra_method", None)
                or "single_molecule_vacuum"
            ),
        )
        if metric is None:
            return None

        summary = dict(metric.array_summary or {})
        rows = summary.pop("profile_rows", None) or []
        if not rows:
            return None
        arr_data = {
            "layer_index": [row["layer_index"] for row in rows],
            "layer_label": [row["layer_label"] for row in rows],
            "ced_MJ_m3": [row["ced_MJ_m3"] for row in rows],
            "volume_A3": [row["volume_A3"] for row in rows],
        }
        arr_storage = self.array_storage.store_metric(
            metric_name="cohesive_energy_density_profile",
            experiment_id=exp_id,
            data=arr_data,
            summary={"n_layers": float(len(rows))},
            metadata=summary,
        )
        metric.array_storage = arr_storage
        metric.array_summary = summary
        metric.exp_id = exp_id
        return metric

    def get_density(self, run_result: LAMMPSRunResult) -> float | None:
        """
        Get density from run result.

        Args:
            run_result: LAMMPS run result

        Returns:
            Density in g/cm³ or None
        """
        log_path = Path(run_result.log_file)
        if not log_path.exists():
            return None

        log_result = self.log_parser.parse(log_path)
        summary = self.thermo_extractor.extract_summary(log_result.thermo_data)
        return summary.density_gcc if summary.density_gcc > 0 else None

    def get_ced(self, run_result: LAMMPSRunResult) -> float | None:
        """
        Get CED from run result.

        Args:
            run_result: LAMMPS run result

        Returns:
            CED in MPa or None
        """
        metrics = self.calculate(run_result)
        for metric in metrics:
            if metric.metric_name == "ced":
                return metric.value
        return None

    def validate_density(self, density: float) -> bool:
        """Validate if density is in acceptable range.

        Args:
            density: Density in g/cm³

        Returns:
            True if valid
        """
        _policy = DEFAULT_FAILURE_POLICY
        return _policy.physical_density_min < density < _policy.physical_density_max

    def get_density_trajectory(
        self,
        run_result: LAMMPSRunResult,
    ) -> DensityTimeSeries | None:
        """
        Get full density trajectory from run result.

        Returns all density values over time, plus statistics
        from the averaging window.

        Args:
            run_result: LAMMPS run result

        Returns:
            DensityTimeSeries with full trajectory or None
        """
        log_path = Path(run_result.log_file)
        if not log_path.exists():
            return None

        log_result = self.log_parser.parse(log_path)
        thermo_data = log_result.thermo_data

        # Get full trajectory
        trajectory = self.thermo_extractor.extract_full_trajectory(thermo_data)

        if "density_gcc" not in trajectory or not trajectory["density_gcc"]:
            return None

        # Calculate time series with statistics
        return self.density_calc.calculate_time_series(
            density_values=trajectory["density_gcc"],
            time_values=trajectory.get("time_ps"),
            window_ps=self.window_ps,
            dt_fs=self.dt_fs,
            thermo_interval=self.thermo_interval,
        )

    def get_full_thermo_trajectory(
        self,
        run_result: LAMMPSRunResult,
    ) -> dict[str, list[float]] | None:
        """
        Get full thermodynamic trajectory from run result.

        Returns all thermo values over time including density,
        temperature, pressure, and energies.

        Args:
            run_result: LAMMPS run result

        Returns:
            Dictionary with time_ps and all thermo columns
        """
        log_path = Path(run_result.log_file)
        if not log_path.exists():
            return None

        log_result = self.log_parser.parse(log_path)
        return self.thermo_extractor.extract_full_trajectory(log_result.thermo_data)

    def calculate_with_trajectory(
        self,
        run_result: LAMMPSRunResult,
    ) -> tuple[list[MetricResult], DensityTimeSeries | None]:
        """
        Calculate all metrics and return density trajectory.

        Args:
            run_result: LAMMPS run result

        Returns:
            Tuple of (metrics list, density time series)
        """
        metrics = self.calculate(run_result)
        trajectory = self.get_density_trajectory(run_result)
        return metrics, trajectory

    # ------------------------------------------------------------------
    # Thermo log Parquet storage
    # ------------------------------------------------------------------

    def _store_thermo_log(
        self,
        thermo_data: dict[str, list[float]],
        exp_id: str,
    ) -> MetricResult | None:
        """Store thermo log as Parquet via ArrayStorage.

        Maps thermo_extractor column names to registry-canonical names:
        step, time_ps, temp, press, pe, ke, vol, density,
        ebond, eangle, edihed, eimp, evdwl, ecoul, epair, emol, elong.

        Energy decomposition columns are included when present in the
        trajectory data (i.e. when thermo_style requested them).  Missing
        columns are simply omitted — no empty arrays are generated.

        Args:
            thermo_data: Raw thermo data from log parser.
            exp_id: Experiment ID.

        Returns:
            MetricResult for thermo_log or None if no data.
        """
        trajectory = self.thermo_extractor.extract_full_trajectory(thermo_data)
        if not trajectory or not trajectory.get("time_ps"):
            return None

        # Map to registry-canonical column names
        col_map = {
            "time_ps": "time_ps",
            "temperature_K": "temp",
            "pressure_atm": "press",
            "potential_energy": "pe",
            "kinetic_energy": "ke",
            "volume_A3": "vol",
            "density_gcc": "density",
            # Energy decomposition (present when thermo_style includes them)
            "ebond": "ebond",
            "eangle": "eangle",
            "edihed": "edihed",
            "eimp": "eimp",
            "evdwl": "evdwl",
            "ecoul": "ecoul",
            "epair": "epair",
            "emol": "emol",
            "elong": "elong",
        }

        # Build step column from time_ps
        data: dict[str, list[float]] = {}
        time_ps = trajectory["time_ps"]
        dt_ps = self.dt_fs / 1000.0 if self.dt_fs > 0 else 1.0
        data["step"] = [int(t / dt_ps) if dt_ps > 0 else i for i, t in enumerate(time_ps)]
        data["time_ps"] = time_ps

        for src_key, dst_key in col_map.items():
            if dst_key in data:
                continue
            values = trajectory.get(src_key)
            if values:
                data[dst_key] = list(values)

        n_points = len(time_ps)
        summary: dict[str, float] = {"n_points": float(n_points)}

        if self.array_storage is None:
            return None

        arr_storage = self.array_storage.store_metric(
            metric_name="thermo_log",
            experiment_id=exp_id,
            data=data,
            summary=summary,
        )

        return MetricResult(
            metric_name="thermo_log",
            value=None,
            unit=self.registry.get_unit("thermo_log"),
            namespace=self.registry.get_namespace("thermo_log"),
            array_storage=arr_storage,
            array_summary=summary,
        )

    # ------------------------------------------------------------------
    # Viscosity calculation
    # ------------------------------------------------------------------

    def _calculate_viscosity(
        self,
        thermo_data: dict[str, list[float]],
        log_path: Path,
        run_result: LAMMPSRunResult,
    ) -> tuple[list[MetricResult], dict[str, str | float | None]]:
        """Calculate viscosity from RNEMD f_viscosity thermo column.

        Uses the Muller-Plathe method: parses cumulative momentum
        transfer and (if available) the velocity profile.

        Args:
            thermo_data: Parsed thermo columns.
            log_path: Path to the LAMMPS log file.
            run_result: Full run result (for dump files / box dims).

        Returns:
            Tuple of (metric list, metadata dict).
        """
        import numpy as np

        empty_meta: dict[str, str | float | None] = {
            "viscosity_method": "rnemd_muller_plathe",
            "viscosity_parse_status": "skipped",
        }

        # 1. Find f_viscosity column
        f_col = ViscosityCalculator.find_f_viscosity_column(thermo_data)
        if f_col is None:
            empty_meta["viscosity_error"] = "f_viscosity column not found in thermo"
            return [], empty_meta

        f_values = thermo_data[f_col]
        if len(f_values) < 3:
            empty_meta["viscosity_error"] = f"Too few f_viscosity samples ({len(f_values)})"
            return [], empty_meta

        # 2. Reconstruct time axis for viscosity portion
        #    f_viscosity only appears in the viscosity run (last run).
        #    Use the last N entries from Step column.
        n_visc = len(f_values)
        step_col = thermo_data.get("Step", [])
        if len(step_col) >= n_visc:
            steps_visc = step_col[-n_visc:]
        else:
            steps_visc = list(range(n_visc))

        time_fs = np.array(steps_visc, dtype=np.float64) * self.dt_fs

        # 3. Box area: try log parsing, then volume fallback
        box_area: float | None = None
        try:
            log_content = log_path.read_text()
            box_area = ViscosityCalculator.extract_box_area_from_log(log_content)
        except OSError:
            pass

        if box_area is None:
            vol_values = thermo_data.get("Vol", [])
            if vol_values:
                avg_vol = float(np.mean(vol_values[-n_visc:]))
                box_area = ViscosityCalculator.estimate_box_area_from_volume(avg_vol)

        if box_area is None or box_area <= 0:
            empty_meta["viscosity_error"] = "Could not determine box area"
            return [], empty_meta

        # 4. Velocity profile (look in experiment directory)
        profile = None
        exp_dir = log_path.parent
        vprofile_files = sorted(exp_dir.glob("vprofile_*.dat"))
        if vprofile_files:
            profile = self.viscosity_calc.parse_velocity_profile(vprofile_files[-1])

        # 5. Compute viscosity
        result = self.viscosity_calc.compute_from_rnemd(
            f_viscosity_values=f_values,
            time_fs=time_fs,
            box_area_A2=box_area,
            velocity_profile=profile,
        )

        # 6. Build outputs
        metrics: list[MetricResult] = []
        scalar = self.viscosity_calc.create_scalar_metric(result)
        if scalar is not None:
            metrics.append(scalar)

        metadata = ViscosityCalculator.get_metadata(result)
        return metrics, metadata

    # ------------------------------------------------------------------
    # RDF calculation
    # ------------------------------------------------------------------

    def _calculate_rdf(
        self,
        dump_files: list[str],
        exp_id: str | None = None,
    ) -> list[MetricResult]:
        """Calculate RDF from dump trajectory file(s).

        Args:
            dump_files: List of dump file paths.
            exp_id: Experiment ID for array storage.

        Returns:
            List of MetricResult (scalar peaks + optional array curve).
        """
        return calculate_rdf_metrics(
            dump_files=dump_files,
            exp_id=exp_id,
            dump_parser=self.dump_parser,
            rdf_calc=self.rdf_calc,
            array_storage=self.array_storage,
        )

    # ------------------------------------------------------------------
    # MSD calculation
    # ------------------------------------------------------------------

    def _calculate_msd(
        self,
        dump_files: list[str],
        exp_id: str | None = None,
    ) -> list[MetricResult]:
        """Calculate MSD and diffusion coefficient from dump trajectory.

        Args:
            dump_files: List of dump file paths.
            exp_id: Experiment ID for array storage.

        Returns:
            List of MetricResult (scalar D + optional array MSD curve).
        """
        return calculate_msd_metrics(
            dump_files=dump_files,
            exp_id=exp_id,
            dt_fs=self.dt_fs,
            dump_parser=self.dump_parser,
            msd_calc=self.msd_calc,
            array_storage=self.array_storage,
        )

    # ------------------------------------------------------------------
    # Tensile metric calculation (Phase 4.3)
    # ------------------------------------------------------------------

    def _calculate_tensile(self, run_result: LAMMPSRunResult) -> list[MetricResult]:
        """Calculate tensile metrics from stress_strain_*.dat files.

        Args:
            run_result: LAMMPS run result (may contain tensile metadata).

        Returns:
            List of MetricResult (empty if no stress-strain files found).
        """
        exp_dir = Path(run_result.log_file).parent
        ss_files = sorted(exp_dir.glob("stress_strain_*.dat"))
        if not ss_files:
            return []

        ss_file = ss_files[-1]  # Use last tensile step
        logger.info(f"Parsing tensile data from {ss_file}")

        original_gap = getattr(run_result, "original_gap_angstrom", None)

        metrics = self.tensile_calc.calculate_from_file(
            ss_file=ss_file,
            original_gap_angstrom=original_gap,
            exp_id=run_result.exp_id,
            layer_index=getattr(run_result, "layer_index", None),
            interface_index=getattr(run_result, "interface_index", None),
        )

        # Store stress-strain curve array if storage available
        if self.array_storage is not None and run_result.exp_id is not None:
            try:
                data = self.tensile_calc.parser.parse(ss_file)
                array_metric = self.tensile_calc.create_array_metric(
                    data=data,
                    exp_id=run_result.exp_id,
                    array_storage=self.array_storage,
                )
                if array_metric is not None:
                    metrics.append(array_metric)
            except Exception as e:
                logger.warning(f"Stress-strain array storage failed: {e}")

        return metrics

    # ------------------------------------------------------------------
    # E_inter calculation (Phase 4.2)
    # ------------------------------------------------------------------

    def _calculate_e_inter(
        self,
        thermo_data: dict[str, list[float]],
        atom_counts: dict[str, int] | None = None,
        additive_pair_label: str | None = None,
        layer_index: int | None = None,
        interface_index: int | None = None,
    ) -> list[MetricResult]:
        """Calculate intermolecular energy from c_gg_* thermo columns.

        Extracts pairwise group/group energies from thermo data produced
        by LAMMPS compute group/group commands.

        Args:
            thermo_data: Parsed thermo data with c_gg_* columns.
            atom_counts: Optional {group_name: n_atoms} for per-atom normalization.
            additive_pair_label: Pair label for additive-binder metric.

        Returns:
            List of MetricResult (e_inter_total + optional e_inter_additive_binder).
        """
        result = self.e_inter_calc.compute(thermo_data, atom_counts=atom_counts)
        if result is None:
            return []

        return self.e_inter_calc.create_metrics(
            result,
            additive_pair_label=additive_pair_label,
            layer_index=layer_index,
            interface_index=interface_index,
        )

    # ------------------------------------------------------------------
    # Layer interaction v2 (Phase 5)
    # ------------------------------------------------------------------

    def _calculate_layer_interactions(
        self,
        thermo_data: dict[str, list[float]],
        group_spec: GroupEnergySpec,
        interface_area_nm2: float | None,
        run_result: "LAMMPSRunResult | None" = None,
    ) -> list[MetricResult]:
        """Calculate layer-pair interaction matrix and cross-cut profile.

        Produces array metrics only (no dynamic scalar names).
        Uses c_gg_L{i}_L{j} thermo columns from layer-indexed
        compute group/group commands.

        Args:
            thermo_data: Parsed thermo data with c_gg_L* columns.
            group_spec: GroupEnergySpec with layer_count and group_selectors.
            interface_area_nm2: Interface area for cross-cut normalization.
            run_result: LAMMPSRunResult for exp_id extraction.

        Returns:
            List of MetricResult for e_inter_layer_matrix and
            cross_cut_interaction_profile.
        """
        import re

        from metrics.layer_metrics import compute_cross_cut_interaction
        from parsers.stats_utils import apply_time_window, compute_mean_std

        # Guard: array_storage required for array metrics
        if not self.array_storage:
            logger.warning("Layer interaction metrics skipped: array_storage not available")
            return []

        exp_id = getattr(run_result, "exp_id", None) if run_result else None
        if not exp_id:
            logger.warning("Layer interaction metrics skipped: exp_id not available")
            return []

        layer_count = group_spec.layer_count
        if layer_count is None or layer_count < 2:
            logger.warning("Layer interaction metrics skipped: invalid layer_count=%s", layer_count)
            return []
        e_inter_matrix: dict[tuple[int, int], float] = {}
        matrix_rows: list[dict] = []

        for col_name, values in thermo_data.items():
            match = re.match(r"c_gg_L(\d+)_L(\d+)", col_name)
            if not match:
                continue
            i, j = int(match.group(1)), int(match.group(2))
            windowed = apply_time_window(
                values,
                window_ps=self.window_ps,
                dt_fs=self.dt_fs,
                thermo_interval=self.thermo_interval,
            )
            if not windowed:
                continue
            mean_e, _ = compute_mean_std(windowed)
            key = (min(i, j), max(i, j))
            e_inter_matrix[key] = mean_e
            matrix_rows.append({"pair_label": f"L{i}_L{j}", "e_inter": mean_e})

        metrics: list[MetricResult] = []

        # e_inter_layer_matrix (array metric with proper storage)
        if matrix_rows:
            data = {
                "pair_label": [r["pair_label"] for r in matrix_rows],
                "e_inter": [r["e_inter"] for r in matrix_rows],
            }
            storage_summary = {
                "layer_count": float(layer_count),
                "n_pairs": float(len(matrix_rows)),
            }
            summary: dict[str, int | float] = {
                "layer_count": layer_count,
                "n_pairs": len(matrix_rows),
            }
            arr_storage = self.array_storage.store_metric(
                metric_name="e_inter_layer_matrix",
                experiment_id=exp_id,
                data=data,
                summary=storage_summary,
            )
            metrics.append(
                MetricResult(
                    metric_name="e_inter_layer_matrix",
                    namespace="layer",
                    value=None,
                    unit=self.registry.get_unit("e_inter_layer_matrix"),
                    array_storage=arr_storage,
                    array_summary=summary,
                )
            )

        # cross_cut_interaction_profile (array metric with proper storage)
        if e_inter_matrix and interface_area_nm2 and interface_area_nm2 > 0:
            cut_rows: list[dict] = []
            for k in range(layer_count - 1):
                cut_val = compute_cross_cut_interaction(
                    e_inter_matrix, layer_count, interface_area_nm2, (k, k + 1)
                )
                cut_rows.append({"cut_index": k, "cross_cut_mJ_m2": cut_val})

            cut_data = {
                "cut_index": [r["cut_index"] for r in cut_rows],
                "cross_cut_mJ_m2": [r["cross_cut_mJ_m2"] for r in cut_rows],
            }
            cut_storage_summary = {
                "layer_count": float(layer_count),
                "n_cuts": float(len(cut_rows)),
                "is_enthalpic_proxy": 1.0,
            }
            cut_summary: dict[str, int | float | bool] = {
                "layer_count": layer_count,
                "n_cuts": len(cut_rows),
                "is_enthalpic_proxy": True,
            }
            arr_storage_cut = self.array_storage.store_metric(
                metric_name="cross_cut_interaction_profile",
                experiment_id=exp_id,
                data=cut_data,
                summary=cut_storage_summary,
            )
            metrics.append(
                MetricResult(
                    metric_name="cross_cut_interaction_profile",
                    namespace="layer",
                    value=None,
                    unit=self.registry.get_unit("cross_cut_interaction_profile"),
                    array_storage=arr_storage_cut,
                    array_summary=cut_summary,
                )
            )
        elif e_inter_matrix and not interface_area_nm2:
            logger.warning(
                "Layer interaction matrix computed but cross-cut profile skipped: "
                "interface_area_nm2 not available"
            )

        return metrics

    # ------------------------------------------------------------------
    # Pair-type RDF calculation (Phase 4.2)
    # ------------------------------------------------------------------

    def _calculate_pair_rdf(
        self,
        dump_files: list[str],
        group_assignments: dict[str, list[int]],
        exp_id: str | None = None,
    ) -> list[MetricResult]:
        """Calculate pair-type RDF between molecular groups.

        Computes g_AB(r) for each pair of groups (e.g., SARA categories)
        from dump trajectory files.

        Args:
            dump_files: List of dump file paths.
            group_assignments: {group_name: [atom_indices]} mapping.
                              Indices are 0-based into the positions array.
            exp_id: Experiment ID for array storage.

        Returns:
            List of MetricResult (optional array rdf_pair_curve).
        """
        return calculate_pair_rdf_metrics(
            dump_files=dump_files,
            group_assignments=group_assignments,
            exp_id=exp_id,
            dump_parser=self.dump_parser,
            pair_rdf_calc=self.pair_rdf_calc,
            array_storage=self.array_storage,
        )

    # ------------------------------------------------------------------
    # Group assignment from dump (Phase 4.2, feedback #4 + #7)
    # ------------------------------------------------------------------

    def _build_group_assignments_from_dump(
        self,
        dump_files: list[str],
        group_energy_spec: GroupEnergySpec,
    ) -> dict[str, list[int]] | None:
        """Build atom→group mapping from dump mol column.

        Validates mol column existence and mol-ID consistency against
        the GroupEnergySpec before constructing assignments.

        Args:
            dump_files: List of dump file paths.
            group_energy_spec: GroupEnergySpec with group→mol_id mapping.

        Returns:
            {group_name: [0-based atom indices]} or None if validation fails.
        """
        from metrics.group_assignment import GroupAssignmentBuilder

        # Parse first dump frame to get mol column
        first_frame = None
        for dump_path in dump_files:
            p = Path(dump_path)
            if not p.exists():
                continue
            for frame in self.dump_parser.parse_frames(p):
                first_frame = frame
                break
            if first_frame is not None:
                break

        if first_frame is None:
            logger.warning("No dump frames found for group assignment")
            return None

        # Check if mol column exists (feedback #7)
        if "mol" not in first_frame.columns:
            logger.warning("Dump file does not contain 'mol' column; skipping pair-RDF calculation")
            return None

        # Collect mol IDs from parsed atom dicts
        dump_mol_ids: set[int] = set()
        for atom_data in first_frame.atoms:
            mol_val = atom_data.get("mol")
            if mol_val is None:
                logger.warning("Dump atom entry missing 'mol' value; skipping pair-RDF calculation")
                return None
            dump_mol_ids.add(int(mol_val))

        # Verify mol-ID assumption (feedback #4)
        ga_builder = GroupAssignmentBuilder()
        if not ga_builder.verify_mol_ids(group_energy_spec, dump_mol_ids):
            logger.warning("mol-ID verification failed; skipping pair-RDF calculation")
            return None

        # Build reverse mapping: mol_id → group_name
        mol_to_group: dict[int, str] = {}
        for group_name, mol_ids in group_energy_spec.groups.items():
            for mid in mol_ids:
                mol_to_group[mid] = group_name

        # Build atom index → group assignment
        group_assignments: dict[str, list[int]] = {name: [] for name in group_energy_spec.groups}
        for atom_idx, atom_data in enumerate(first_frame.atoms):
            mol_val = atom_data.get("mol")
            if mol_val is None:
                continue
            mol_id = int(mol_val)
            assigned_group: str | None = mol_to_group.get(mol_id)
            if assigned_group is not None:
                group_assignments[assigned_group].append(atom_idx)

        # Filter out empty groups
        group_assignments = {k: v for k, v in group_assignments.items() if v}

        if len(group_assignments) < 2:
            logger.warning(
                f"Only {len(group_assignments)} non-empty groups found; "
                "need at least 2 for pair-RDF"
            )
            return None

        return group_assignments


# Alias for backward compatibility
MetricsCalculator = MetricCalculator
