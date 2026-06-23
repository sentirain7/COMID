#!/usr/bin/env bash
# =============================================================================
# install.sh - One-command bootstrap installer for COMID
# =============================================================================
# Sets up the whole stack from a fresh `git clone`, in dependency order:
#
#   1. conda (Miniforge) - installed automatically if missing
#   2. conda env from environment.yml  (rdkit, ambertools, numpy, scipy, ...)
#      -> conda-forge resolves the scientific-stack ordering / ABI for you
#   3. pip install -e ".[<extras>]"    (the COMID package itself)
#   4. .env scaffolded from .env.example
#   5. (optional) GPU LAMMPS build via scripts/install_lammps.sh
#   6. import-level verification of the Reviewable Core
#
# After this, use ./start_all.sh to run the services.
#
# Usage:
#   ./install.sh                 # core setup (conda env + package + .env), no LAMMPS
#   ./install.sh --full          # core setup + build GPU LAMMPS (Execution Backend)
#   ./install.sh --extras ml     # pip extras to install (default: all)
#   ./install.sh --with-lammps   # alias for adding the LAMMPS build step
#   ./install.sh --env-name comid # conda env name (default: from environment.yml)
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

EXTRAS="all"
BUILD_LAMMPS=0
ENV_NAME=""        # default: read `name:` from environment.yml

c_info() { printf '\033[0;34m[install]\033[0m %s\n' "$*"; }
c_ok()   { printf '\033[0;32m[install]\033[0m %s\n' "$*"; }
c_warn() { printf '\033[0;33m[install]\033[0m %s\n' "$*"; }
c_err()  { printf '\033[0;31m[install]\033[0m %s\n' "$*" >&2; }
c_step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --full)          BUILD_LAMMPS=1; shift ;;
        --with-lammps)   BUILD_LAMMPS=1; shift ;;
        --extras)        EXTRAS="$2"; shift 2 ;;
        --env-name)      ENV_NAME="$2"; shift 2 ;;
        -h|--help)       grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) c_err "unknown arg: $1"; exit 2 ;;
    esac
done

[[ "$(uname -s)" == "Linux" ]] || c_warn "this installer targets Linux; other OSes are untested."

# --- 1. ensure conda --------------------------------------------------------
c_step "1/6  conda (Miniforge)"
if ! command -v conda >/dev/null 2>&1; then
    if [[ -f "${HOME}/miniforge3/bin/conda" ]]; then
        eval "$("${HOME}/miniforge3/bin/conda" shell.bash hook)"
    else
        c_info "conda not found — installing Miniforge to ~/miniforge3 ..."
        tmp="$(mktemp -d)"
        wget -qO "${tmp}/miniforge.sh" \
            "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh"
        bash "${tmp}/miniforge.sh" -b -p "${HOME}/miniforge3"
        rm -rf "$tmp"
        eval "$("${HOME}/miniforge3/bin/conda" shell.bash hook)"
        conda init bash >/dev/null 2>&1 || true
    fi
else
    eval "$(conda shell.bash hook)"
fi
c_ok "conda: $(command -v conda)"

# --- 2. conda env from environment.yml -------------------------------------
c_step "2/6  conda environment (environment.yml)"
[[ -z "$ENV_NAME" ]] && ENV_NAME="$(awk '/^name:/{print $2; exit}' environment.yml)"
[[ -z "$ENV_NAME" ]] && ENV_NAME="asphalt_env"
if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
    c_info "env '${ENV_NAME}' exists — updating from environment.yml ..."
    conda env update -n "$ENV_NAME" -f environment.yml --prune
else
    c_info "creating env '${ENV_NAME}' from environment.yml ..."
    conda env create -f environment.yml
fi
conda activate "$ENV_NAME"
c_ok "active env: ${CONDA_DEFAULT_ENV:-$ENV_NAME}  ($(python --version 2>&1))"

# --- 3. pip install the package --------------------------------------------
c_step "3/6  COMID package (pip install -e .[${EXTRAS}])"
python -m pip install --upgrade pip >/dev/null
python -m pip install -e ".[${EXTRAS}]"
c_ok "package installed (editable, extras: ${EXTRAS})"

# --- 4. .env scaffold -------------------------------------------------------
c_step "4/6  .env"
if [[ -f .env ]]; then
    c_info ".env already present — leaving it untouched"
elif [[ -f .env.example ]]; then
    cp .env.example .env
    c_ok "created .env from .env.example (edit it for your machine)"
else
    c_warn "no .env.example found — skipping .env scaffold"
fi

# --- 5. optional LAMMPS build ----------------------------------------------
c_step "5/6  LAMMPS (Execution Backend)"
if [[ "$BUILD_LAMMPS" -eq 1 ]]; then
    c_info "building GPU LAMMPS via scripts/install_lammps.sh ..."
    bash scripts/install_lammps.sh
else
    c_info "skipped (run './install.sh --full' or 'scripts/install_lammps.sh' to build GPU LAMMPS)."
    c_info "the Reviewable Core (FF / topology / metrics / dry-run) needs no LAMMPS."
fi

# --- 6. verify Reviewable Core ---------------------------------------------
c_step "6/6  verification"
if PYTHONPATH=src:packages python -c "import contracts, common, builder, metrics, ml" 2>/dev/null; then
    c_ok "Reviewable Core imports OK"
else
    c_warn "core import check failed — see errors above (frontend/Node deps are separate)."
fi

cat <<EOF

$(c_ok "COMID setup complete.")
  Next:
    conda activate ${ENV_NAME}
    ./start_all.sh            # start Redis + API(:8000) + dashboard(:5173) + workers
    ./start_all.sh --status   # check services
  LAMMPS-free dry run (no GPU):
    PYTHONPATH=src:packages python scripts/run_inverse_pipeline_smoke.py
EOF
