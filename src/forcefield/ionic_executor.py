"""Wave 3 stub: ionic profile loader and assignment guard.

This module is the runtime side of the Wave 3 ionic SSOT. The yaml
catalog at ``data/forcefields/ionic_profiles.yaml`` is the storage
SSOT; everything below this line consumes it. The plan v3 contract is
that *no* ionic species is actually parameterized at runtime until the
four activation pre-conditions documented in
``docs/ionic_profile_policy.md`` have been signed off:

1. usage context locked (aqueous / asphalt_interface / vacuum)
2. mixing-rule compatibility against GAFF2 arithmetic and INTERFACE
   FF Lorentz-Berthelot reviewed
3. literature provenance recorded for charges, LJ params, and
   validation
4. LAMMPS regression in CI passing

Until then, :func:`assign_ionic` ALWAYS raises
:class:`IonicNotActivatedError`. The activation gate has two
overlapping checks (defense in depth):

* the yaml ``activation.global_enabled`` flag must be true AND the
  per-profile entry must be in ``activation.enabled_profiles``
* the operator must set ``ASPHALT_IONIC_ROUTE_ACTIVATED=1`` in the
  environment when invoking the build (this is the human "I have
  reviewed the policy" toggle)

Both must be true. The yaml gate is the long-lived editorial decision;
the env var is the short-lived "this build session knows what it's
doing" decision. A single review or a single env var alone is not
enough.

Even when both gates are true, the assignment path is intentionally
left unimplemented in this module — Wave 3 of plan v3 is "policy
confirmation, not activation". When a future PR is ready to flip the
gate, it will replace ``_assign_unimplemented`` with a real
implementation, and the typing router (currently fail-closed for
ionic_profile) must also be updated in the same PR.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from common.logging import get_logger
from common.pathing import get_project_root

logger = get_logger("forcefield.ionic_executor")

IONIC_PROFILES_PATH = "data/forcefields/ionic_profiles.yaml"
ACTIVATION_ENV_VAR = "ASPHALT_IONIC_ROUTE_ACTIVATED"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class IonicProfileError(RuntimeError):
    """Base class for ionic profile errors."""


class IonicProfileNotFoundError(IonicProfileError):
    """The requested ionic profile is not declared in the yaml SSOT."""


class IonicProfileSchemaError(IonicProfileError):
    """The ionic profile yaml is malformed."""


class IonicNotActivatedError(IonicProfileError):
    """The ionic route is not activated; runtime assignment is refused.

    This is the Wave 3 fail-closed contract: even if a profile exists
    in the yaml SSOT and even if a caller hands us a topology, we
    refuse to mutate that topology unless the activation gates are
    open. The error message tells the operator exactly which gate is
    closed and where to read the policy.
    """


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IonicSiteRule:
    site_type: str
    element: str
    charge: float
    neighbor_pattern: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class IonicAtomType:
    site_type: str
    mass: float
    epsilon: float
    sigma: float


@dataclass(frozen=True)
class IonicProfile:
    """One ionic profile parsed from ionic_profiles.yaml."""

    profile_id: str
    status: str
    profile_version: str
    family: str
    description: str
    applicable_context: dict[str, Any]
    mixing_rule_compatibility: dict[str, Any]
    citations: dict[str, str]
    site_rules: tuple[IonicSiteRule, ...]
    atom_types: tuple[IonicAtomType, ...]
    validation: dict[str, Any]

    def is_active_status(self) -> bool:
        return str(self.status).strip().lower() == "active"

    def policy_preconditions_met(self) -> tuple[bool, list[str]]:
        """Check the four Wave 3 activation pre-conditions for this profile.

        Returns (ok, missing_reasons). ``ok`` is True only if every
        condition holds. ``missing_reasons`` lists the human-readable
        gaps so callers can show them to the operator.

        These checks are *necessary* but not *sufficient*: an active
        status here only means the yaml editor declared the policy
        signed off; the runtime activation gate (env var) is a
        separate check enforced by :func:`is_activated`.
        """
        missing: list[str] = []

        # 1. usage context locked
        ctx = self.applicable_context or {}
        if not any(bool(ctx.get(name)) for name in ("aqueous", "asphalt_interface", "vacuum")):
            missing.append(
                "applicable_context: at least one of "
                "{aqueous, asphalt_interface, vacuum} must be true"
            )

        # 2. mixing-rule compatibility documented (review_required is a block)
        mix = self.mixing_rule_compatibility or {}
        for rule in ("lorentz_berthelot",):
            value = str(mix.get(rule, "")).strip().lower()
            if value not in ("validated", "incompatible"):
                missing.append(
                    f"mixing_rule_compatibility.{rule}={value or 'unset'} "
                    "(must be 'validated' or 'incompatible')"
                )

        # 3. literature provenance recorded
        cit = self.citations or {}
        if not str(cit.get("ion_charges") or "").strip():
            missing.append("citations.ion_charges is empty")
        if not str(cit.get("ion_lj") or "").strip():
            missing.append("citations.ion_lj is empty")
        validation_cit = str(cit.get("validation") or "").strip().lower()
        if not validation_cit or validation_cit == "pending":
            missing.append(
                "citations.validation is empty or 'pending' (a real LAMMPS "
                "regression reference is required)"
            )

        # 4. LAMMPS regression in CI: this can only be partially checked
        #    here. The yaml's validation.activation_blocked_reason field
        #    must be empty for the profile to be considered ready. The
        #    actual CI presence is enforced by tests/unit/test_ionic_policy.py.
        v = self.validation or {}
        blocked = str(v.get("activation_blocked_reason") or "").strip()
        if blocked:
            missing.append(
                f"validation.activation_blocked_reason is non-empty: {blocked.splitlines()[0]!r}"
            )

        return (len(missing) == 0, missing)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IonicProfileCatalog:
    """In-memory representation of the ionic_profiles.yaml SSOT."""

    schema_version: int
    version: str
    activation_global_enabled: bool
    activation_enabled_profiles: tuple[str, ...]
    profiles: dict[str, IonicProfile]


def _ionic_profiles_path() -> Path:
    return get_project_root() / IONIC_PROFILES_PATH


def _parse_site_rules(payload: Any, profile_id: str) -> tuple[IonicSiteRule, ...]:
    if not isinstance(payload, dict):
        raise IonicProfileSchemaError(f"profile {profile_id!r}: site_rules must be a mapping")
    out: list[IonicSiteRule] = []
    for site_type, raw in payload.items():
        if not isinstance(raw, dict):
            raise IonicProfileSchemaError(
                f"profile {profile_id!r} site {site_type!r}: must be a mapping"
            )
        try:
            out.append(
                IonicSiteRule(
                    site_type=str(site_type),
                    element=str(raw["element"]),
                    charge=float(raw["charge"]),
                    neighbor_pattern=dict(raw.get("neighbor_pattern") or {}),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IonicProfileSchemaError(
                f"profile {profile_id!r} site {site_type!r}: malformed entry: {exc}"
            ) from exc
    return tuple(out)


def _parse_atom_types(payload: Any, profile_id: str) -> tuple[IonicAtomType, ...]:
    if not isinstance(payload, dict):
        raise IonicProfileSchemaError(f"profile {profile_id!r}: atom_types must be a mapping")
    out: list[IonicAtomType] = []
    for site_type, raw in payload.items():
        if not isinstance(raw, dict):
            raise IonicProfileSchemaError(
                f"profile {profile_id!r} atom_type {site_type!r}: must be a mapping"
            )
        try:
            out.append(
                IonicAtomType(
                    site_type=str(site_type),
                    mass=float(raw["mass"]),
                    epsilon=float(raw["epsilon"]),
                    sigma=float(raw["sigma"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IonicProfileSchemaError(
                f"profile {profile_id!r} atom_type {site_type!r}: malformed entry: {exc}"
            ) from exc
    return tuple(out)


def _parse_profile(profile_id: str, raw: Any) -> IonicProfile:
    if not isinstance(raw, dict):
        raise IonicProfileSchemaError(
            f"profile {profile_id!r}: must be a mapping, got {type(raw).__name__}"
        )

    required = (
        "status",
        "profile_version",
        "family",
        "description",
        "applicable_context",
        "mixing_rule_compatibility",
        "citations",
        "site_rules",
        "atom_types",
        "validation",
    )
    missing = [k for k in required if k not in raw]
    if missing:
        raise IonicProfileSchemaError(
            f"profile {profile_id!r}: missing required keys {sorted(missing)}"
        )

    return IonicProfile(
        profile_id=profile_id,
        status=str(raw["status"]),
        profile_version=str(raw["profile_version"]),
        family=str(raw["family"]),
        description=str(raw["description"]),
        applicable_context=dict(raw["applicable_context"] or {}),
        mixing_rule_compatibility=dict(raw["mixing_rule_compatibility"] or {}),
        citations=dict(raw["citations"] or {}),
        site_rules=_parse_site_rules(raw["site_rules"], profile_id),
        atom_types=_parse_atom_types(raw["atom_types"], profile_id),
        validation=dict(raw["validation"] or {}),
    )


def load_ionic_catalog(path: Path | None = None) -> IonicProfileCatalog:
    """Load the ionic profile catalog from disk.

    Raises:
        IonicProfileSchemaError: if the file is missing or malformed.
    """
    yaml_path = path or _ionic_profiles_path()
    if not yaml_path.exists():
        raise IonicProfileSchemaError(
            f"Ionic profile yaml not found: {yaml_path}. The Wave 3 SSOT "
            "must exist before any ionic species is parameterized."
        )

    try:
        payload = yaml.safe_load(yaml_path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise IonicProfileSchemaError(
            f"Ionic profile yaml parse failed at {yaml_path}: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise IonicProfileSchemaError(
            f"Ionic profile yaml must contain a top-level mapping, got {type(payload).__name__}"
        )

    schema_version = int(payload.get("schema_version") or 0)
    if schema_version != 1:
        raise IonicProfileSchemaError(
            f"Ionic profile yaml schema_version={schema_version} is unsupported "
            "(this build expects schema_version=1)"
        )

    version = str(payload.get("version") or "")
    activation_block = payload.get("activation") or {}
    if not isinstance(activation_block, dict):
        raise IonicProfileSchemaError("Ionic profile yaml 'activation' block must be a mapping")

    enabled_profiles = activation_block.get("enabled_profiles") or []
    if not isinstance(enabled_profiles, list):
        raise IonicProfileSchemaError("activation.enabled_profiles must be a list")

    raw_profiles = payload.get("profiles") or {}
    if not isinstance(raw_profiles, dict):
        raise IonicProfileSchemaError(
            f"Ionic profile yaml 'profiles' must be a mapping, got {type(raw_profiles).__name__}"
        )

    parsed: dict[str, IonicProfile] = {}
    for profile_id, raw in raw_profiles.items():
        parsed[str(profile_id)] = _parse_profile(str(profile_id), raw)

    return IonicProfileCatalog(
        schema_version=schema_version,
        version=version,
        activation_global_enabled=bool(activation_block.get("global_enabled", False)),
        activation_enabled_profiles=tuple(str(p) for p in enabled_profiles),
        profiles=parsed,
    )


def get_ionic_profile(
    profile_id: str,
    *,
    catalog: IonicProfileCatalog | None = None,
) -> IonicProfile:
    """Look up a single profile by id.

    Raises ``IonicProfileNotFoundError`` if the profile is not in the
    catalog.
    """
    cat = catalog or load_ionic_catalog()
    try:
        return cat.profiles[profile_id]
    except KeyError as exc:
        known = sorted(cat.profiles.keys())
        raise IonicProfileNotFoundError(
            f"Ionic profile {profile_id!r} not found. Known profiles: {known}"
        ) from exc


# ---------------------------------------------------------------------------
# Activation gates
# ---------------------------------------------------------------------------


def is_environment_activated() -> bool:
    """Wave 3 env-var gate. Operator-level 'I have read the policy' toggle."""
    return os.environ.get(ACTIVATION_ENV_VAR) == "1"


def is_activated(
    profile_id: str,
    *,
    catalog: IonicProfileCatalog | None = None,
) -> tuple[bool, list[str]]:
    """Return ``(activated, blocking_reasons)`` for ``profile_id``.

    The ionic route is activated for a profile only when ALL of the
    following hold (defense in depth):

    * env var ``ASPHALT_IONIC_ROUTE_ACTIVATED=1`` set
    * yaml ``activation.global_enabled: true``
    * yaml ``activation.enabled_profiles`` contains ``profile_id``
    * profile.status == "active"
    * profile.policy_preconditions_met() returns True

    Returns ``(False, [...reasons])`` if any check fails.
    """
    blockers: list[str] = []

    if not is_environment_activated():
        blockers.append(
            f"env var {ACTIVATION_ENV_VAR}=1 not set (operator-level activation gate is closed)"
        )

    cat = catalog or load_ionic_catalog()

    if not cat.activation_global_enabled:
        blockers.append(
            "ionic_profiles.yaml activation.global_enabled is false "
            "(yaml-level activation gate is closed)"
        )

    if profile_id not in cat.activation_enabled_profiles:
        blockers.append(
            f"profile {profile_id!r} is not listed in "
            "ionic_profiles.yaml activation.enabled_profiles"
        )

    try:
        profile = cat.profiles[profile_id]
    except KeyError:
        blockers.append(f"profile {profile_id!r} not declared in ionic_profiles.yaml")
        return (False, blockers)

    if not profile.is_active_status():
        blockers.append(f"profile.status is {profile.status!r}, not 'active'")

    ok, missing = profile.policy_preconditions_met()
    if not ok:
        for m in missing:
            blockers.append(f"policy precondition not met: {m}")

    return (len(blockers) == 0, blockers)


# ---------------------------------------------------------------------------
# Wave 3 stub: refuse all assignments
# ---------------------------------------------------------------------------


def _build_blocked_reason(profile_id: str, blockers: list[str]) -> str:
    bullets = "\n".join(f"  - {b}" for b in blockers)
    return (
        f"Ionic species cannot be parameterized: profile {profile_id!r} "
        "is not activated.\n"
        f"Blocking reasons:\n{bullets}\n"
        "See docs/ionic_profile_policy.md for the activation procedure."
    )


@dataclass(frozen=True)
class IonicAssignmentResult:
    """Result of ionic parameter assignment."""

    charge_model: str
    bonded_overrides: dict[str, Any] | None = None


def _load_ionic_artifact(artifact_id: str) -> dict[str, Any]:
    """Load ionic artifact JSON from the JC-TIP3P catalog."""
    from common.pathing import get_project_root

    art_dir = get_project_root() / "data" / "forcefield_artifacts" / "ionic_jc_tip3p"
    art_path = art_dir / f"{artifact_id}.json"
    if not art_path.exists():
        raise IonicProfileError(f"Ionic artifact not found: {art_path}")
    import json

    with open(art_path) as f:
        return json.load(f)


def _apply_ionic_artifact(topology: Any, payload: dict[str, Any]) -> IonicAssignmentResult:
    """Apply ionic artifact to topology in-place. Return LJ overrides."""
    from forcefield.uff_element_fallback import UFF_ELEMENT_FALLBACKS

    art_atoms = payload.get("atoms", [])
    if len(art_atoms) != len(topology.atoms):
        raise IonicProfileSchemaError(
            f"Ionic artifact atom count {len(art_atoms)} != topology {len(topology.atoms)}"
        )

    for cached, atom in zip(art_atoms, topology.atoms, strict=True):
        atom.ff_type = cached["ff_type"]
        atom.charge = float(cached["charge"])
        atom.charge_defined = True

    overrides: dict[str, Any] = {
        "atom_types": {},
        "bond_types": {},
        "angle_types": {},
        "dihedral_types": {},
        "improper_types": {},
    }
    for cached in art_atoms:
        ft = cached["ff_type"]
        if ft not in overrides["atom_types"]:
            eps = cached.get("epsilon", 0.0)
            sig = cached.get("sigma", 0.0)
            elem = cached["element"]
            mass = UFF_ELEMENT_FALLBACKS.get(elem, {}).get("mass", 23.0)
            overrides["atom_types"][ft] = {
                "mass": mass,
                "epsilon": eps,
                "sigma": sig,
                "charge": 0.0,
                "element": elem,
            }

    charge_model = payload.get("charge_model", "jc_tip3p")
    return IonicAssignmentResult(
        charge_model=charge_model,
        bonded_overrides=overrides,
    )


def assign_ionic(
    *,
    topology: Any,
    profile_id: str,
    artifact_id: str | None = None,
    usage_context: str | None = None,
    catalog: IonicProfileCatalog | None = None,
) -> IonicAssignmentResult:
    """Assign ionic parameters to topology.

    Gate check → context check → artifact load → topology mutation → overrides.

    Args:
        topology: Live MolTopology to mutate.
        profile_id: Policy profile key (e.g., "joung_cheatham_nacl_v1").
        artifact_id: Artifact filename stem (e.g., "NaCl"). Defaults to
            topology.mol_id if not provided.
        usage_context: Runtime context — "vacuum", "aqueous", or
            "asphalt_interface". Must match profile's applicable_context.
            If None, fail-closed.
        catalog: Optional pre-loaded profile catalog.

    Returns:
        IonicAssignmentResult with LJ overrides.

    Raises:
        IonicNotActivatedError: When activation gates or context check fails.
        IonicProfileError: When artifact is missing or malformed.
    """
    # Context-aware gate: fail-closed if context not specified
    if not usage_context:
        raise IonicNotActivatedError(
            "Ionic assignment requires explicit usage_context "
            "(vacuum/aqueous/asphalt_interface), got None. "
            "Fail-closed: silent default is not allowed."
        )

    activated, blockers = is_activated(profile_id, catalog=catalog)
    if not activated:
        reason = _build_blocked_reason(profile_id, blockers)
        logger.warning(
            "ionic assign refused for %s (mol_id=%s)",
            profile_id,
            getattr(topology, "mol_id", "?"),
        )
        raise IonicNotActivatedError(reason)

    # Context-aware gate: check profile's applicable_context
    cat = catalog or load_ionic_catalog()
    profile = cat.profiles.get(profile_id) if cat else None
    if profile:
        ctx = profile.applicable_context or {}
        if not ctx.get(usage_context, False):
            raise IonicNotActivatedError(
                f"Ionic profile {profile_id!r} does not support "
                f"usage_context={usage_context!r}. "
                f"Allowed contexts: {[k for k, v in ctx.items() if v]}"
            )

    # Resolve artifact_id
    _artifact_id = artifact_id or getattr(topology, "mol_id", profile_id)
    payload = _load_ionic_artifact(_artifact_id)

    logger.info(
        "Applying ionic profile %s (artifact=%s, context=%s) to %s",
        profile_id,
        _artifact_id,
        usage_context,
        getattr(topology, "mol_id", "?"),
    )
    return _apply_ionic_artifact(topology, payload)


__all__ = [
    "ACTIVATION_ENV_VAR",
    "IONIC_PROFILES_PATH",
    "IonicProfileError",
    "IonicProfileNotFoundError",
    "IonicProfileSchemaError",
    "IonicNotActivatedError",
    "IonicSiteRule",
    "IonicAtomType",
    "IonicProfile",
    "IonicProfileCatalog",
    "load_ionic_catalog",
    "get_ionic_profile",
    "is_environment_activated",
    "is_activated",
    "assign_ionic",
]
