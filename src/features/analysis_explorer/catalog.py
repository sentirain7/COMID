"""Static dataset catalog for Analysis Explorer."""

from __future__ import annotations

from api.schemas.analysis_explorer import DatasetCatalogEntry, DatasetDimensionDef, DatasetMetricDef

_CHART_TYPES_ALL = ["scatter", "line", "bar", "scatter3d", "table"]

CATALOG: list[DatasetCatalogEntry] = [
    DatasetCatalogEntry(
        mode="bulk_binder_cell",
        label="Bulk Binder Cell",
        dimensions=[
            DatasetDimensionDef(key="binder_type", label="Binder Type"),
            DatasetDimensionDef(key="aging_state", label="Aging State"),
            DatasetDimensionDef(key="additive", label="Additive"),
            DatasetDimensionDef(key="additive_wt", label="Additive wt%", type="continuous"),
            DatasetDimensionDef(key="temperature_K", label="Temperature (K)", type="continuous"),
            DatasetDimensionDef(key="run_tier", label="Run Tier"),
            DatasetDimensionDef(key="ff_type", label="Force Field"),
            DatasetDimensionDef(key="structure_size", label="Structure Size"),
        ],
        metrics=[
            DatasetMetricDef(key="density", label="Density", unit="g/cm3"),
            DatasetMetricDef(key="cohesive_energy_density", label="CED", unit="MJ/m3"),
            DatasetMetricDef(key="viscosity", label="Viscosity", unit="mPa-s"),
            DatasetMetricDef(
                key="msd_diffusion_coefficient", label="Diffusion Coeff", unit="cm2/s"
            ),
            DatasetMetricDef(key="total_energy", label="Total Energy", unit="kcal/mol"),
            DatasetMetricDef(key="potential_energy", label="Potential Energy", unit="kcal/mol"),
            DatasetMetricDef(key="kinetic_energy", label="Kinetic Energy", unit="kcal/mol"),
            DatasetMetricDef(key="rdf_first_peak_r", label="RDF First Peak r", unit="Å"),
            DatasetMetricDef(key="rdf_first_peak_g", label="RDF First Peak g", unit=""),
            DatasetMetricDef(
                key="rdf_coordination_number", label="RDF Coordination Number", unit=""
            ),
            DatasetMetricDef(key="e_inter_total", label="E_inter Total", unit="kcal/mol"),
            DatasetMetricDef(
                key="glass_transition_temperature_k",
                label="Glass Transition Temp",
                unit="K",
            ),
            DatasetMetricDef(key="ghg_emission", label="GHG Emission", unit="kgCO2e/kg"),
        ],
        array_metrics=[
            DatasetMetricDef(key="rdf_curve", label="RDF Curve", unit="[Å, -]"),
            DatasetMetricDef(key="msd_curve", label="MSD Curve", unit="[ps, Å²]"),
            DatasetMetricDef(key="rdf_pair_curve", label="Pair RDF Curve", unit="[Å, -, label]"),
            DatasetMetricDef(key="thermo_log", label="Thermo Log", unit="mixed"),
        ],
        chart_types=_CHART_TYPES_ALL,
        default_chart="scatter",
        default_x="temperature_K",
        default_y="density",
        default_series="aging_state",
    ),
    DatasetCatalogEntry(
        mode="single_molecule",
        label="Single Molecule",
        dimensions=[
            DatasetDimensionDef(key="mol_id", label="Molecule ID"),
            DatasetDimensionDef(key="name", label="Name"),
            DatasetDimensionDef(key="sara_type", label="SARA Type"),
            DatasetDimensionDef(key="temperature_K", label="Temperature (K)", type="continuous"),
            DatasetDimensionDef(key="ff_name", label="FF Name"),
            DatasetDimensionDef(key="ff_version", label="FF Version"),
        ],
        metrics=[
            DatasetMetricDef(key="e_intra", label="E_intra", unit="kcal/mol"),
            DatasetMetricDef(key="n_samples", label="N Samples", unit=""),
            DatasetMetricDef(key="averaging_window_ps", label="Avg Window", unit="ps"),
            DatasetMetricDef(key="molecular_weight", label="MW", unit="g/mol"),
            DatasetMetricDef(key="num_atoms", label="Atom Count", unit=""),
        ],
        chart_types=_CHART_TYPES_ALL,
        default_chart="scatter",
        default_x="temperature_K",
        default_y="e_intra",
        default_series="sara_type",
    ),
    DatasetCatalogEntry(
        mode="layered_structure",
        label="Layered Structure",
        dimensions=[
            DatasetDimensionDef(key="layer_type", label="Layer Type"),
            DatasetDimensionDef(key="crystal_material", label="Crystal Material"),
            DatasetDimensionDef(key="crystal_surface", label="Crystal Surface"),
            DatasetDimensionDef(key="binder_type", label="Binder Type"),
            DatasetDimensionDef(key="aging_state", label="Aging State"),
            DatasetDimensionDef(key="binder_type_secondary", label="Binder Type (2nd)"),
            DatasetDimensionDef(key="aging_state_secondary", label="Aging State (2nd)"),
            DatasetDimensionDef(key="has_water", label="Has Water"),
            DatasetDimensionDef(key="temperature_K", label="Temperature (K)", type="continuous"),
            DatasetDimensionDef(key="additive_type", label="Additive"),
            DatasetDimensionDef(key="additive_wt", label="Additive wt%", type="continuous"),
        ],
        metrics=[
            DatasetMetricDef(key="density", label="Density", unit="g/cm3"),
            DatasetMetricDef(key="cohesive_energy_density", label="CED", unit="MJ/m3"),
            DatasetMetricDef(key="e_inter_total", label="E_inter Total", unit="kcal/mol"),
            DatasetMetricDef(key="tensile_strength", label="Tensile Strength", unit="MPa"),
            DatasetMetricDef(key="elastic_modulus", label="Elastic Modulus", unit="GPa"),
            DatasetMetricDef(key="ductility", label="Ductility", unit=""),
            DatasetMetricDef(key="toughness", label="Toughness", unit="MJ/m3"),
            DatasetMetricDef(key="work_of_separation", label="Work of Separation", unit="mJ/m2"),
            DatasetMetricDef(
                key="interfacial_tensile_strength", label="Interfacial Tensile Strength", unit="MPa"
            ),
        ],
        array_metrics=[
            DatasetMetricDef(
                key="stress_strain_curve", label="Stress-Strain Curve", unit="[-, MPa]"
            ),
            DatasetMetricDef(
                key="e_inter_layer_matrix",
                label="Layer Interaction Matrix",
                unit="[label, kcal/mol]",
            ),
            DatasetMetricDef(
                key="cross_cut_interaction_profile",
                label="Cross-Cut Profile",
                unit="[index, mJ/m2]",
            ),
        ],
        chart_types=_CHART_TYPES_ALL,
        default_chart="bar",
        default_x="crystal_material",
        default_y="work_of_separation",
        default_series="layer_type",
    ),
]

CATALOG_BY_MODE = {c.mode: c for c in CATALOG}
