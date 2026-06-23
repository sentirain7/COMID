#!/usr/bin/env bash
# =============================================================================
# install_lammps.sh - Pinned, GPU-enabled LAMMPS source build for COMID
# =============================================================================
# Builds LAMMPS stable_22Jul2025 with the exact configuration this platform
# requires (KOKKOS + CUDA + OpenMP + cuFFT and the package set used by the
# protocol templates), then writes LAMMPS_EXECUTABLE into the repo .env.
#
# apt/conda default LAMMPS builds are insufficient (no GPU acceleration / missing
# packages), so we build from source against a pinned tag for reproducibility.
#
# Usage:
#   scripts/install_lammps.sh                  # auto-detect GPU arch, build
#   scripts/install_lammps.sh --arch HOPPER90  # force a Kokkos CUDA arch
#   scripts/install_lammps.sh --prefix ~/lammps --jobs 16
#   scripts/install_lammps.sh --no-env-write   # do not touch .env
#
# Requirements: git, cmake>=3.20, a CUDA toolkit (nvcc), a C++ compiler, MPI
# (optional). On a conda env, `conda install -c conda-forge cmake cudatoolkit-dev`
# can provide the toolchain.
# =============================================================================
set -euo pipefail

LAMMPS_TAG="stable_22Jul2025"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="${HOME}/lammps"
JOBS="$(nproc 2>/dev/null || echo 8)"
ARCH=""
WRITE_ENV=1

# LAMMPS package set required by the protocol templates (see the project documentation).
PACKAGES=(CLASS2 EXTRA-DUMP EXTRA-FIX EXTRA-MOLECULE EXTRA-PAIR INTERLAYER \
          KOKKOS KSPACE MANYBODY MC MISC MOLECULE OPENMP OPT REAXFF RIGID ASPHERE)

c_info()  { printf '\033[0;34m[install_lammps]\033[0m %s\n' "$*"; }
c_ok()    { printf '\033[0;32m[install_lammps]\033[0m %s\n' "$*"; }
c_warn()  { printf '\033[0;33m[install_lammps]\033[0m %s\n' "$*"; }
c_err()   { printf '\033[0;31m[install_lammps]\033[0m %s\n' "$*" >&2; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --arch)        ARCH="$2"; shift 2 ;;
        --prefix)      PREFIX="$2"; shift 2 ;;
        --jobs)        JOBS="$2"; shift 2 ;;
        --tag)         LAMMPS_TAG="$2"; shift 2 ;;
        --no-env-write) WRITE_ENV=0; shift ;;
        -h|--help)     grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) c_err "unknown arg: $1"; exit 2 ;;
    esac
done

# --- preflight -------------------------------------------------------------
for tool in git cmake; do
    command -v "$tool" >/dev/null 2>&1 || { c_err "missing required tool: $tool"; exit 1; }
done
if ! command -v nvcc >/dev/null 2>&1; then
    c_warn "nvcc (CUDA toolkit) not found on PATH — the CUDA build will fail."
    c_warn "Install a CUDA toolkit, or: conda install -c conda-forge cudatoolkit-dev cmake"
fi

# --- detect Kokkos CUDA arch from the GPU compute capability ----------------
map_cc_to_arch() {
    case "$1" in
        9.0) echo HOPPER90 ;;
        8.9) echo ADA89 ;;
        8.6) echo AMPERE86 ;;
        8.0) echo AMPERE80 ;;
        7.5) echo TURING75 ;;
        7.0) echo VOLTA70 ;;
        *)   echo "" ;;
    esac
}
if [[ -z "$ARCH" ]]; then
    if command -v nvidia-smi >/dev/null 2>&1; then
        cc="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -1 | tr -d ' ')"
        ARCH="$(map_cc_to_arch "$cc")"
        [[ -n "$ARCH" ]] && c_info "detected GPU compute capability $cc -> Kokkos arch $ARCH"
    fi
fi
if [[ -z "$ARCH" ]]; then
    ARCH="AMPERE80"
    c_warn "could not auto-detect GPU arch; defaulting to $ARCH (override with --arch)"
