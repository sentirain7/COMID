"""
Metrics registry policy - SSOT for metric name/unit enforcement.

All sessions must use this registry for metric validation.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from contracts.policies.replicate import DEFAULT_REPLICATE_POLICY


class MetricType(StrEnum):
    """Metric data type."""

    SCALAR = "scalar"
    ARRAY = "array"


class MetricNamespace(StrEnum):
    """Metric namespace for categorization."""

    BULK_FF_GAFF2 = "bulk_ff_gaff2"
    REAXFF = "reaxff"
    LAYER = "layer"
    MECHANICAL = "mechanical"
    DERIVED = "derived"


class MetricDefinition(BaseModel):
    """Definition of a single metric."""

    name: str = Field(..., description="Metric name")
    unit: str = Field(..., description="Unit string")
    dtype: MetricType = Field(..., description="Data type")
    namespace: MetricNamespace = Field(..., description="Namespace")
    description: str = Field("", description="Human-readable description")
    array_columns: list[str] | None = Field(None, description="Column names for array metrics")
    produced: bool = Field(True, description="Whether the current codebase produces this metric")
    trainable: bool = Field(False, description="Whether current ML contracts train on this metric")
    llm_exposed: bool = Field(False, description="Whether LLM/runtime should expose this metric")
    supports_layer_index: bool = Field(
        False, description="Whether per-layer provenance is meaningful for this metric"
    )
    supports_interface_index: bool = Field(
        False, description="Whether per-interface provenance is meaningful for this metric"
    )
    requires_replicates: bool = Field(
        False,
        description=(
            "Whether this metric MUST be reported as a multi-replicate ensemble "
            "(mean ± standard error) rather than a single stochastic run. "
            "Stochastic interface-mechanical targets (tensile/debonding) set this "
            "so the replica aggregation path (metrics.interface_replicate) is the SSOT."
        ),
    )
    min_replicate_count: int = Field(
        1,
        ge=1,
        description=(
            "Minimum independent replicates (seeds/strain-rates) for an adequate "
            "ensemble. Mirrors ReplicatePolicy.min_seeds for replica-required metrics."
        ),
    )


class MetricsRegistry(BaseModel):
    """
    Metrics registry - SSOT for metric name/unit enforcement.

    This defines all valid metrics with their units and types.
    Parser and DB must validate against this registry.
    """

    metrics: dict[str, MetricDefinition] = Field(
        default={
            # Scalar bulk metrics
            "density": MetricDefinition(
                name="density",
                unit="g/cm3",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="System density from NPT average",
                trainable=True,
                llm_exposed=True,
            ),
            "cohesive_energy_density": MetricDefinition(
                name="cohesive_energy_density",
                unit="MJ/m3",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Cohesive energy density (CED)",
                trainable=True,
                llm_exposed=True,
            ),
            "bulk_modulus": MetricDefinition(
                name="bulk_modulus",
                unit="GPa",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Isothermal bulk modulus from NPT volume fluctuations",
                trainable=True,
                llm_exposed=True,
            ),
            "rdf_first_peak_r": MetricDefinition(
                name="rdf_first_peak_r",
                unit="angstrom",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="RDF first peak position",
                trainable=True,
            ),
            "rdf_first_peak_g": MetricDefinition(
                name="rdf_first_peak_g",
                unit="dimensionless",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="RDF first peak height",
                trainable=True,
            ),
            "rdf_coordination_number": MetricDefinition(
                name="rdf_coordination_number",
                unit="dimensionless",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Coordination number from RDF",
                trainable=True,
            ),
            "rdf_second_peak_r": MetricDefinition(
                name="rdf_second_peak_r",
                unit="angstrom",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="RDF second peak position",
            ),
            "rdf_second_peak_g": MetricDefinition(
                name="rdf_second_peak_g",
                unit="dimensionless",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="RDF second peak height",
            ),
            "msd_diffusion_coefficient": MetricDefinition(
                name="msd_diffusion_coefficient",
                unit="cm2/s",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Diffusion coefficient from MSD",
                trainable=True,
            ),
            "viscosity": MetricDefinition(
                name="viscosity",
                unit="mPa.s",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Dynamic viscosity",
                trainable=True,
                llm_exposed=True,
            ),
            "glass_transition_temperature_k": MetricDefinition(
                name="glass_transition_temperature_k",
                unit="K",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Glass transition temperature from density-T bilinear fitting",
                trainable=False,
                llm_exposed=False,
            ),
            # Thermodynamic metrics (from thermo output)
            "temperature": MetricDefinition(
                name="temperature",
                unit="K",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Average temperature from NPT production",
            ),
            "pressure": MetricDefinition(
                name="pressure",
                unit="atm",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Average pressure from NPT production",
            ),
            "potential_energy": MetricDefinition(
                name="potential_energy",
                unit="kcal/mol",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="System potential energy from NPT average",
            ),
            "kinetic_energy": MetricDefinition(
                name="kinetic_energy",
                unit="kcal/mol",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="System kinetic energy from NPT average",
            ),
            "total_energy": MetricDefinition(
                name="total_energy",
                unit="kcal/mol",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="System total energy from NPT average",
            ),
            "potential_energy_density": MetricDefinition(
                name="potential_energy_density",
                unit="kcal/mol/A3",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Potential energy per unit volume",
            ),
            "kinetic_energy_density": MetricDefinition(
                name="kinetic_energy_density",
                unit="kcal/mol/A3",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Kinetic energy per unit volume",
            ),
            "total_energy_density": MetricDefinition(
                name="total_energy_density",
                unit="kcal/mol/A3",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Total energy per unit volume",
            ),
            # Energy decomposition metrics (from LAMMPS thermo_style)
            "e_bond": MetricDefinition(
                name="e_bond",
                unit="kcal/mol",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Bond energy from LAMMPS thermo",
            ),
            "e_angle": MetricDefinition(
                name="e_angle",
                unit="kcal/mol",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Angle energy from LAMMPS thermo",
            ),
            "e_dihed": MetricDefinition(
                name="e_dihed",
                unit="kcal/mol",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Dihedral energy from LAMMPS thermo",
            ),
            "e_improper": MetricDefinition(
                name="e_improper",
                unit="kcal/mol",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Improper energy from LAMMPS thermo",
            ),
            "e_vdwl": MetricDefinition(
                name="e_vdwl",
                unit="kcal/mol",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Van der Waals pairwise energy",
            ),
            "e_coul": MetricDefinition(
                name="e_coul",
                unit="kcal/mol",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Coulombic pairwise energy",
            ),
            "e_pair": MetricDefinition(
                name="e_pair",
                unit="kcal/mol",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Total pairwise energy (vdwl+coul+long)",
            ),
            "e_mol": MetricDefinition(
                name="e_mol",
                unit="kcal/mol",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Molecular energy (bond+angle+dihed+imp)",
            ),
            "e_long": MetricDefinition(
                name="e_long",
                unit="kcal/mol",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Long-range kspace energy",
            ),
            # Intermolecular energy metrics (Phase 4.2)
            "e_inter_total": MetricDefinition(
                name="e_inter_total",
                unit="kcal/mol",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Total intermolecular energy from group/group compute",
                trainable=True,
            ),
            "e_inter_additive_binder": MetricDefinition(
                name="e_inter_additive_binder",
                unit="kcal/mol",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Additive-binder intermolecular energy",
            ),
            # Layer metrics
            "adhesion_energy": MetricDefinition(
                name="adhesion_energy",
                unit="mJ/m2",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.LAYER,
                description="Interface adhesion energy",
                produced=False,
                trainable=False,
                llm_exposed=True,
                supports_interface_index=True,
            ),
            "orientation_order": MetricDefinition(
                name="orientation_order",
                unit="dimensionless",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.LAYER,
                description="P2 orientational order parameter",
                produced=False,
                trainable=False,
                supports_interface_index=True,
            ),
            # Mechanical metrics
            # P1-7: 아래 4개는 interfacial_tensile_strength/work_of_separation과 동일한
            # 확률적 인장(stress-strain) 실행에서 산출되므로 동일하게 replica 앙상블 필수.
            "tensile_strength": MetricDefinition(
                name="tensile_strength",
                unit="MPa",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.MECHANICAL,
                description="Ultimate tensile strength",
                trainable=True,
                llm_exposed=True,
                requires_replicates=True,
                min_replicate_count=DEFAULT_REPLICATE_POLICY.min_seeds,
            ),
            "elastic_modulus": MetricDefinition(
                name="elastic_modulus",
                unit="GPa",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.MECHANICAL,
                description="Young's modulus",
                trainable=True,
                llm_exposed=True,
                requires_replicates=True,
                min_replicate_count=DEFAULT_REPLICATE_POLICY.min_seeds,
            ),
            "shear_modulus": MetricDefinition(
                name="shear_modulus",
                unit="GPa",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.MECHANICAL,
                description="Shear modulus",
                produced=False,
                trainable=False,
                llm_exposed=False,
            ),
            # Phase 4.3: Tensile/interface mechanical metrics
            "interfacial_tensile_strength": MetricDefinition(
                name="interfacial_tensile_strength",
                unit="MPa",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.MECHANICAL,
                description="Peak stress at interface debonding",
                trainable=True,
                llm_exposed=True,
                supports_interface_index=True,
                requires_replicates=True,
                min_replicate_count=DEFAULT_REPLICATE_POLICY.min_seeds,
            ),
            "work_of_separation": MetricDefinition(
                name="work_of_separation",
                unit="mJ/m2",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.MECHANICAL,
                description="Work required to separate interface",
                trainable=True,
                llm_exposed=True,
                supports_interface_index=True,
                requires_replicates=True,
                min_replicate_count=DEFAULT_REPLICATE_POLICY.min_seeds,
            ),
            "ductility": MetricDefinition(
                name="ductility",
                unit="dimensionless",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.MECHANICAL,
                description="Strain at peak stress (failure ductility)",
                trainable=True,
                llm_exposed=True,
                requires_replicates=True,
                min_replicate_count=DEFAULT_REPLICATE_POLICY.min_seeds,
            ),
            "toughness": MetricDefinition(
                name="toughness",
                unit="MJ/m3",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.MECHANICAL,
                description="Area under stress-strain curve",
                trainable=True,
                llm_exposed=True,
                requires_replicates=True,
                min_replicate_count=DEFAULT_REPLICATE_POLICY.min_seeds,
            ),
            # Array metrics
            "rdf_curve": MetricDefinition(
                name="rdf_curve",
                unit="[angstrom, dimensionless]",
                dtype=MetricType.ARRAY,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Full RDF curve data",
                array_columns=["r", "g_r"],
            ),
            "msd_curve": MetricDefinition(
                name="msd_curve",
                unit="[ps, angstrom2]",
                dtype=MetricType.ARRAY,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Full MSD curve data",
                array_columns=["time_ps", "msd"],
            ),
            "stress_strain_curve": MetricDefinition(
                name="stress_strain_curve",
                unit="[dimensionless, MPa]",
                dtype=MetricType.ARRAY,
                namespace=MetricNamespace.MECHANICAL,
                description="Stress-strain curve data",
                array_columns=["strain", "stress_MPa"],
            ),
            "density_profile": MetricDefinition(
                name="density_profile",
                unit="[angstrom, g/cm3]",
                dtype=MetricType.ARRAY,
                namespace=MetricNamespace.LAYER,
                description="Density profile along axis",
                array_columns=["z", "density"],
                produced=False,
                supports_interface_index=True,
            ),
            "rdf_pair_curve": MetricDefinition(
                name="rdf_pair_curve",
                unit="[angstrom, dimensionless, label]",
                dtype=MetricType.ARRAY,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Pair-type RDF curves for SARA group pairs",
                array_columns=["r", "g_r", "pair_label"],
            ),
            # Multi-layer interface E_inter metrics (Phase 4.2)
            "e_inter_interface_1": MetricDefinition(
                name="e_inter_interface_1",
                unit="kcal/mol",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.LAYER,
                description="E_inter at primary interface",
                produced=False,
                trainable=False,
                llm_exposed=True,
                supports_interface_index=True,
            ),
            "e_inter_interface_2": MetricDefinition(
                name="e_inter_interface_2",
                unit="kcal/mol",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.LAYER,
                description="E_inter at secondary interface",
                produced=False,
                supports_interface_index=True,
            ),
            "e_inter_layer_matrix": MetricDefinition(
                name="e_inter_layer_matrix",
                unit="[label, kcal/mol]",
                dtype=MetricType.ARRAY,
                namespace=MetricNamespace.LAYER,
                description="Full layer-pair E_inter matrix",
                array_columns=["pair_label", "e_inter"],
                produced=True,
                supports_layer_index=True,
                supports_interface_index=True,
            ),
            "cohesive_energy_density_profile": MetricDefinition(
                name="cohesive_energy_density_profile",
                unit="[index, label, MJ/m3, angstrom3]",
                dtype=MetricType.ARRAY,
                namespace=MetricNamespace.LAYER,
                description=(
                    "Per-layer cohesive energy density profile for binder-backed "
                    "layers in a layered structure."
                ),
                array_columns=["layer_index", "layer_label", "ced_MJ_m3", "volume_A3"],
                produced=True,
                supports_layer_index=True,
            ),
            "cross_cut_interaction_profile": MetricDefinition(
                name="cross_cut_interaction_profile",
                unit="[index, mJ/m2]",
                dtype=MetricType.ARRAY,
                namespace=MetricNamespace.LAYER,
                description=(
                    "Cross-cut enthalpic interaction proxy at each cut plane. "
                    "NOT thermodynamic work of adhesion."
                ),
                array_columns=["cut_index", "cross_cut_mJ_m2"],
                produced=True,
                supports_interface_index=True,
            ),
            "thermo_log": MetricDefinition(
                name="thermo_log",
                unit="mixed",
                dtype=MetricType.ARRAY,
                namespace=MetricNamespace.BULK_FF_GAFF2,
                description="Full thermo log data",
                array_columns=[
                    "step",
                    "time_ps",
                    "temp",
                    "press",
                    "pe",
                    "ke",
                    "vol",
                    "density",
                    "ebond",
                    "eangle",
                    "edihed",
                    "eimp",
                    "evdwl",
                    "ecoul",
                    "epair",
                    "emol",
                    "elong",
                ],
            ),
            # ── Derived metrics (composition-based, no simulation) ──
            "ghg_emission": MetricDefinition(
                name="ghg_emission",
                unit="kgCO2e/kg",
                dtype=MetricType.SCALAR,
                namespace=MetricNamespace.DERIVED,
                description="Cradle-to-gate GHG emission factor (composition-weighted)",
                produced=False,
            ),
        },
        description="All registered metrics",
    )

    def is_valid_metric(self, name: str) -> bool:
        """Check if metric name is valid."""
        return name in self.metrics

    def get_unit(self, name: str) -> str:
        """Get unit for a metric."""
        if name not in self.metrics:
            raise ValueError(f"Unknown metric: {name}")
        return self.metrics[name].unit

    def get_type(self, name: str) -> MetricType:
        """Get data type for a metric."""
        if name not in self.metrics:
            raise ValueError(f"Unknown metric: {name}")
        return self.metrics[name].dtype

    def get_namespace(self, name: str) -> MetricNamespace:
        """Get namespace for a metric."""
        if name not in self.metrics:
            raise ValueError(f"Unknown metric: {name}")
        return self.metrics[name].namespace

    def get_definition(self, name: str) -> MetricDefinition:
        """Get full definition for a metric."""
        if name not in self.metrics:
            raise ValueError(f"Unknown metric: {name}")
        return self.metrics[name]

    def validate_metric(self, name: str, unit: str, namespace: str) -> tuple[bool, str | None]:
        """
        Validate a metric against the registry.

        Args:
            name: Metric name
            unit: Unit string
            namespace: Namespace string

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not self.is_valid_metric(name):
            return False, f"Unknown metric: {name}"

        definition = self.metrics[name]

        if unit != definition.unit:
            return False, f"Unit mismatch for {name}: {unit} != {definition.unit}"

        if namespace != definition.namespace.value:
            return (
                False,
                f"Namespace mismatch for {name}: {namespace} != {definition.namespace.value}",
            )

        return True, None

    def list_scalar_metrics(self, namespace: str | None = None) -> list[str]:
        """List all scalar metric names, optionally filtered by namespace."""
        result = []
        for name, defn in self.metrics.items():
            if defn.dtype == MetricType.SCALAR:
                if namespace is None or defn.namespace.value == namespace:
                    result.append(name)
        return result

    def list_array_metrics(self, namespace: str | None = None) -> list[str]:
        """List all array metric names, optionally filtered by namespace."""
        result = []
        for name, defn in self.metrics.items():
            if defn.dtype == MetricType.ARRAY:
                if namespace is None or defn.namespace.value == namespace:
                    result.append(name)
        return result

    def get_array_columns(self, name: str) -> list[str] | None:
        """Get column names for an array metric."""
        if name not in self.metrics:
            raise ValueError(f"Unknown metric: {name}")
        return self.metrics[name].array_columns

    def is_trainable(self, name: str) -> bool:
        """Return whether a metric is currently trainable."""
        return self.get_definition(name).trainable

    def is_llm_exposed(self, name: str) -> bool:
        """Return whether a metric should be exposed to LLM/runtime callers."""
        return self.get_definition(name).llm_exposed

    def is_produced(self, name: str) -> bool:
        """Return whether the current codebase produces this metric."""
        return self.get_definition(name).produced

    def requires_replicates(self, name: str) -> bool:
        """Return whether a metric must be reported as a replicate ensemble (mean ± SE)."""
        return self.get_definition(name).requires_replicates

    def min_replicate_count(self, name: str) -> int:
        """Return the minimum adequate replicate count for a metric."""
        return self.get_definition(name).min_replicate_count

    def replica_required_metrics(self) -> list[str]:
        """List metric names that must be reported as replicate ensembles (SSOT)."""
        return [n for n, d in self.metrics.items() if d.requires_replicates]


# Default instance for convenience
DEFAULT_METRICS_REGISTRY = MetricsRegistry()
