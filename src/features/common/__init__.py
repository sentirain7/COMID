"""Common feature utilities."""

__all__ = [
    "as_workspace_relative",
    "canonical_value_key",
    "density_from_total_mass",
    "group_sort_key",
    "is_interface_like_source",
    "is_water_like_source",
    "list_canonical_sources",
    "list_legacy_only_sources",
    "normalize_source_type",
    "resolve_interface_source",
    "resolve_workspace_path",
    "run_in_session",
    "run_in_session_async",
    "run_in_session_commit",
    "with_optional_session",
    "stable_sort_records",
    "total_mass_from_types",
]


def __getattr__(name: str):
    if name in {
        "run_in_session",
        "run_in_session_async",
        "run_in_session_commit",
        "with_optional_session",
    }:
        from .db import (
            run_in_session,
            run_in_session_async,
            run_in_session_commit,
            with_optional_session,
        )

        return {
            "run_in_session": run_in_session,
            "run_in_session_async": run_in_session_async,
            "run_in_session_commit": run_in_session_commit,
            "with_optional_session": with_optional_session,
        }[name]
    if name in {"density_from_total_mass", "total_mass_from_types"}:
        from .density import density_from_total_mass, total_mass_from_types

        return {
            "density_from_total_mass": density_from_total_mass,
            "total_mass_from_types": total_mass_from_types,
        }[name]
    if name in {"as_workspace_relative", "resolve_workspace_path"}:
        from .workspace import as_workspace_relative, resolve_workspace_path

        return {
            "as_workspace_relative": as_workspace_relative,
            "resolve_workspace_path": resolve_workspace_path,
        }[name]
    if name in {"normalize_source_type", "is_interface_like_source"}:
        from .source_compat import is_interface_like_source, normalize_source_type

        return {
            "normalize_source_type": normalize_source_type,
            "is_interface_like_source": is_interface_like_source,
        }[name]
    if name in {
        "resolve_interface_source",
        "list_canonical_sources",
        "list_legacy_only_sources",
        "is_water_like_source",
    }:
        from .interface_sources import (
            is_water_like_source,
            list_canonical_sources,
            list_legacy_only_sources,
            resolve_interface_source,
        )

        return {
            "resolve_interface_source": resolve_interface_source,
            "list_canonical_sources": list_canonical_sources,
            "list_legacy_only_sources": list_legacy_only_sources,
            "is_water_like_source": is_water_like_source,
        }[name]
    if name in {"canonical_value_key", "group_sort_key", "stable_sort_records"}:
        from .canonical_ordering import canonical_value_key, group_sort_key, stable_sort_records

        return {
            "canonical_value_key": canonical_value_key,
            "group_sort_key": group_sort_key,
            "stable_sort_records": stable_sort_records,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