fi

# --- fetch pinned source ----------------------------------------------------
SRC="${PREFIX}/src/lammps-${LAMMPS_TAG}"
mkdir -p "${PREFIX}/src"
if [[ -d "${SRC}/.git" ]]; then
    c_info "reusing existing source at ${SRC}"
else
    c_info "cloning LAMMPS ${LAMMPS_TAG} (shallow) ..."
    git clone --depth 1 --branch "${LAMMPS_TAG}" https://github.com/lammps/lammps.git "${SRC}"
fi

# --- configure (CMake) ------------------------------------------------------
BUILD="${SRC}/build-kokkos-cuda"
mkdir -p "${BUILD}"
PKG_FLAGS=()
for p in "${PACKAGES[@]}"; do PKG_FLAGS+=("-DPKG_${p}=ON"); done

c_info "configuring (KOKKOS+CUDA+OpenMP, FFT=cuFFT, arch=${ARCH}) ..."
cmake -S "${SRC}/cmake" -B "${BUILD}" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="${PREFIX}" \
    -DBUILD_MPI=on -DBUILD_OMP=on \
    -DPKG_KOKKOS=on \
    -DKokkos_ENABLE_CUDA=on \
    -DKokkos_ENABLE_OPENMP=on \
    -DKokkos_ARCH_${ARCH}=on \
    -DFFT_KOKKOS=CUFFT \
    "${PKG_FLAGS[@]}"

# --- build & install --------------------------------------------------------
c_info "building with ${JOBS} jobs (this can take ~20-40 min) ..."
cmake --build "${BUILD}" -j "${JOBS}"
cmake --install "${BUILD}" 2>/dev/null || true

LMP_BIN="${BUILD}/lmp"
[[ -x "$LMP_BIN" ]] || LMP_BIN="${PREFIX}/bin/lmp"
if [[ ! -x "$LMP_BIN" ]]; then
    c_err "build finished but no lmp binary found (looked in ${BUILD} and ${PREFIX}/bin)"
    exit 1
fi
c_ok "built LAMMPS: ${LMP_BIN}"

# --- verify KOKKOS/GPU capability ------------------------------------------
if "$LMP_BIN" -h 2>/dev/null | grep -qi 'KOKKOS'; then
    c_ok "verified: KOKKOS package present in this binary"
else
    c_warn "could not confirm KOKKOS in 'lmp -h' output — check the build log"
fi

# --- write LAMMPS_EXECUTABLE into .env -------------------------------------
if [[ "$WRITE_ENV" -eq 1 ]]; then
    ENV_FILE="${REPO_ROOT}/.env"
    [[ -f "$ENV_FILE" ]] || { [[ -f "${REPO_ROOT}/.env.example" ]] && cp "${REPO_ROOT}/.env.example" "$ENV_FILE"; }
    touch "$ENV_FILE"
    # replace or append LAMMPS_EXECUTABLE / LAMMPS_GPU_PACKAGE
    if grep -q '^LAMMPS_EXECUTABLE=' "$ENV_FILE"; then
        sed -i "s|^LAMMPS_EXECUTABLE=.*|LAMMPS_EXECUTABLE=${LMP_BIN}|" "$ENV_FILE"
    else
        printf 'LAMMPS_EXECUTABLE=%s\n' "$LMP_BIN" >> "$ENV_FILE"
    fi
    if grep -q '^LAMMPS_GPU_PACKAGE=' "$ENV_FILE"; then
        sed -i "s|^LAMMPS_GPU_PACKAGE=.*|LAMMPS_GPU_PACKAGE=kokkos|" "$ENV_FILE"
    else
        printf 'LAMMPS_GPU_PACKAGE=kokkos\n' >> "$ENV_FILE"
    fi
    c_ok "wrote LAMMPS_EXECUTABLE to ${ENV_FILE}"
fi

c_ok "done. LAMMPS ${LAMMPS_TAG} (arch ${ARCH}) ready at ${LMP_BIN}"
