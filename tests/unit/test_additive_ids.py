"""Unit tests for common.additive_ids canonicalization helpers."""

from common.additive_ids import (
    canonicalize_additive_mol_id,
    expand_additive_mol_id_aliases,
    infer_additive_mol_id,
)


def test_canonicalize_legacy_alias_to_ssot():
    assert canonicalize_additive_mol_id("ADD_SBS_001") == "SBS"
    assert canonicalize_additive_mol_id("add_ppa_001") == "PPA"


def test_canonicalize_keeps_unknown_identifier():
    assert canonicalize_additive_mol_id("CUSTOM_ADD_X") == "CUSTOM_ADD_X"


def test_infer_from_additive_type_when_mol_id_missing():
    assert infer_additive_mol_id(additive_type="NanoClay", mol_id=None) == "NanoClay"
    assert infer_additive_mol_id(additive_type="crumb-rubber", mol_id=None) == "CRM"


def test_expand_aliases_contains_canonical_and_legacy():
    aliases = expand_additive_mol_id_aliases("ADD_SASOBIT_001")
    assert aliases[0] == "Sasobit"
    assert "ADD_SASOBIT_001" in aliases
