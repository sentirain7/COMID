#!/usr/bin/env python3
"""Compatibility wrapper that delegates batch generation to the canonical CLI.

Phase 4 (v00.99.41) — The independent AmberTools pipeline that used to
live here has been retired. Use the merged
``scripts/generate_gaff2_artifact.py batch ...`` instead. This file is kept
to avoid breaking automation scripts that still call into it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ADMIN_GUARD_ENV = "ASPHALT_ANTECHAMBER_ADMIN"


def main() -> None:
    if os.environ.get(ADMIN_GUARD_ENV) != "1":
        print(f"ERROR: {ADMIN_GUARD_ENV}=1 must be set.", file=sys.stderr)
        sys.exit(1)

    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    sys.path.insert(0, str(PROJECT_ROOT / "packages"))

    # Forward to generate_gaff2_artifact.py so there is exactly one place
    # that knows how to call AmberTools.
    canonical = PROJECT_ROOT / "scripts" / "generate_gaff2_artifact.py"
    forwarded_args = ["batch", *sys.argv[1:]]
    print(
        "[deprecated] batch_generate_gaff2_artifacts.py — forwarding to "
        f"{canonical.name} {' '.join(forwarded_args)}",
        file=sys.stderr,
    )
    os.execv(sys.executable, [sys.executable, str(canonical), *forwarded_args])


if __name__ == "__main__":
    main()
