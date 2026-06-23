"""Experiment service facade."""

from common.pathing import parse_exp_id
from contracts.policies.binders import get_default_binder_config

from .query import (
    batch_cancel_experiments,
    batch_delete_experiments,
    batch_retry_experiments,
    cancel_experiment,
    delete_experiment,
    get_experiment,
    get_experiment_filter_options,
    get_experiment_thermo,
    list_experiments,
    retry_experiment,
)
from .submission import (
    check_typing_charge_readiness,
    precompute_typing_charge,
    prepare_typing_charge_background,
    preview_molecule_composition,
    submit_dependent_molecule_experiment,
    submit_experiment,
    submit_molecule_experiment,
)


def default_binder_config() -> dict:
    """Expose default binder config for reuse."""
    return get_default_binder_config()


def parse_material_from_exp_id(exp_id: str) -> dict:
    """Expose exp-id parse for startup reuse."""
    return parse_exp_id(exp_id)


__all__ = [
    "batch_cancel_experiments",
    "batch_delete_experiments",
    "batch_retry_experiments",
    "cancel_experiment",
    "check_typing_charge_readiness",
    "default_binder_config",
    "delete_experiment",
    "get_experiment",
    "get_experiment_filter_options",
    "get_experiment_thermo",
    "list_experiments",
    "parse_material_from_exp_id",
    "precompute_typing_charge",
    "prepare_typing_charge_background",
    "preview_molecule_composition",
    "retry_experiment",
    "submit_dependent_molecule_experiment",
    "submit_experiment",
    "submit_molecule_experiment",
]
