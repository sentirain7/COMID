#!/usr/bin/env python3
"""Thin CLI wrapper around ``features.molecules.artifact_service``.

Phase 4 (v00.99.41) — The standalone AmberTools pipeline that used to live
in this script has been retired. Single-molecule and batch generation now
delegate to the same backend service that the public/admin API uses, so
CLI output and admin diagnostics never drift apart again.

Admin-only — set ``ASPHALT_ANTECHAMBER_ADMIN=1`` to enable.

Usage (single molecule)::

    ASPHALT_ANTECHAMBER_ADMIN=1 python scripts/generate_gaff2_artifact.py single \\
        --mol data/molecules/single_moles/Methanol.mol --mol-id Methanol

Usage (batch)::

    ASPHALT_ANTECHAMBER_ADMIN=1 python scripts/generate_gaff2_artifact.py batch \\
        [--dry-run] [--force] [--workers N] [--profile baseline|sqm_robust]

Usage (preflight only — no AmberTools execution)::

    ASPHALT_ANTECHAMBER_ADMIN=1 python scripts/generate_gaff2_artifact.py single \\
        --mol foo.mol --mol-id Foo --diagnose-only
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "packages"))

ADMIN_GUARD_ENV = "ASPHALT_ANTECHAMBER_ADMIN"
ARTIFACT_DIR = PROJECT_ROOT / "data" / "forcefield_artifacts" / "organic_gaff2"
SUPPORTED_PROFILES = ("baseline", "sqm_robust")


def _check_admin_guard() -> None:
    if os.environ.get(ADMIN_GUARD_ENV) != "1":
        print(f"ERROR: {ADMIN_GUARD_ENV}=1 must be set.", file=sys.stderr)
        sys.exit(1)


def _check_tools() -> None:
    for cmd in ("antechamber", "parmchk2", "tleap"):
        if subprocess.run(["which", cmd], capture_output=True).returncode != 0:
            print(
                f"ERROR: {cmd} not found. Run: conda activate asphalt_env",
                file=sys.stderr,
            )
            sys.exit(1)
    try:
        import parmed  # noqa: F401
    except ImportError:
        print("ERROR: parmed not found. Run: pip install parmed", file=sys.stderr)
        sys.exit(1)


def _diagnose_only(mol_id: str) -> int:
    """Print the same RDKit preflight payload that the admin API returns.

    Delegates to ``artifact_service.diagnose_artifact_target`` so the CLI
    output cannot drift from ``POST /artifacts/admin/diagnose/{mol_id}``.
    """
    from features.molecules.artifact_service import (
        diagnose_artifact_target,
        resolve_artifact_target,
    )

    target = resolve_artifact_target(mol_id)
    payload = diagnose_artifact_target(target)
    payload.update(
        {
            "source_id": target.source_id,
            "consumer_ids": target.consumer_ids,
            "parameterization_mode": target.parameterization_mode,
        }
    )
    print(json.dumps(payload, indent=2))
    return 0


def _run_single(args: argparse.Namespace) -> int:
    if args.diagnose_only:
        return _diagnose_only(args.mol_id)

    from features.molecules.admin_status import AdminStatusStore
    from features.molecules.artifact_service import (
        ARTIFACT_DIR,
        AdminGenerationError,
        generate_gaff2_artifact,
        resolve_artifact_target,
        source_generation_lock,
        validate_admin_generation_request,
        validate_artifact,
    )
    from features.molecules.exceptions import ArtifactGenerationError

    mol_path = Path(args.mol)
    if not mol_path.exists():
        print(f"ERROR: {mol_path} not found", file=sys.stderr)
        return 1

    target = resolve_artifact_target(args.mol_id)
    store = AdminStatusStore(ARTIFACT_DIR)
    try:
        validate_admin_generation_request(target, args.profile, store)
    except AdminGenerationError as e:
        print(f"ERROR ({e.status_code}): {e.message}", file=sys.stderr)
        return 1

    try:
        with source_generation_lock(target.source_id):
            try:
                artifact = generate_gaff2_artifact(
                    mol_path=mol_path,
                    mol_id=args.mol_id,
                    smiles=args.smiles,
                    formal_charge=args.charge,
                    ff_assignment=target.ff_assignment,
                    generation_profile=args.profile,
                )
            except ArtifactGenerationError as e:
                try:
                    store.record_failure(
                        target.source_id,
                        e,
                        consumer_ids=target.consumer_ids,
                        generation_profile=args.profile,
                    )
                except Exception:
                    pass
                print(
                    f"ERROR [{e.stage}/{e.failure_code.value}]: {e.message}",
                    file=sys.stderr,
                )
                return 1
            try:
                store.record_success(
                    target.source_id,
                    consumer_ids=target.consumer_ids,
                    generation_profile=args.profile,
                )
            except Exception:
                pass
    except Exception as e:  # pragma: no cover - defensive
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    out = Path(args.output) if args.output else target.artifact_path
    if out != target.artifact_path:
        # Default path was already written by generate_gaff2_artifact via
        # the resolver. Honour --output by copying when overridden.
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w") as f:
            json.dump(artifact, f, indent=2)

    validation = validate_artifact(artifact)
    print(f"Artifact: {out}")
    print(
        f"  atoms={len(artifact['atoms'])} bonds={len(artifact['bond_types'])} "
        f"angles={len(artifact['angle_types'])} "
        f"dihedrals={len(artifact['dihedral_types'])} "
        f"impropers={len(artifact['improper_types'])} "
        f"Σq={artifact.get('charge_sum', 0):+.4f} "
        f"profile={artifact.get('generation_profile')}"
    )
    print(f"  valid={validation['valid']}")
    return 0


def _run_batch(args: argparse.Namespace) -> int:
    from features.molecules.admin_status import AdminStatusStore
    from features.molecules.artifact_service import (
        ARTIFACT_DIR,
        AdminGenerationError,
        get_pending_molecules,
        resolve_artifact_target,
        run_parallel_batch,
        validate_admin_generation_request,
    )

    molecules = get_pending_molecules()
    pending = (
        [m for m in molecules if m.get("artifact_type") == "organic"]
        if args.force
        else [
            m
            for m in molecules
            if m.get("artifact_type") == "organic" and not m["is_complete"]
        ]
    )

    if args.dry_run:
        print(f"전체 organic 분자: {len(molecules)}개")
        print(f"생성 대상: {len(pending)}개\n")
        for m in pending:
            print(
                f"  {m['mol_id']:50s} {m.get('atom_count', 0):4d} atoms  "
                f"source_id={m.get('source_id')}  ({m.get('catalog')})"
            )
        return 0

    if not pending:
        print("Nothing to generate — all artifacts complete.")
        return 0

    # v00.99.42 reinforcement: apply admin gating per row before queuing.
    # sqm_robust must clear the same prior-failure check that the API uses,
    # so a `batch --profile sqm_robust` run only escalates rows that have
    # actually failed with sqm_timeout / sqm_nonconverged.
    store = AdminStatusStore(ARTIFACT_DIR)
    eligible: list[dict] = []
    skipped: list[dict] = []
    for m in pending:
        target = resolve_artifact_target(m["mol_id"])
        try:
            validate_admin_generation_request(target, args.profile, store)
        except AdminGenerationError as exc:
            skipped.append(
                {
                    "mol_id": m["mol_id"],
                    "source_id": target.source_id,
                    "reason": "admin_policy_blocked",
                    "status_code": exc.status_code,
                    "message": exc.message,
                }
            )
            continue
        m["generation_profile"] = args.profile
        eligible.append(m)

    if skipped:
        print(f"\n[skipped] admin policy blocked {len(skipped)} row(s):")
        for s in skipped:
            print(
                f"  {s['mol_id']:40s} [{s['status_code']}] {s['message'][:120]}"
            )

    if not eligible:
        print("\nNothing eligible to generate under requested profile.")
        return 1 if skipped else 0

    # v00.99.43 codex audit: tag the batch as admin so the FF Parameters
    # page progress payload reflects the actual operator surface (CLI is
    # admin-gated by ASPHALT_ANTECHAMBER_ADMIN). Forwarding the profile
    # closes the metadata SSOT so batch_kind/generation_profile in
    # /batch-progress always matches the caller's intent.
    result = run_parallel_batch(
        eligible,
        max_workers=args.workers,
        batch_kind="admin",
        generation_profile=args.profile,
    )
    print("\n=== Results ===")
    print(f"  Success:  {result['success']}")
    print(f"  Failed:   {result['failed']}")
    print(f"  Skipped:  {len(skipped)} (admin_policy_blocked)")
    print(f"  Workers:  {result['max_workers']}")
    if result["failed"] > 0:
        print("\nFailed molecules:")
        for d in result["details"]:
            if d.get("status") == "error":
                code = d.get("failure_code", "unknown")
                stage = d.get("stage", "")
                print(f"  {d['mol_id']:40s} [{stage}/{code}] {d.get('error', '')[:120]}")
    return 0 if result["failed"] == 0 else 1


def main() -> None:
    _check_admin_guard()

    parser = argparse.ArgumentParser(
        description="Generate GAFF2 artifact JSON (single or batch) — thin wrapper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--profile",
        choices=SUPPORTED_PROFILES,
        default="baseline",
        help=(
            "Generation profile. baseline = current sqm options. sqm_robust = "
            "convergence-aid options (admin only; recommended for sqm_* failures)."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=False)

    single = sub.add_parser("single", help="Generate artifact for one molecule")
    single.add_argument("--mol", required=False, help="Input MDL MOL or MOL2 file")
    single.add_argument("--mol-id", required=True, help="Molecule identifier")
    single.add_argument("--output", help="Output JSON path (default: artifact dir)")
    single.add_argument("--smiles", default="", help="Canonical SMILES")
    single.add_argument("--charge", type=int, default=0, help="Formal charge")
    single.add_argument(
        "--diagnose-only",
        action="store_true",
        help="Skip AmberTools; print preflight (resolver) info and exit.",
    )

    batch = sub.add_parser("batch", help="Generate artifacts for all organic molecules")
    batch.add_argument("--dry-run", action="store_true", help="List molecules only")
    batch.add_argument(
        "--force",
        action="store_true",
        help="Regenerate existing (complete) artifacts",
    )
    batch.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Max parallel workers (default: auto = cpu_count - 4, min 2, cap 24)",
    )

    args = parser.parse_args()

    # Tools are only needed when we actually call AmberTools.
    needs_tools = (
        args.command == "single" and not getattr(args, "diagnose_only", False)
    ) or (args.command == "batch" and not getattr(args, "dry_run", False))
    if needs_tools:
        _check_tools()

    if args.command == "single":
        # Push the parser-level --profile into the sub-namespace.
        args.profile = getattr(args, "profile", "baseline") or "baseline"
        sys.exit(_run_single(args))
    elif args.command == "batch":
        args.profile = getattr(args, "profile", "baseline") or "baseline"
        sys.exit(_run_batch(args))
    else:
        # Default: dry-run inventory.
        from features.molecules.artifact_service import get_pending_molecules

        molecules = get_pending_molecules()
        organic = [m for m in molecules if m.get("artifact_type") == "organic"]
        complete = sum(1 for m in organic if m["is_complete"])
        print(f"Organic molecules: {len(organic)}  Complete: {complete}")


if __name__ == "__main__":
    main()
