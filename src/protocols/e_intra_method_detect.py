"""Lightweight E_intra method detection from a LAMMPS input file.

PR 2 (Codex Round 6): pulled out of ``features.scan_database.service`` so
non-API workers (pipeline, retrain task) can import the detector without
dragging FastAPI / Starlette through ``features.scan_database.router``.

Both the pipeline (post-run provenance verification) and scan_database
(import-time tagging) call into this module directly.
"""

from __future__ import annotations


def detect_e_intra_method_from_input(input_file_path: str | None) -> str:
    """Return the E_intra method tag implied by a LAMMPS input file.

    Recognised pair_style / kspace forms:

    - ``pair_style lj/cut/coul/cut <cutoff>``  (charged vacuum)
    - ``pair_style lj/cut <cutoff>``           (no-charge vacuum)
    - ``pair_style lj/cut/coul/long <cutoff>`` + ``kspace_style pppm``
      (periodic PPPM)

    Cutoff > legacy 12 Å indicates Method 1a (adaptive cutoff vacuum);
    12 Å (or absent / parse failure) falls back to Method 1.  The function
    is read-only and never raises — bad files return the safe default.
    """
    from contracts.schema_enums import EIntraMethod
    from protocols.lammps_force_field import VACUUM_DEFAULT_CUTOFF_A

    default = EIntraMethod.SINGLE_MOLECULE_VACUUM.value
    if not input_file_path:
        return default
    try:
        saw_periodic_pair_style = False
        saw_pppm = False
        with open(input_file_path, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if line.startswith("kspace_style"):
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].lower() == "pppm":
                        saw_pppm = True
                    continue
                if not line.startswith("pair_style"):
                    continue
                parts = line.split()
                if len(parts) < 3:
                    return default
                style = parts[1]
                cutoff_token = parts[2]
                if style == "lj/cut/coul/long":
                    saw_periodic_pair_style = True
                    if saw_pppm:
                        return EIntraMethod.SINGLE_MOLECULE_PERIODIC.value
                    continue
                if style not in ("lj/cut/coul/cut", "lj/cut"):
                    return default
                try:
                    cutoff = float(cutoff_token)
                except ValueError:
                    return default
                if cutoff > VACUUM_DEFAULT_CUTOFF_A + 0.5:
                    return EIntraMethod.SINGLE_MOLECULE_VACUUM_ADAPTIVE_CUTOFF.value
                return default
        if saw_periodic_pair_style and saw_pppm:
            return EIntraMethod.SINGLE_MOLECULE_PERIODIC.value
    except OSError:
        return default
    return default
