"""FF eligibility adapter — surfaces blocked/warning states from existing SSOT.

This module does NOT define new FF policy. It combines results from
typing_router + ff_assignment + catalog to produce preview/submit
eligibility summaries for binder and layered workflows.
"""

from __future__ import annotations

from typing import Any

from common.logging import get_logger

logger = get_logger("forcefield.eligibility")


def collect_binder_ff_issues(
    mol_ids: list[str],
    additive_ids: list[str],
) -> dict[str, Any]:
    """Collect FF eligibility issues for a binder composition.

    Uses resolve_ff_hint() directly (no molecule_db required).

    v00.99.96 semantic — FAIL-CLOSED at preview/validate:
        Previously (v00.99.30) a missing / incomplete organic curated
        artifact was reported as a ``warning`` because the build path
        auto-regenerated via ``ensure_organic_artifact``. Under the new
        explicit-generation policy the build path is strict observe-only,
        so any FF that is not already on disk must block submit here.

        ``resolve_ff_hint`` now returns ``is_submittable=False`` for
        missing/incomplete artifacts, so the existing ``blocked`` branch
        below captures them automatically. The ``warning_items`` list is
        retained (always empty for organic under the new semantic) so
        downstream consumers with ``ff_warning_items`` in their schema
        do not break — they simply receive an empty list.

    Args:
        mol_ids: Binder molecule IDs (SARA components). Batch-level callers
            MUST pass the **union** of all binder molecules derived from
            their enumerated combinations; additives alone is not enough.
        additive_ids: Selected additive IDs.

    Returns:
        Dict with ``blocked_items``, ``warning_items``, ``has_blocked``.
        ``warning_items`` is retained as an empty list for schema
        backwards compatibility.
    """
    from features.molecules.catalog import resolve_ff_hint

    blocked: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []  # retained for schema compat

    all_ids = [("molecule", mid) for mid in mol_ids] + [("additive", aid) for aid in additive_ids]

    for item_kind, item_id in all_ids:
        try:
            hint = resolve_ff_hint(item_id)
        except Exception:
            blocked.append(
                {
                    "item_id": item_id,
                    "item_kind": item_kind,
                    "route": None,
                    "status": "blocked",
                    "message": f"Failed to resolve FF hint for {item_id}",
                }
            )
            continue

        if not hint.get("is_submittable", True):
            blocked.append(
                {
                    "item_id": item_id,
                    "item_kind": item_kind,
                    "route": hint.get("route"),
                    "status": "blocked",
                    "message": hint.get("blocked_reason") or f"{item_id} is blocked",
                }
            )
            continue

        # v00.99.96: the previous "artifact_warning → warning" branch is
        # unreachable for organic curated artifact because resolve_ff_hint
        # now returns is_submittable=False when the artifact is
        # missing/incomplete. Kept for future non-organic warning channels
        # that might populate artifact_warning without blocking submit.
        warn_msg = hint.get("artifact_warning")
        if warn_msg:
            warnings.append(
                {
                    "item_id": item_id,
                    "item_kind": item_kind,
                    "route": hint.get("route"),
                    "status": "warn",
                    "message": warn_msg,
                }
            )

    return {
        "blocked_items": blocked,
        "warning_items": warnings,
        "has_blocked": len(blocked) > 0,
    }


