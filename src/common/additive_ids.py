"""Canonical additive mol_id helpers with legacy alias compatibility."""

from __future__ import annotations

import re

# Canonical IDs aligned with additives.yaml keys.
_CANONICAL_TO_ALIASES: dict[str, tuple[str, ...]] = {
    "SBS": ("ADD_SBS_001",),
    "Elvaloy": ("ADD_ELVALOY_001",),
    "PPA": ("ADD_PPA_001",),
    "Sasobit": ("ADD_SASOBIT_001",),
    "NanoClay": ("ADD_NCLAY_001",),
    "CRM": ("ADD_CRM_001",),
}

_TYPE_TO_CANONICAL: dict[str, str] = {
    "sbs": "SBS",
    "elvaloy": "Elvaloy",
    "ppa": "PPA",
    "sasobit": "Sasobit",
    "nanoclay": "NanoClay",
    "nclay": "NanoClay",
    "crm": "CRM",
    "crumbrubbermodifier": "CRM",
    "crumbrubber": "CRM",
}

_ALIAS_TO_CANONICAL: dict[str, str] = {}
for _canonical, _aliases in _CANONICAL_TO_ALIASES.items():
    _ALIAS_TO_CANONICAL[_canonical.casefold()] = _canonical
    for _alias in _aliases:
        _ALIAS_TO_CANONICAL[_alias.casefold()] = _canonical


def _normalize_type_key(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", raw.strip().lower())


def canonicalize_additive_mol_id(mol_id: str | None) -> str | None:
    """Return canonical additive mol_id while accepting legacy aliases."""
    if mol_id is None:
        return None
    token = str(mol_id).strip()
    if not token:
        return None
    return _ALIAS_TO_CANONICAL.get(token.casefold(), token)


def infer_additive_mol_id(
    *,
    additive_type: str | None = None,
    mol_id: str | None = None,
) -> str | None:
    """Resolve best-effort canonical mol_id from mol_id and additive_type."""
    canonical = canonicalize_additive_mol_id(mol_id)
    if canonical:
        return canonical
    if additive_type is None:
        return None
    key = _normalize_type_key(additive_type)
    return _TYPE_TO_CANONICAL.get(key)


def expand_additive_mol_id_aliases(
    mol_id: str | None,
    *,
    additive_type: str | None = None,
) -> list[str]:
    """Return canonical+legacy alias list for filtering and compatibility."""
    canonical = infer_additive_mol_id(additive_type=additive_type, mol_id=mol_id)
    if canonical is None:
        raw = str(mol_id).strip() if mol_id else ""
        return [raw] if raw else []

    values: list[str] = [canonical]
    for alias in _CANONICAL_TO_ALIASES.get(canonical, ()):
        if alias not in values:
            values.append(alias)
    raw = str(mol_id).strip() if mol_id else ""
    if raw and raw not in values:
        values.append(raw)
    return values
