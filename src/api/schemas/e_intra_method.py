"""Shared validators for public submission/settings E_intra method fields."""

from __future__ import annotations

from contracts.schema_enums import EIntraMethod, coerce_e_intra_method


def validate_submission_e_intra_method(value: str | None) -> str | None:
    """Validate only currently supported public submission methods.

    Method 2 (``single_molecule_periodic``) remains a reserved enum value for
    future internal/experimental use. Public submit/settings surfaces must not
    accept it until the end-to-end workflow exists.
    """
    if value is None:
        return None
    method = coerce_e_intra_method(value)
    if method is EIntraMethod.SINGLE_MOLECULE_PERIODIC:
        raise ValueError(
            "single_molecule_periodic is reserved for a future workflow and "
            "is not supported in public submission/settings APIs yet"
        )
    return method.value