def collect_layered_ff_checks(
    layers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return FF compatibility checks for a layered source stack.

    Each returned dict has ``code``, ``status`` (pass/warn/fail),
    ``message``, and ``details``.

    Uses resolve_ff_hint() directly (no molecule_db required).

    Args:
        layers: List of layer dicts with at least ``source_type`` and
            ``source_id`` or ``auto_match_material``.

    Returns:
        List of check dicts compatible with LayeredStructureCheckResponse.
    """
    checks: list[dict[str, Any]] = []

    for i, layer in enumerate(layers):
        source_type = layer.get("source_type", "")
        source_id = layer.get("source_id") or layer.get("auto_match_material")

        if source_type in ("crystal_structure", "crystal"):
            # Crystal sources are always FF-compatible
            continue

        if source_type in ("binder_experiment", "amorphous_binder"):
            # Binder/amorphous sources use organic FF — compatible
            continue

        # binder_cell, binder_cell is a prebuilt binder experiment source — FF-compatible
        # These sources already passed FF gate at creation time
        if source_type in ("binder_cell",):
            # Binder cell sources use organic FF — compatible (prebuilt)
            continue

        if source_type == "interface_molecule":
            # source_id is the actual mol_id — use directly
            if not source_id:
                checks.append(
                    {
                        "code": "ff_compatibility",
                        "status": "fail",
                        "message": f"Layer {i + 1}: interface molecule source_id missing",
                        "details": {"layer_index": i, "source_type": source_type},
                    }
                )
                continue

            try:
                from features.molecules.catalog import resolve_ff_hint

                hint = resolve_ff_hint(str(source_id))
                route = hint.get("route", "")

                if route == "ionic_profile":
                    checks.append(
                        {
                            "code": "ff_compatibility",
                            "status": "fail",
                            "message": (
                                f"Layer {i + 1}: ionic species '{source_id}' is not "
                                "supported in layered structures"
                            ),
                            "details": {
                                "layer_index": i,
                                "source_id": source_id,
                                "route": route,
                            },
                        }
                    )
                elif route == "water_model":
                    checks.append(
                        {
                            "code": "ff_compatibility",
                            "status": "pass",
                            "message": (f"Layer {i + 1}: water model '{source_id}' is compatible"),
                            "details": {
                                "layer_index": i,
                                "source_id": source_id,
                                "route": route,
                            },
                        }
                    )
                elif not hint.get("is_submittable", True):
                    checks.append(
                        {
                            "code": "ff_compatibility",
                            "status": "fail",
                            "message": (
                                f"Layer {i + 1}: '{source_id}' is blocked — "
                                f"{hint.get('blocked_reason', 'unknown reason')}"
                            ),
                            "details": {
                                "layer_index": i,
                                "source_id": source_id,
                                "route": route,
                            },
                        }
                    )
                # else: organic or inorganic — pass (no check needed)
            except Exception as exc:
                checks.append(
                    {
                        "code": "ff_compatibility",
                        "status": "fail",
                        "message": (
                            f"Layer {i + 1}: failed to resolve FF for '{source_id}': {exc}"
                        ),
                        "details": {"layer_index": i, "source_id": source_id},
                    }
                )
            continue

        if source_type == "interface_molecule_cell":
            # cell ID (e.g., ifc_water_10x10x20) is NOT a mol_id
            # Extract actual mol_id from layer dict: interface_mol_id or components_json
            interface_mol_id = layer.get("interface_mol_id")
            is_water_like = layer.get("is_water_like", False)

            # is_water_like가 true면 mol_id 문자열에 의존하지 않고 water_model compatible pass
            if is_water_like:
                checks.append(
                    {
                        "code": "ff_compatibility",
                        "status": "pass",
                        "message": f"Layer {i + 1}: water-like cell is FF-compatible",
                        "details": {
                            "layer_index": i,
                            "source_id": source_id,
                            "is_water_like": True,
                        },
                    }
                )
                continue

            if not interface_mol_id:
                components = layer.get("components_json", {})
                # components_json can be dict or list[dict]
                if isinstance(components, list):
                    # Multiple components — extract first mol_id
                    for comp in components:
                        if isinstance(comp, dict) and comp.get("mol_id"):
                            interface_mol_id = comp["mol_id"]
                            break
                elif isinstance(components, dict):
                    interface_mol_id = components.get("mol_id")

            # If mol_id not found and not water_like, log warning with explicit reason
            if not interface_mol_id:
                logger.warning(
                    "Layer %d: interface_molecule_cell without interface_mol_id or is_water_like; "
                    "assuming FF-compatible (prebuilt cell) but this may indicate missing metadata",
                    i + 1,
                )
                checks.append(
                    {
                        "code": "ff_compatibility",
                        "status": "pass",
                        "message": (
                            f"Layer {i + 1}: interface_molecule_cell without mol_id metadata; "
                            "assuming FF-compatible (prebuilt cell)"
                        ),
                        "details": {
                            "layer_index": i,
                            "source_id": source_id,
                            "reason": "prebuilt_cell_no_metadata",
                        },
                    }
                )
                continue

            # interface_mol_id is available — check FF compatibility
            try:
                from features.molecules.catalog import resolve_ff_hint

                hint = resolve_ff_hint(interface_mol_id)
                route = hint.get("route", "")

                if route == "ionic_profile":
                    checks.append(
                        {
                            "code": "ff_compatibility",
                            "status": "fail",
                            "message": (
                                f"Layer {i + 1}: ionic species '{interface_mol_id}' is not "
                                "supported in layered structures"
                            ),
                            "details": {
                                "layer_index": i,
                                "source_id": source_id,
                                "interface_mol_id": interface_mol_id,
                                "route": route,
                            },
                        }
                    )
                elif route == "water_model":
                    checks.append(
                        {
                            "code": "ff_compatibility",
                            "status": "pass",
                            "message": (
                                f"Layer {i + 1}: water model '{interface_mol_id}' is compatible"
                            ),
                            "details": {
                                "layer_index": i,
                                "source_id": source_id,
                                "interface_mol_id": interface_mol_id,
                                "route": route,
                            },
                        }
                    )
                elif not hint.get("is_submittable", True):
                    checks.append(
                        {
                            "code": "ff_compatibility",
                            "status": "fail",
                            "message": (
                                f"Layer {i + 1}: '{interface_mol_id}' is blocked — "
                                f"{hint.get('blocked_reason', 'unknown reason')}"
                            ),
                            "details": {
                                "layer_index": i,
                                "source_id": source_id,
                                "interface_mol_id": interface_mol_id,
                                "route": route,
                            },
                        }
                    )
                # else: organic or inorganic — pass (no check needed)
            except Exception as exc:
                checks.append(
                    {
                        "code": "ff_compatibility",
                        "status": "fail",
                        "message": (
                            f"Layer {i + 1}: failed to resolve FF for '{interface_mol_id}': {exc}"
                        ),
                        "details": {
                            "layer_index": i,
                            "source_id": source_id,
                            "interface_mol_id": interface_mol_id,
                        },
                    }
                )
            continue

        # Unknown source type — fail-closed
        checks.append(
            {
                "code": "ff_compatibility",
                "status": "fail",
                "message": (
                    f"Layer {i + 1}: unknown source_type '{source_type}' — "
                    "cannot determine FF compatibility"
                ),
                "details": {"layer_index": i, "source_type": source_type},
            }
        )

    # If no issues found, emit a single pass check
    if not checks:
        checks.append(
            {
                "code": "ff_compatibility",
                "status": "pass",
                "message": "All layer sources are FF-compatible",
                "details": {},
            }
        )

    return checks


def collect_organic_source_provenance(
    mol_ids: list[str],
    additive_ids: list[str],
) -> list[dict[str, str]]:
    """Collect organic source provenance (source_id, generator, generation_profile) for governance.

    Reads from admin sidecar first, falls back to artifact JSON, then defaults.
    Used by submission gates to determine stack_id before build.

    Args:
        mol_ids: Binder molecule IDs (SARA components).
        additive_ids: Additive molecule IDs.

    Returns:
        List of provenance dicts with keys: mol_id, source_id, generator,
        generation_profile. Empty list on total failure (fail-open for
        provenance collection — the governance gate itself is fail-closed).
    """
    sources: list[dict[str, str]] = []
    try:
        from features.molecules.admin_status import AdminStatusStore
        from features.molecules.artifact_service import ARTIFACT_DIR, resolve_artifact_target

        store = AdminStatusStore(ARTIFACT_DIR)
        all_ids = list(mol_ids) + list(additive_ids)
        seen: set[str] = set()

        for mid in all_ids:
            try:
                target = resolve_artifact_target(mid)
                sid = target.source_id
                if sid in seen:
                    continue
                seen.add(sid)

                generator = "antechamber_am1bcc"  # default
                gen_profile = "baseline"

                # Try admin sidecar first
                sidecar = store.get(sid)
                if sidecar:
                    generator = sidecar.generator or generator
                    gen_profile = sidecar.generation_profile or gen_profile
                else:
                    # Try artifact JSON
                    import json

                    art_path = target.artifact_path
                    if art_path.exists():
                        try:
                            with open(art_path) as f:
                                art = json.load(f)
                            generator = art.get("generator", generator)
                        except Exception:
                            pass

                sources.append(
                    {
                        "mol_id": mid,
                        "source_id": sid,
                        "generator": generator,
                        "generation_profile": gen_profile,
                    }
                )
            except Exception:
                continue
    except Exception:
        pass
    return sources
