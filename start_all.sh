#!/bin/bash
# =============================================================================
# Asphalt MD Agent - All Services Start Script (version from src/contracts/VERSION)
# =============================================================================
#
# Usage:
#   ./start_all.sh              # Start all services
#   ./start_all.sh --dev        # Start with development mode (auto-reload)
#   ./start_all.sh --check      # Check dependencies only
#   ./start_all.sh --verify     # Verify module imports only
#   ./start_all.sh --stop       # Stop all services
#   ./start_all.sh --status     # Show status of all services
#
# Services started:
#   - Redis (if not running)
#   - FastAPI backend (port 8000)
#   - React frontend (port 5173)
#   - Celery worker (all queues)
#
# Environment variables:
#   API_HOST      - API host (default: 0.0.0.0)
#   API_PORT      - API port (default: 8000)
#   REDIS_HOST    - Redis host (default: localhost)
#   REDIS_PORT    - Redis port (default: 6379)
#   CONCURRENCY   - Celery worker concurrency (default: 4)
#   AUTO_INSTALL_SYSTEM_DEPS - Auto-install missing system deps when possible (default: true)
#
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# TTY detection for inline status updates
if [ -t 1 ]; then IS_TTY=true; else IS_TTY=false; fi

# Inline check helpers: show [INFO] then overwrite with [OK] or [ERROR]
print_checking() {
    if [ "$IS_TTY" = true ]; then
        printf "${BLUE}[INFO]${NC} Checking %s..." "$1"
    else
        echo -e "${BLUE}[INFO]${NC} Checking $1..."
    fi
}

print_check_ok() {
    if [ "$IS_TTY" = true ]; then
        printf "\r${GREEN}[OK]${NC} %-60s\n" "$1"
    else
        echo -e "${GREEN}[OK]${NC} $1"
    fi
}

print_check_fail() {
    if [ "$IS_TTY" = true ]; then
        printf "\r${RED}[ERROR]${NC} %-60s\n" "$1"
    else
        echo -e "${RED}[ERROR]${NC} $1"
    fi
}

# Action helpers: generic INFO->OK overwrite (used by start_api/celery/frontend)
print_action_start() {
    if [ "$IS_TTY" = true ]; then
        printf "${BLUE}[INFO]${NC} %s..." "$1"
    else
        echo -e "${BLUE}[INFO]${NC} $1..."
    fi
}

print_action_ok() {
    if [ "$IS_TTY" = true ]; then
        printf "\r${GREEN}[OK]${NC} %-72s\n" "$1"
    else
        echo -e "${GREEN}[OK]${NC} $1"
    fi
}

# Project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONDA_ENV_NAME="asphalt_env"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
LOG_DIR="$PROJECT_ROOT/logs"
PID_DIR="$PROJECT_ROOT/.pids"
VERSION_FILE="$PROJECT_ROOT/src/contracts/VERSION"
PYPROJECT_FILE="$PROJECT_ROOT/pyproject.toml"
FRONTEND_PACKAGE_FILE="$FRONTEND_DIR/package.json"
FRONTEND_LOCK_FILE="$FRONTEND_DIR/package-lock.json"

if [ -f "$VERSION_FILE" ]; then
    APP_VERSION=$(cat "$VERSION_FILE" | tr -d '[:space:]')
else
    APP_VERSION="unknown"
fi

if [[ "$APP_VERSION" =~ ^([0-9])\.(.+)$ ]]; then
    DISPLAY_VERSION="v0${BASH_REMATCH[1]}.${BASH_REMATCH[2]}"
else
    DISPLAY_VERSION="v${APP_VERSION}"
fi

# Configuration
API_HOST="${API_HOST:-0.0.0.0}"
API_PORT="${API_PORT:-8000}"
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
AUTO_INSTALL_SYSTEM_DEPS="${AUTO_INSTALL_SYSTEM_DEPS:-true}"
PYTHON_BIN=""
PIP_BIN=""

# =============================================================================
# GPU Detection Function
# =============================================================================

detect_gpu_count() {
    # Prefer the backend SSOT eligible-GPU count (excludes sub-threshold display
    # GPUs like an RTX 3050 alongside H200s) so Celery concurrency matches the
    # GPUs the scheduler will actually allocate. Requires PYTHON_BIN/PYTHONPATH
    # (set by setup_conda_env) — detect_gpu_count is called from compute_concurrency
    # which runs after setup, so this path is available at that point.
    if [ -n "$PYTHON_BIN" ]; then
        local eligible
        eligible=$("$PYTHON_BIN" -c "from monitoring.gpu_collector import detect_eligible_compute_gpus as d; print(len(d()))" 2>/dev/null)
        if [ -n "$eligible" ] && [ "$eligible" -gt 0 ] 2>/dev/null; then
            echo "$eligible"
            return
        fi
    fi

    # Fallback: raw nvidia-smi count (all GPUs)
    local count=$(nvidia-smi -L 2>/dev/null | wc -l)
    if [ "$count" -gt 0 ]; then
        echo "$count"
        return
    fi

    # Fallback to lspci
    count=$(lspci 2>/dev/null | grep -i 'nvidia.*vga\|nvidia.*3d' | wc -l)
    if [ "$count" -gt 0 ]; then
        echo "$count"
        return
    fi

    # Default to 1 for CPU-only mode
    echo "1"
}

# compute_concurrency: GPU_SLOTS_PER_GPU(=GPU당 동시잡/MPS) 및 Celery CONCURRENCY 결정.
# budget 정책 SSOT(max_concurrent_jobs_per_gpu)에서 슬롯 수를 읽으므로 PYTHON_BIN/
# PYTHONPATH 준비 후(setup_conda_env 뒤) 호출해야 한다 — 이른 호출 시 정책 읽기가
# 실패해 1로 폴백되어 N=6 슬롯이 Celery 동시성에서 병목된다. 환경변수 override 보존.
# 다중잡 벤치 실측 채택(docs/architecture/md-speed-optimization-exploration.md §7).
compute_concurrency() {
    if [ -z "$GPU_SLOTS_PER_GPU" ]; then
        GPU_SLOTS_PER_GPU=$("$PYTHON_BIN" -c "from contracts.policies.budget import DEFAULT_JOB_BUDGETING_POLICY as P; print(max(1,int(P.max_concurrent_jobs_per_gpu)))" 2>/dev/null || echo 1)
    fi

    # Effective GPU sharing mode: auto -> mig if MIG instances are present, else
    # mps. Drives the MPS-daemon gate (start_mps) and the concurrency sizing.
    if [ -z "${SHARING_MODE:-}" ]; then
        SHARING_MODE=$("$PYTHON_BIN" -c "from monitoring.gpu_collector import resolve_sharing_mode; print(resolve_sharing_mode())" 2>/dev/null || echo mps)
    fi

    # CONCURRENCY: Environment variable > total compute slots across eligible
    # devices (mode-aware: MPS sum(GPU x N), MIG #instances, none #GPUs). Sizes
    # the GPU-execution pool (run_prepared_simulation, simulation.gpu). Builds run
    # in a SEPARATE pool (BUILD_CONCURRENCY) so a large batch of Packmol builds
    # can't saturate CPU or starve GPU dispatch (v01.05.56 P0-B).
    if [ -z "$CONCURRENCY" ]; then
        local slots
        slots=$("$PYTHON_BIN" -c "from monitoring.gpu_collector import total_compute_slots; print(total_compute_slots())" 2>/dev/null || echo 0)
        if [ -z "$slots" ] || ! [ "$slots" -ge 1 ] 2>/dev/null; then
            local gpu_n
            gpu_n=$(detect_gpu_count)
            slots=$(( gpu_n * GPU_SLOTS_PER_GPU ))
        fi
        CONCURRENCY=$slots
        [ "$CONCURRENCY" -lt 1 ] && CONCURRENCY=1
        echo -e "${BLUE}[INFO]${NC} sharing=$SHARING_MODE -> gpu-pool concurrency=$CONCURRENCY"
    fi

    # BUILD_CONCURRENCY: dedicated build pool = max_concurrent_builds (SSOT).
    if [ -z "$BUILD_CONCURRENCY" ]; then
        BUILD_CONCURRENCY=$("$PYTHON_BIN" -c "from contracts.policies.budget import DEFAULT_JOB_BUDGETING_POLICY as P; n=int(P.max_concurrent_builds); print(n if n > 0 else 8)" 2>/dev/null || echo 8)
        [ "$BUILD_CONCURRENCY" -lt 1 ] && BUILD_CONCURRENCY=1
        echo -e "${BLUE}[INFO]${NC} build-pool concurrency=$BUILD_CONCURRENCY (max_concurrent_builds)"
    fi

    # CONTROL_CONCURRENCY: small fixed pool for lightweight beat/orchestration
    # tasks (scheduler, status sync, recovery). These are fast and non-blocking,
    # so a handful of workers is plenty; the point is isolation from GPU/CPU work,
    # not throughput. 4 gives headroom for the ~8 periodic tasks that may overlap.
    if [ -z "$CONTROL_CONCURRENCY" ]; then
        CONTROL_CONCURRENCY=4
    fi
}

# =============================================================================
# Utility Functions
# =============================================================================

print_header() {
    echo -e "${CYAN}============================================${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}============================================${NC}"
}

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_command() {
    if command -v "$1" &> /dev/null; then
        return 0
    else
        return 1
    fi
}

# Resolve the PID actually listening on a TCP port. Used as SSOT for the API
# PID because `nohup setsid uvicorn &` re-forks (setsid becomes group leader),
# leaving the shell's $! pointing at a dead intermediate PID.
port_listener_pid() {
    local port="$1"
    if command -v ss >/dev/null 2>&1; then
        ss -tlnpH "sport = :$port" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | head -1
    elif command -v lsof >/dev/null 2>&1; then
        lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -1
    fi
}

# Resolve a PID by cmdline pattern (for portless services like celery whose
# saved $! is unreliable after the setsid re-fork). Returns the lowest PID
# (the parent worker) so group-kill reaches the spawned children.
pattern_pid() {
    pgrep -f "$1" 2>/dev/null | sort -n | head -1
}

py_exec() {
    "$PYTHON_BIN" "$@"
}

pip_exec() {
    "$PIP_BIN" "$@"
}

get_pyproject_version() {
    if [ -f "$PYPROJECT_FILE" ]; then
        python3 - <<'PY' 2>/dev/null
from pathlib import Path
import tomllib

data = tomllib.loads(Path("pyproject.toml").read_text())
print(data.get("project", {}).get("version", "unknown"))
PY
    else
        echo "unknown"
    fi
}

get_frontend_package_version() {
    if [ -f "$FRONTEND_PACKAGE_FILE" ]; then
        node -p "require('$FRONTEND_PACKAGE_FILE').version" 2>/dev/null || echo "unknown"
    else
        echo "unknown"
    fi
}

print_version_summary() {
    local pyproject_version frontend_version python_version pip_version node_version npm_version
    pyproject_version=$(get_pyproject_version)
    frontend_version=$(get_frontend_package_version)
    python_version=$(py_exec -c "import sys; print(sys.version.split()[0])" 2>/dev/null || echo "unknown")
    pip_version=$(py_exec -m pip --version 2>/dev/null | awk '{print $2}' || echo "unknown")
    node_version=$(node -v 2>/dev/null || echo "missing")
    npm_version=$(npm -v 2>/dev/null || echo "missing")

    print_header "Version Summary"
    echo "App/Contracts: ${DISPLAY_VERSION}"
    echo "Backend pkg:   ${pyproject_version}"
    echo "Frontend pkg:  ${frontend_version}"
    echo "Python/env:    ${python_version} (${CONDA_ENV_NAME})"
    echo "pip:           ${pip_version}"
    echo "Node/npm:      ${node_version} / ${npm_version}"

    if [ "$APP_VERSION" != "$pyproject_version" ] || [ "$APP_VERSION" != "$frontend_version" ]; then
        print_warning "Version mismatch detected (contracts=${APP_VERSION}, backend=${pyproject_version}, frontend=${frontend_version})"
    fi
}

print_dependency_summary() {
    print_header "Dependency Summary"
    # 핵심 패키지를 한 줄에 여러 개씩 묶어 백엔드 2줄 / 프론트 2줄로 압축.
    echo "Backend:"
    py_exec - <<'PY'
from importlib import metadata

packages = [
    ("fastapi", "fastapi"),
    ("sqlalchemy", "sqlalchemy"),
    ("celery", "celery"),
    ("redis", "redis"),
    ("numpy", "numpy"),
    ("rdkit", "rdkit"),
    ("xgboost", "xgboost"),
    ("lightgbm", "lightgbm"),
    ("openai", "openai"),
    ("anthropic", "anthropic"),
]

items = []
for label, dist_name in packages:
    try:
        version = metadata.version(dist_name)
    except metadata.PackageNotFoundError:
        version = "MISSING"
    items.append(f"{label}={version}")

for i in range(0, len(items), 5):
    print("  " + "  ".join(items[i : i + 5]))
PY

    echo "Frontend:"
    (
        cd "$FRONTEND_DIR" && node <<'NODE'
const fs = require('fs');
const path = require('path');
const names = ['react', 'react-dom', 'vite', '@tanstack/react-query', 'axios', 'three'];
const items = [];
for (const name of names) {
  const pkgPath = path.join(process.cwd(), 'node_modules', ...name.split('/'), 'package.json');
  let version = 'MISSING';
  if (fs.existsSync(pkgPath)) {
    version = JSON.parse(fs.readFileSync(pkgPath, 'utf8')).version;
  }
  items.push(`${name}=${version}`);
}
for (let i = 0; i < items.length; i += 3) {
  console.log("  " + items.slice(i, i + 3).join("  "));
}
NODE
    )
}

detect_package_manager() {
    if check_command apt-get; then
        echo "apt"
    elif check_command yum; then
        echo "yum"
    elif check_command dnf; then
        echo "dnf"
    elif check_command pacman; then
        echo "pacman"
    elif check_command brew; then
        echo "brew"
    else
        echo ""
    fi
}

# WSL2 감지. WSL의 NVIDIA 드라이버는 Windows 호스트가 제공하므로(libcuda는
# /usr/lib/wsl/lib) Linux 드라이버 유틸 패키지(nvidia-compute-utils-<major>)를
# 설치할 수 없다 → MPS 바이너리 입수 경로가 막혀 있다. MPS는 네이티브 멀티-GPU
# Ubuntu 서버 전용으로 취급하고, WSL에서는 시분할로 정상 동작시킨다.
is_wsl() {
    grep -qi microsoft /proc/version 2>/dev/null || [ -n "${WSL_DISTRO_NAME:-}" ]
}

install_python_runtime() {
    print_status "Installing Python runtime dependencies..."

    local pm
    pm=$(detect_package_manager)
    case "$pm" in
        "apt")
            sudo apt-get update -qq
            sudo apt-get install -y python3 python3-venv python3-pip
            ;;
        "yum")
            sudo yum install -y python3 python3-pip
            ;;
        "dnf")
            sudo dnf install -y python3 python3-pip
            ;;
        "pacman")
            sudo pacman -S --noconfirm python python-pip
            ;;
        "brew")
            brew install python
            ;;
        *)
            print_error "Unsupported package manager. Install Python3 + venv manually."
            return 1
            ;;
    esac

    return 0
}

install_nodejs_runtime() {
    print_status "Installing Node.js runtime dependencies..."

    local pm
    pm=$(detect_package_manager)
    case "$pm" in
        "apt")
            sudo apt-get update -qq
            sudo apt-get install -y nodejs npm
            ;;
        "yum")
            sudo yum install -y nodejs npm
            ;;
        "dnf")
            sudo dnf install -y nodejs npm
            ;;
        "pacman")
            sudo pacman -S --noconfirm nodejs npm
            ;;
        "brew")
            brew install node
            ;;
        *)
            print_error "Unsupported package manager. Install Node.js >= 18 manually."
            return 1
            ;;
    esac

    return 0
}

install_packmol() {
    print_status "Attempting to install Packmol..."

    local pm
    pm=$(detect_package_manager)
    case "$pm" in
        "apt")
            sudo apt-get update -qq
            sudo apt-get install -y packmol
            ;;
        "yum")
            sudo yum install -y packmol
            ;;
        "dnf")
            sudo dnf install -y packmol
            ;;
        "pacman")
            sudo pacman -S --noconfirm packmol
            ;;
        "brew")
            brew install packmol
            ;;
        *)
            print_warning "No supported package manager for Packmol auto-install."
            return 1
            ;;
    esac

    return 0
}

install_ambertools() {
    print_status "Attempting to install AmberTools (for GAFF2 artifact generation)..."

    # AmberTools is best installed via conda-forge
    if check_command conda; then
        print_status "Installing AmberTools via conda-forge..."
        conda install -y -c conda-forge ambertools 2>&1 | tail -5
        if check_command antechamber; then
            print_success "AmberTools installed successfully via conda"
            return 0
        fi
    fi

    # Try mamba (faster conda alternative)
    if check_command mamba; then
        print_status "Installing AmberTools via mamba..."
        mamba install -y -c conda-forge ambertools 2>&1 | tail -5
        if check_command antechamber; then
            print_success "AmberTools installed successfully via mamba"
            return 0
        fi
    fi

    # pip install as last resort (limited but may work for antechamber/sqm)
    if [ -n "$PIP_BIN" ]; then
        print_status "Trying pip install ambertools..."
        pip_exec install ambertools -q 2>/dev/null || true
        if check_command antechamber; then
            print_success "AmberTools installed via pip"
            return 0
        fi
    fi

    print_warning "Could not auto-install AmberTools."
    return 1
}

# CUDA MPS 제어 바이너리(nvidia-cuda-mps-control / -server) 자동설치.
# MPS는 NVIDIA 드라이버 유틸 패키지(nvidia-compute-utils-<major>)에 포함된다.
# 버전은 반드시 현재 드라이버 major와 일치해야 하므로 nvidia-smi에서 추출한다.
install_mps_tools() {
    if [ "$AUTO_INSTALL_SYSTEM_DEPS" != "true" ]; then
        print_warning "AUTO_INSTALL_SYSTEM_DEPS=false — MPS 자동설치 건너뜀"
        return 1
    fi

    # WSL은 드라이버가 Windows 호스트 제공 → nvidia-compute-utils 설치 불가/무의미.
    if is_wsl; then
        print_warning "WSL 환경 — MPS 자동설치 불가(드라이버 유틸 패키지 부재). 시분할로 동작"
        return 1
    fi

    local pm
    pm=$(detect_package_manager)
    if [ "$pm" != "apt" ]; then
        print_warning "MPS 자동설치는 apt(Ubuntu/Debian)만 지원 — '$pm'에서는 수동 설치 필요"
        return 1
    fi

    # 드라이버 major (예: 580.159.03 -> 580). nvidia-smi 없으면 설치 불가(드라이버 부재).
    local drv_major
    drv_major=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 | cut -d. -f1)
    if [ -z "$drv_major" ]; then
        print_warning "nvidia-smi에서 드라이버 버전 확인 불가 — MPS 자동설치 불가(GPU/드라이버 부재?)"
        return 1
    fi

    print_status "Installing CUDA MPS tools (nvidia-compute-utils-$drv_major, driver-matched)..."
    sudo apt-get update -qq
    if sudo apt-get install -y "nvidia-compute-utils-$drv_major" 2>&1 | tail -3; then
        if command -v nvidia-cuda-mps-control >/dev/null 2>&1; then
            print_success "CUDA MPS tools installed (nvidia-compute-utils-$drv_major)"
            return 0
        fi
    fi
    print_warning "Could not auto-install CUDA MPS tools (nvidia-compute-utils-$drv_major)."
    return 1
}

# NOTE: install_lammps() removed - this project requires custom GPU build
# (KOKKOS + CUDA + OpenMP + cuFFT). Default apt/conda versions are insufficient.
# Users must build LAMMPS from source and set LAMMPS_EXECUTABLE in .env

# =============================================================================
# Check and Setup Conda Environment
# =============================================================================

install_miniforge() {
    print_status "Installing Miniforge (lightweight conda)..."
    local installer="/tmp/miniforge_installer.sh"
    wget -qO "$installer" https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
    bash "$installer" -b -p "$HOME/miniforge3"
    rm -f "$installer"
    eval "$($HOME/miniforge3/bin/conda shell.bash hook)"
    conda init bash 2>/dev/null || true
    print_success "Miniforge installed: $HOME/miniforge3"
}

setup_conda_env() {
    print_header "Conda Environment Setup"

    # Check conda availability
    if ! check_command conda; then
        # Try sourcing miniforge if installed but not in PATH
        if [ -f "$HOME/miniforge3/bin/conda" ]; then
            eval "$($HOME/miniforge3/bin/conda shell.bash hook)"
        fi
    fi

    if ! check_command conda; then
        print_warning "conda not found"
        if [ "$AUTO_INSTALL_SYSTEM_DEPS" = "true" ]; then
            install_miniforge
        else
            print_error "conda is required. Install Miniforge: https://github.com/conda-forge/miniforge"
            exit 1
        fi
    fi

    if ! check_command conda; then
        print_error "conda installation failed"
        exit 1
    fi

    print_success "conda $(conda --version 2>&1 | awk '{print $2}')"

    # Create or activate conda environment
    if ! conda env list 2>/dev/null | grep -q "^${CONDA_ENV_NAME} "; then
        if [ -f "$PROJECT_ROOT/environment.yml" ]; then
            print_status "Creating conda environment from environment.yml..."
            conda env create -f "$PROJECT_ROOT/environment.yml"
            print_success "Conda environment created: $CONDA_ENV_NAME"
        else
            print_error "environment.yml not found at $PROJECT_ROOT"
            exit 1
        fi
    else
        print_success "Conda environment exists: $CONDA_ENV_NAME"
    fi

    # Activate conda environment
    conda activate "$CONDA_ENV_NAME" 2>/dev/null || eval "$(conda shell.bash hook)" && conda activate "$CONDA_ENV_NAME"
    print_success "Conda environment activated: $CONDA_ENV_NAME"

    PYTHON_BIN="$(conda run -n $CONDA_ENV_NAME which python)"
    PIP_BIN="$(conda run -n $CONDA_ENV_NAME which pip)"
    if [ ! -x "$PYTHON_BIN" ] || [ ! -x "$PIP_BIN" ]; then
        print_error "$CONDA_ENV_NAME is invalid (missing python/pip)"
        exit 1
    fi
    print_success "Using conda interpreter: $PYTHON_BIN"

    # Set Python path (src for application code, packages for road_advisor_* packages)
    export PYTHONPATH="${PROJECT_ROOT}/src:${PROJECT_ROOT}/packages:$PYTHONPATH"
}

# =============================================================================
# Check and Install Python Dependencies
# =============================================================================

install_python_deps() {
    print_header "Python Dependencies"
    local audit_output audit_status

    set +e
    audit_output=$(py_exec - "$PYPROJECT_FILE" <<'PY'
from __future__ import annotations

import sys
import tomllib
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

project_file = Path(sys.argv[1])
data = tomllib.loads(project_file.read_text())
project = data.get("project", {})
optional = project.get("optional-dependencies", {})

requirement_strings = list(project.get("dependencies", []))
for group in ("db", "queue", "api", "ml", "llm"):
    requirement_strings.extend(optional.get(group, []))

seen: dict[str, Requirement] = {}
for raw in requirement_strings:
    req = Requirement(raw)
    seen[req.name.lower()] = req

issues = 0
for key in sorted(seen):
    req = seen[key]
    try:
        installed = metadata.version(req.name)
    except metadata.PackageNotFoundError:
        print(f"MISSING {req.name} ({req.specifier or 'any'})")
        issues += 1
        continue

    if req.specifier and not req.specifier.contains(Version(installed), prereleases=True):
        print(f"MISMATCH {req.name} installed={installed} required={req.specifier}")
        issues += 1
    else:
        print(f"OK {req.name}=={installed}")

try:
    pymatgen_version = metadata.version("pymatgen")
    print(f"OPTIONAL pymatgen=={pymatgen_version}")
except metadata.PackageNotFoundError:
    print("OPTIONAL pymatgen=MISSING")

raise SystemExit(issues)
PY
)
    audit_status=$?
    set -e

    echo "$audit_output" | grep -E '^(MISSING|MISMATCH) ' || true
    echo "$audit_output" | grep -E '^OPTIONAL ' || true

    if [ $audit_status -eq 0 ]; then
        print_success "Python dependencies verified against pyproject.toml"
        return 0
    fi

    print_warning "Installing/updating Python dependencies from pyproject.toml..."
    pip_exec install --upgrade pip -q
    pip_exec install -e "$PROJECT_ROOT[db,queue,api,ml,llm]" -q

    set +e
    audit_output=$(py_exec - "$PYPROJECT_FILE" <<'PY'
from __future__ import annotations

import sys
import tomllib
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

project_file = Path(sys.argv[1])
data = tomllib.loads(project_file.read_text())
project = data.get("project", {})
optional = project.get("optional-dependencies", {})

requirement_strings = list(project.get("dependencies", []))
for group in ("db", "queue", "api", "ml", "llm"):
    requirement_strings.extend(optional.get(group, []))

seen: dict[str, Requirement] = {}
for raw in requirement_strings:
    req = Requirement(raw)
    seen[req.name.lower()] = req

issues = 0
for key in sorted(seen):
    req = seen[key]
    try:
        installed = metadata.version(req.name)
    except metadata.PackageNotFoundError:
        print(f"MISSING {req.name} ({req.specifier or 'any'})")
        issues += 1
        continue

    if req.specifier and not req.specifier.contains(Version(installed), prereleases=True):
        print(f"MISMATCH {req.name} installed={installed} required={req.specifier}")
        issues += 1

raise SystemExit(issues)
PY
)
    audit_status=$?
    set -e
    if [ $audit_status -ne 0 ]; then
        echo "$audit_output"
        print_error "Python dependency installation did not converge"
        return 1
    fi

    print_success "Python dependencies installed/updated"
}

# =============================================================================
# Ensure Database Schema Compatibility
# =============================================================================

ensure_db_schema_compat() {
    print_header "Database Schema Compatibility"

    py_exec - <<'PY'
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import unquote

REQUIRED_COLUMNS = {
    "additive_type": "ALTER TABLE experiments ADD COLUMN additive_type VARCHAR(50) DEFAULT NULL",
    "additive_wt": "ALTER TABLE experiments ADD COLUMN additive_wt FLOAT DEFAULT 0.0",
    "additive_mol_id": "ALTER TABLE experiments ADD COLUMN additive_mol_id VARCHAR(100) DEFAULT NULL",
}

REQUIRED_INDEXES = {
    "ix_experiments_additive_type": "CREATE INDEX IF NOT EXISTS ix_experiments_additive_type ON experiments (additive_type)",
    "ix_experiments_additive_mol_id": "CREATE INDEX IF NOT EXISTS ix_experiments_additive_mol_id ON experiments (additive_mol_id)",
}

def resolve_db_url() -> str:
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url

    try:
        from config.settings import get_settings
        settings_url = get_settings().database.url
        if settings_url:
            return settings_url
    except Exception:
        pass

    try:
        from database.connection import get_default_url
        return get_default_url()
    except Exception:
        root = Path.cwd()
        return f"sqlite:///{root / 'asphalt_agent.db'}"


def sqlite_path_from_url(url: str) -> Path | None:
    if not url.startswith("sqlite"):
        return None

    if url.startswith("sqlite:///:memory:"):
        return None

    # sqlite:///abs/path.db
    if url.startswith("sqlite:///"):
        raw = url[len("sqlite:///") :]
        return Path(unquote(raw))

    # sqlite://relative/path.db
    if url.startswith("sqlite://"):
        raw = url[len("sqlite://") :]
        return Path(unquote(raw))

    return None


db_url = resolve_db_url()
db_path = sqlite_path_from_url(db_url)

if db_path is None:
    print(f"[INFO] Non-SQLite DATABASE_URL detected ({db_url}); skipping SQLite schema patch.")
    sys.exit(0)

db_path.parent.mkdir(parents=True, exist_ok=True)

with sqlite3.connect(str(db_path)) as conn:
    cur = conn.execute("PRAGMA table_info(experiments)")
    rows = cur.fetchall()
    if not rows:
        print(f"[INFO] experiments table not found in {db_path}; no compatibility patch needed.")
        sys.exit(0)

    existing_columns = {row[1] for row in rows}
    applied = []

    for col_name, sql in REQUIRED_COLUMNS.items():
        if col_name not in existing_columns:
            conn.execute(sql)
            applied.append(col_name)

    for idx_name, sql in REQUIRED_INDEXES.items():
        conn.execute(sql)

    conn.commit()

if applied:
    print(f"Applied schema patch: {', '.join(applied)}", file=__import__('sys').stderr)
else:
    print(f"Schema already compatible", file=__import__('sys').stderr)
PY
    if [ $? -eq 0 ]; then
        print_success "Database schema compatibility check complete"
    else
        print_error "Database schema compatibility check failed"
        return 1
    fi
}

# =============================================================================
# Check Simulation Tools (Packmol, LAMMPS)
# =============================================================================

check_simulation_tools() {
    print_header "Simulation Tools Check"

    local failed=0

    # Check Packmol
    print_checking "Packmol"
    local packmol_cmd=""
    if check_command packmol; then
        packmol_cmd="packmol"
    elif [ -x "$PROJECT_ROOT/bin/packmol" ]; then
        packmol_cmd="$PROJECT_ROOT/bin/packmol"
    fi

    if [ -n "$packmol_cmd" ]; then
        local packmol_version=$($packmol_cmd < /dev/null 2>&1 | grep -i "version" | head -1 || echo "unknown")
        print_check_ok "Packmol: $packmol_cmd"
    else
        if [ "$AUTO_INSTALL_SYSTEM_DEPS" = "true" ]; then
            install_packmol || true
            if check_command packmol; then
                packmol_cmd="packmol"
                local packmol_version=$($packmol_cmd < /dev/null 2>&1 | grep -i "version" | head -1 || echo "unknown")
                print_check_ok "Packmol: $packmol_cmd"
            fi
        fi
    fi

    if [ -z "$packmol_cmd" ]; then
        print_error "Packmol NOT installed!"
        echo "  Without Packmol, molecule packing will use MOCK mode (no overlap prevention)"
        echo ""
        echo "  Install options:"
        echo "    Ubuntu/Debian: sudo apt install packmol"
        echo "    Conda:         conda install -c conda-forge packmol"
        echo "    Source:        https://m3g.github.io/packmol/"
        echo ""
        failed=1
    fi

    # Check LAMMPS
    print_checking "LAMMPS"
    local lammps_cmd=""

    # First check .env file for LAMMPS_EXECUTABLE
    if [ -f "$PROJECT_ROOT/.env" ]; then
        local env_lammps=$(grep -E "^LAMMPS_EXECUTABLE=" "$PROJECT_ROOT/.env" 2>/dev/null | cut -d'=' -f2 | tr -d '"' | tr -d "'")
        if [ -n "$env_lammps" ] && [ -x "$env_lammps" ]; then
            lammps_cmd="$env_lammps"
            print_status "Found LAMMPS from .env: $lammps_cmd"
        fi
    fi

    # Fallback to PATH search if not found in .env
    if [ -z "$lammps_cmd" ]; then
        if check_command lmp; then
            lammps_cmd="lmp"
        elif check_command lmp_mpi; then
            lammps_cmd="lmp_mpi"
        elif check_command lmp_kokkos; then
            lammps_cmd="lmp_kokkos"
        elif check_command lmp_gpu; then
            lammps_cmd="lmp_gpu"
        fi
    fi

    if [ -n "$lammps_cmd" ]; then
        local lammps_version=$($lammps_cmd -h 2>&1 | grep -i "LAMMPS" | head -1 || echo "unknown")
        print_check_ok "LAMMPS: $lammps_cmd"

        # Verify required packages for GAFF2 simulations
        # Packages may span multiple lines after "Installed packages:" with a blank line separator
        local installed_pkgs=$($lammps_cmd -h 2>&1 | grep -A5 "Installed packages:" | grep -v "Installed packages:" | grep -v "^$" | tr '\n' ' ' || echo "")
        local required_pkgs=("EXTRA-MOLECULE" "EXTRA-DUMP" "EXTRA-FIX" "EXTRA-PAIR" "KOKKOS" "KSPACE" "MOLECULE" "CLASS2" "MANYBODY" "REAXFF" "RIGID")
        local missing_pkgs=()
        for pkg in "${required_pkgs[@]}"; do
            if ! echo "$installed_pkgs" | grep -qw "$pkg"; then
                missing_pkgs+=("$pkg")
            fi
        done
        if [ ${#missing_pkgs[@]} -gt 0 ]; then
            print_error "LAMMPS missing required packages: ${missing_pkgs[*]}"
            echo "  Current packages: $installed_pkgs"
            echo "  Rebuild LAMMPS with: cmake -D PKG_<NAME>=ON for each missing package"
            echo "  Critical: EXTRA-MOLECULE is required for GAFF2 dihedral_style fourier"
            failed=1
        else
            print_check_ok "LAMMPS packages verified (${#required_pkgs[@]} required)"
        fi
    else
        # NOTE: LAMMPS auto-install is disabled because this project requires
        # a custom GPU build (KOKKOS + CUDA + OpenMP + cuFFT + specific packages).
        # The default apt/conda versions do not meet these requirements.
        print_error "LAMMPS NOT configured!"
        echo "  This project requires LAMMPS with GPU acceleration (KOKKOS + CUDA)."
        echo ""
        echo "  Setup steps:"
        echo "    1. Build LAMMPS from source with required packages:"
        echo "       - KOKKOS (CUDA + OpenMP backend)"
        echo "       - KSPACE, CLASS2, MOLECULE, EXTRA-PAIR, REAXFF, etc."
        echo "       See: https://docs.lammps.org/Build.html"
        echo ""
        echo "    2. Set the path in .env file:"
        echo "       LAMMPS_EXECUTABLE=/path/to/your/lmp"
        echo ""
        echo "    Example .env entry:"
        echo "       LAMMPS_EXECUTABLE=/home/user/lammps/build/lmp"
        echo ""
        failed=1
    fi

    # Check AmberTools (antechamber, parmchk2, tleap — required for GAFF2 artifact generation)
    print_checking "AmberTools (GAFF2)"
    local ambertools_ok=true
    local ambertools_cmds=("antechamber" "parmchk2" "tleap")
    local ambertools_missing=()

    for cmd in "${ambertools_cmds[@]}"; do
        if ! check_command "$cmd"; then
            ambertools_missing+=("$cmd")
            ambertools_ok=false
        fi
    done

    if [ "$ambertools_ok" = true ]; then
        local antechamber_path=$(which antechamber 2>/dev/null || echo "unknown")
        print_check_ok "AmberTools: antechamber, parmchk2, tleap"
    else
        print_warning "AmberTools missing commands: ${ambertools_missing[*]}"
        if [ "$AUTO_INSTALL_SYSTEM_DEPS" = "true" ]; then
            install_ambertools || true
            # Re-check after install attempt
            ambertools_ok=true
            for cmd in "${ambertools_cmds[@]}"; do
                if ! check_command "$cmd"; then
                    ambertools_ok=false
                fi
            done
            if [ "$ambertools_ok" = true ]; then
                print_success "AmberTools installed successfully"
            fi
        fi
    fi

    if [ "$ambertools_ok" = false ]; then
        print_error "AmberTools NOT installed!"
        echo "  AmberTools is required for GAFF2 force field artifact generation."
        echo "  Key commands: antechamber (atom typing + AM1-BCC charges),"
        echo "                parmchk2 (missing parameter check),"
        echo "                tleap (topology builder)"
        echo ""
        echo "  Install options:"
        echo "    Conda (recommended): conda install -c conda-forge ambertools"
        echo "    Mamba:               mamba install -c conda-forge ambertools"
        echo "    Manual:              https://ambermd.org/GetAmber.php"
        echo ""
        failed=1
    fi

    if [ $failed -eq 0 ]; then
        print_success "All simulation tools verified!"
        return 0
    else
        print_warning "Some simulation tools are missing - simulations may fail or use mock mode"
        return 1
    fi
}

# =============================================================================
# Verify Critical Module Imports
# =============================================================================

verify_modules() {
    print_header "Module Import Verification"

    local failed=0
    local ok_list=() warn_list=()

    # _mod NAME SEVERITY(error|warn) IMPORT_CODE
    # Collect results so the common case prints one compact OK line; only
    # problems surface individually. Critical (error) failures abort startup.
    _mod() {
        local name="$1" sev="$2" code="$3"
        if py_exec -c "$code" 2>/dev/null; then
            ok_list+=("$name")
        elif [ "$sev" = "error" ]; then
            failed=1
            warn_list+=("$name [CRITICAL]")
        else
            warn_list+=("$name")
        fi
    }

    _mod core error "
from contracts.schemas import BuildRequest, ProtocolRequest, MetricResult
from contracts.policies.tier import DEFAULT_TIER_POLICY
from contracts.policies.ml_policy import DEFAULT_ML_POLICY
from contracts.errors import BuildError, ErrorCode
from common.pathing import get_experiment_path
from common.hashing import compute_topology_hash"
    _mod config warn "from config.settings import Settings"
    _mod database error "
from database.connection import session_scope
from database.repositories.experiment_repo import ExperimentRepository
from database.repositories.metric_repo import MetricRepository
from database.repositories.model_version_repo import ModelVersionRepository"
    _mod api warn "
from api.application import app
from api.deps import get_molecule_db"
    _mod orchestrator warn "
from orchestrator.tasks import run_screening_simulation, cleanup_old_jobs
from orchestrator.pipeline import Pipeline
from orchestrator.continuous_loop import ContinuousLearningLoop
from orchestrator.gpu_service import GPUService
from orchestrator.celery_job_manager import CeleryJobManager"
    _mod builder error "
from builder.structure_builder import StructureBuilder
from builder.layer_builder import LayerBuilder"
    _mod forcefield error "
from forcefield.interface_ff import INTERFACE_FF_MINERAL_PARAMS
from forcefield.uff_element_fallback import UFF_ELEMENT_FALLBACKS"
    _mod metrics error "
from metrics.calculator import MetricsCalculator
from metrics.layer_metrics import AdhesionEnergyCalculator"
    _mod rdkit warn "
from rdkit import Chem
from rdkit.Chem import Descriptors"
    _mod ml warn "
from ml.data_loader import DataLoader
from ml.trainer import Trainer
from ml.models import PropertyPredictor
from ml.multi_target import MultiTargetPredictor
from ml.ood_detector import OODDetector
from ml.uncertainty import UncertaintyEstimator
from ml.feature_store import FeatureStore
from ml.additive_features import AdditiveFeatureExtractor"
    _mod mlops warn "
from ml.model_registry import ModelRegistry, ComparisonResult
from ml.drift_detector import DriftDetector, DriftType, DriftReport
from ml.retrainer import ModelRetrainer, should_retrain"
    _mod recommendation warn "
from recommendation.agent import RecommendationAgent
from recommendation.bayesian_optimizer import BayesianOptimizer
from recommendation.inverse_designer import InverseDesigner
from recommendation.pareto import ParetoFront"
    _mod validation warn "
from validation.reaxff_validator import ReaxFFValidator
from validation.reaxff_selector import ReaxFFSelector"
    _mod monitoring warn "from monitoring.gpu_collector import GPUCollector, create_gpu_collector"
    _mod llm warn "from llm.client_factory import create_llm_client"

    print_check_ok "Modules OK (${#ok_list[@]}): ${ok_list[*]}"
    for w in "${warn_list[@]}"; do print_warning "$w import failed"; done

    if [ $failed -eq 0 ]; then
        return 0
    else
        print_error "Critical module(s) failed verification"
        return 1
    fi
}

# =============================================================================
# Check and Setup Redis
# =============================================================================

install_redis() {
    print_status "Redis is not installed. Attempting to install..."

    # Detect package manager and install Redis
    if check_command apt-get; then
        # Debian/Ubuntu
        print_status "Detected Debian/Ubuntu system. Installing Redis via apt..."
        sudo apt-get update -qq
        sudo apt-get install -y redis-server
        print_success "Redis installed successfully"
        return 0
    elif check_command yum; then
        # RHEL/CentOS
        print_status "Detected RHEL/CentOS system. Installing Redis via yum..."
        sudo yum install -y redis
        print_success "Redis installed successfully"
        return 0
    elif check_command dnf; then
        # Fedora
        print_status "Detected Fedora system. Installing Redis via dnf..."
        sudo dnf install -y redis
        print_success "Redis installed successfully"
        return 0
    elif check_command pacman; then
        # Arch Linux
        print_status "Detected Arch Linux system. Installing Redis via pacman..."
        sudo pacman -S --noconfirm redis
        print_success "Redis installed successfully"
        return 0
    elif check_command brew; then
        # macOS
        print_status "Detected macOS system. Installing Redis via Homebrew..."
        brew install redis
        print_success "Redis installed successfully"
        return 0
    else
        print_error "Could not detect package manager. Please install Redis manually."
        return 1
    fi
}

check_redis() {
    print_header "Redis Check"

    if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping &>/dev/null; then
        print_success "Redis is running on ${REDIS_HOST}:${REDIS_PORT}"
        return 0
    else
        print_warning "Redis is not running"

        # Check if Redis is installed
        if ! check_command redis-cli || ! check_command redis-server; then
            print_warning "Redis is not installed"
            if ! install_redis; then
                print_error "Failed to install Redis"
                return 1
            fi
        fi

        # Try to start Redis via systemctl
        if check_command systemctl; then
            print_status "Attempting to start Redis via systemctl..."
            # Enable and start redis-server
            sudo systemctl enable redis-server 2>/dev/null || true
            if sudo systemctl start redis-server 2>/dev/null; then
                sleep 1
                if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping &>/dev/null; then
                    print_success "Redis started successfully"
                    return 0
                fi
            fi
        fi

        # Try redis-server directly (for systems without systemd or WSL)
        if check_command redis-server; then
            print_status "Attempting to start Redis directly..."
            redis-server --daemonize yes --port "$REDIS_PORT"
            sleep 1
            if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping &>/dev/null; then
                print_success "Redis started successfully"
                return 0
            fi
        fi

        print_error "Could not start Redis. Please start it manually:"
        echo "  sudo systemctl start redis-server"
        echo "  OR"
        echo "  redis-server --daemonize yes"
        echo "  OR"
        echo "  docker run -d -p 6379:6379 redis:alpine"
        return 1
    fi
}

# =============================================================================
# Check and Install Node.js Dependencies
# =============================================================================

install_node_deps() {
    print_header "Node.js Dependencies"

    if ! check_command node || ! check_command npm; then
        print_warning "Node.js/npm not found"
        if [ "$AUTO_INSTALL_SYSTEM_DEPS" = "true" ]; then
            install_nodejs_runtime || true
        fi
    fi

    if ! check_command node; then
        print_error "Node.js is not installed. Please install Node.js >= 18"
        return 1
    fi
    local node_version=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
    if [ "$node_version" -lt 18 ]; then
        print_warning "Node.js version $node_version detected. Version >= 18 recommended."
    else
        print_success "Node.js $(node -v) detected"
    fi

    if ! check_command npm; then
        print_error "npm is not installed"
        return 1
    fi

    cd "$FRONTEND_DIR"

    local node_audit node_audit_status install_cmd
    set +e
    node_audit=$(node <<'NODE'
const fs = require('fs');
const path = require('path');

const pkg = JSON.parse(fs.readFileSync('package.json', 'utf8'));
const lock = fs.existsSync('package-lock.json')
  ? JSON.parse(fs.readFileSync('package-lock.json', 'utf8'))
  : null;

const expected = {
  ...(pkg.dependencies || {}),
  ...(pkg.devDependencies || {}),
};

const missing = [];
const mismatched = [];
for (const name of Object.keys(expected).sort()) {
  const packageJsonPath = path.join(process.cwd(), 'node_modules', ...name.split('/'), 'package.json');
  if (!fs.existsSync(packageJsonPath)) {
    missing.push(name);
    continue;
  }
  const installed = JSON.parse(fs.readFileSync(packageJsonPath, 'utf8')).version;
  const locked = lock?.packages?.[`node_modules/${name}`]?.version;
  if (locked && installed !== locked) {
    mismatched.push(`${name} installed=${installed} locked=${locked}`);
  } else {
    console.log(`OK ${name}==${installed}`);
  }
}

for (const name of missing) console.log(`MISSING ${name}`);
for (const item of mismatched) console.log(`MISMATCH ${item}`);
process.exit(missing.length || mismatched.length ? 1 : 0);
NODE
)
    node_audit_status=$?
    set -e

    echo "$node_audit" | grep -E '^(MISSING|MISMATCH|EXTRANEOUS) ' || true

    if [ ! -d "node_modules" ] || [ $node_audit_status -ne 0 ]; then
        if [ -f "$FRONTEND_LOCK_FILE" ]; then
            install_cmd="npm ci --no-audit --no-fund"
        else
            install_cmd="npm install --no-audit --no-fund"
        fi
        print_status "Installing Node.js dependencies via: $install_cmd"
        eval "$install_cmd"
        if [ $? -ne 0 ]; then
            print_error "Failed to install Node.js dependencies"
            cd "$PROJECT_ROOT"
            return 1
        fi
        print_success "Node.js dependencies installed"
    else
        print_success "Node.js dependencies verified"
    fi

    cd "$PROJECT_ROOT"
}

# =============================================================================
# Create Required Directories
# =============================================================================

create_directories() {
    mkdir -p "$LOG_DIR"
    mkdir -p "$PID_DIR"
}

# =============================================================================
# Start Services
# =============================================================================

start_api() {
    print_action_start "Starting API server"

    local reload_flag=""
    if [ "$DEV_MODE" = true ]; then
        reload_flag="--reload"
    fi

    cd "$PROJECT_ROOT"
    # setsid: start uvicorn as a new session/process-group leader so the
    # parent PID equals PGID. Stop path can then signal the entire group
    # including multiprocessing.spawn workers whose cmdline does NOT contain
    # "uvicorn api.main:app" (and thus evade `pkill -f` pattern matching).
    if command -v setsid >/dev/null 2>&1; then
        nohup setsid "$PYTHON_BIN" -m uvicorn api.main:app \
            --host "$API_HOST" \
            --port "$API_PORT" \
            $reload_flag \
            > "$LOG_DIR/api.log" 2>&1 &
    else
        nohup "$PYTHON_BIN" -m uvicorn api.main:app \
            --host "$API_HOST" \
            --port "$API_PORT" \
            $reload_flag \
            > "$LOG_DIR/api.log" 2>&1 &
    fi

    local api_pid=$!
    echo "$api_pid" > "$PID_DIR/api.pid"

    # Poll for the port to bind. setsid re-forks uvicorn (so $! may be a dead
    # intermediate PID), and import-time molecule-library loading can delay the
    # bind by 10s+. Resolve the real listener as SSOT once it appears.
    local listener_pid="" waited=0
    while [ "$waited" -lt 30 ]; do
        listener_pid=$(port_listener_pid "$API_PORT")
        [ -n "$listener_pid" ] && break
        sleep 1
        waited=$((waited + 1))
    done
    if [ -n "$listener_pid" ]; then
        api_pid="$listener_pid"
        echo "$api_pid" > "$PID_DIR/api.pid"
    else
        rm -f "$PID_DIR/api.pid"
        print_check_fail "API server failed to bind port $API_PORT within ${waited}s"
        echo "  Logs: $LOG_DIR/api.log"
        echo "  Last log lines:"
        tail -n 20 "$LOG_DIR/api.log" 2>/dev/null || true
        return 1
    fi

    print_action_ok "API server started (PID: $api_pid, Port: $API_PORT)"
}

start_frontend() {
    print_action_start "Starting frontend server"

    cd "$FRONTEND_DIR"
    nohup npm run dev > "$LOG_DIR/frontend.log" 2>&1 &
    local fe_pid=$!
    echo "$fe_pid" > "$PID_DIR/frontend.pid"

    # Wait for Vite to start and detect actual port
    sleep 3
    local frontend_port=$(grep -oP 'localhost:\K[0-9]+' "$LOG_DIR/frontend.log" | head -1)
    frontend_port="${frontend_port:-5173}"
    echo "$frontend_port" > "$PID_DIR/frontend.port"

    print_action_ok "Frontend server started (PID: $fe_pid, Port: $frontend_port)"

    cd "$PROJECT_ROOT"
}

# CUDA MPS 데몬 — GPU당 다중잡(slots>1)을 진짜 동시 실행시키는 전제.
# slots=1이면 불필요하므로 건너뜀. root/재부팅/compute-mode 변경 불요(Default 모드).
export CUDA_MPS_PIPE_DIRECTORY="${CUDA_MPS_PIPE_DIRECTORY:-/tmp/nvidia-mps}"
export CUDA_MPS_LOG_DIRECTORY="${CUDA_MPS_LOG_DIRECTORY:-/tmp/nvidia-mps-log}"
start_mps() {
    # MPS only applies in 'mps' sharing mode. In 'mig' the MIG instances provide
    # hardware isolation (no MPS); in 'none' it's 1 job/GPU.
    if [ "${SHARING_MODE:-mps}" != "mps" ]; then
        echo -e "${BLUE}[INFO]${NC} sharing mode=${SHARING_MODE:-mps} — MPS 미사용 (MIG=인스턴스 격리 / none=1잡/GPU)"
        return 0
    fi
    if [ "${GPU_SLOTS_PER_GPU:-1}" -le 1 ]; then
        return 0  # 단일잡/GPU — MPS 불필요
    fi
    if ! command -v nvidia-cuda-mps-control >/dev/null 2>&1; then
        # WSL은 드라이버가 Windows 호스트 제공 → nvidia-compute-utils 설치 불가
        # (MPS 바이너리 입수 경로 부재). 자동설치 시도 없이 시분할로 정상 동작.
        if is_wsl; then
            echo -e "${BLUE}[INFO]${NC} WSL 환경 — CUDA MPS는 네이티브 멀티-GPU 서버 전용. 단일 GPU WSL은 시분할로 정상 동작(설치 시도 생략)"
            return 0
        fi
        # 다중잡(slots>1)인데 MPS 바이너리 부재 → 자동설치 시도(드라이버-매칭).
        echo -e "${YELLOW}[WARN]${NC} nvidia-cuda-mps-control 없음 — 자동설치 시도"
        install_mps_tools || true
    fi
    if ! command -v nvidia-cuda-mps-control >/dev/null 2>&1; then
        echo -e "${YELLOW}[WARN]${NC} MPS 미설치/설치 실패 — MPS 미기동(시분할로 동작, 처리량 저하)"
        return 0
    fi
    # NOTE: use `pgrep -f` (full cmdline), NOT `pgrep -x`. The kernel truncates
    # the process comm name to 15 chars, but "nvidia-cuda-mps-control" is 23 —
    # so `-x` (exact comm match) never matches and reports a false negative.
    if pgrep -f nvidia-cuda-mps-control >/dev/null 2>&1; then
        echo -e "${BLUE}[INFO]${NC} MPS 데몬 이미 실행 중"
        return 0
    fi
    print_action_start "Starting CUDA MPS daemon (slots/GPU=$GPU_SLOTS_PER_GPU)"
    mkdir -p "$CUDA_MPS_PIPE_DIRECTORY" "$CUDA_MPS_LOG_DIRECTORY"
    # Launch the MPS daemon with CUDA_VISIBLE_DEVICES UNSET so it manages ALL
    # physical GPUs (v01.06.16). A stale CVD in the launching shell — a terminal
    # that sourced an old ~/.bashrc, or a cached process/shell snapshot — would
    # otherwise restrict the daemon to a subset (e.g. "0,1,2,3,4"); then EVERY
    # CUDA client on the node (all route through the default /tmp/nvidia-mps pipe)
    # gets cudaErrorNoDevice for the excluded GPU (GPU 6), so jobs assigned there
    # die at init and the GPU sits idle. The app selects GPUs via UUID routing +
    # the eligibility/slot gate, so the daemon seeing all GPUs (incl. an
    # ineligible RTX 3050) is correct and safe. See memory gpu-uuid-routing-principle.
    env -u CUDA_VISIBLE_DEVICES nvidia-cuda-mps-control -d >/dev/null 2>&1
    sleep 1
    if pgrep -f nvidia-cuda-mps-control >/dev/null 2>&1; then
        print_action_ok "CUDA MPS daemon (pipe=$CUDA_MPS_PIPE_DIRECTORY)"
    else
        echo -e "${YELLOW}[WARN]${NC} MPS 데몬 기동 실패 — 시분할로 동작"
    fi
}

stop_mps() {
    # Gracefully stop the MPS control daemon on shutdown (v01.05.56 M3). Without
    # this a stale daemon + pipe dir survive --stop, and the next start_mps
    # pgrep mistakes the stale daemon for a healthy one. `quit -t N` force-stops
    # MPS servers after N s if clients linger (bare `quit` blocks until they
    # finish). Call AFTER celery (and its LAMMPS clients) are terminated.
    command -v nvidia-cuda-mps-control >/dev/null 2>&1 || return 0
    pgrep -f nvidia-cuda-mps-control >/dev/null 2>&1 || return 0
    echo "quit -t 20" | nvidia-cuda-mps-control >/dev/null 2>&1 || true
}

# Defense A (v01.06.06): pre-warm the LAMMPS capability cache while the system is
# IDLE, before Celery workers consume the queue. The probe (lmp -h + a real
# KOKKOS-GPU run) is expensive (~8s even idle). If it FIRST runs under a heavy
# job load (e.g. 300 jobs submitted at once) it exceeds the 15s timeout, and the
# degraded result (kokkos_backend=none -> accel_mode=mpi_only) gets written to
# the SHARED file cache — so every worker then runs LAMMPS without '-k on' and
# jobs fail en masse with "Package kokkos command without KOKKOS package
# enabled". Warming here guarantees a correct cache before any load arrives.
warm_lammps_caps() {
    [ -n "$PYTHON_BIN" ] || return 0
    local cache="${PROJECT_ROOT}/lammps_caps_cache.json"
    # If an existing cache is DEGRADED (a GPU is present but KOKKOS wasn't
    # detected — the signature of a probe that timed out under load), remove it
    # so the warm below does a FRESH idle probe instead of re-loading the bad
    # result (get_lammps_caps would otherwise just return the cached bad value).
    if [ -f "$cache" ] && grep -q '"gpu_detected": true' "$cache" 2>/dev/null \
        && grep -qE '"kokkos_backend": *"none"|"accel_mode": *"(mpi_only|serial)"' "$cache" 2>/dev/null; then
        print_warning "Degraded LAMMPS caps cache (no KOKKOS on a GPU host) — removing for a fresh idle probe"
        rm -f "$cache"
    fi
    print_action_start "Warming LAMMPS capability cache (idle, before workers)"
    local out
    out=$("$PYTHON_BIN" -c "from config.settings import get_settings; from orchestrator.lammps_probe import get_lammps_caps; s=get_settings(); c=get_lammps_caps(s.lammps.executable, mpi_command=s.lammps.mpi_command); print(c.accel_mode, c.kokkos_backend, c.gpu_detected)" 2>/dev/null)
    if echo "$out" | grep -q "kokkos_gpu"; then
        print_action_ok "LAMMPS caps warmed: $out"
    elif [ -n "$out" ]; then
        print_warning "LAMMPS caps degraded after warm: '$out' — jobs may run CPU-only. Check GPU/driver/KOKKOS build."
    else
        print_warning "LAMMPS caps warm produced no result — workers will probe lazily (timeout risk under load)"
    fi
}

start_celery() {
    print_action_start "Starting Celery workers (3-pool: cpu + gpu + control)"

    # Export Redis settings
    export CELERY_BROKER_URL="redis://${REDIS_HOST}:${REDIS_PORT}/0"
    export CELERY_RESULT_BACKEND="redis://${REDIS_HOST}:${REDIS_PORT}/1"

    cd "$PROJECT_ROOT"
    # Two dedicated worker pools (v01.05.56 P0-B) decouple the two concurrencies
    # that v54 conflated into one pool. Builds (CPU/Packmol) and GPU execution
    # are already separate Celery tasks on separate queues; giving each its own
    # pool means a large build backlog waits in-queue instead of blocking
    # workers needed for GPU dispatch. setsid isolates the process group from
    # api's group-kill. Unique --hostname per pool keeps control/inspect/revoke
    # and PID tracking accurate.

    # Three resource-class pools (v01.06.14) decouple work by the resource it
    # contends for, restoring the 1-worker = 1-GPU-slot invariant:
    #   - cpu@   : CPU/RAM-bound Packmol builds + CPU post-processing (metrics,
    #              e_inter rerun) + misc default. Capped at max_concurrent_builds.
    #   - gpu@   : ONLY run_prepared_simulation (simulation.gpu) + priority — the
    #              long-blocking GPU jobs. concurrency == total GPU slots, so every
    #              dispatched GPU job is consumed immediately (no ready job ever
    #              waits holding a GPU; kills the dispatch_mismatch / slot-churn).
    #   - control@: ONLY the lightweight beat/orchestration tasks (scheduler,
    #              status sync, recovery, inventory). Small fixed pool that NEVER
    #              competes with GPU/CPU work, so the dispatcher always runs even
    #              when gpu@ is 100% saturated (fixes control-plane starvation).
    # setsid isolates the process group from api's group-kill; unique --hostname
    # per pool keeps control/inspect/revoke and PID tracking accurate.

    # CPU pool: Packmol builds + CPU post-processing + catch-all default.
    nohup setsid "$PYTHON_BIN" -m celery -A orchestrator.celery_app:celery_app worker \
        --queues=simulation,simulation.screening,simulation.confirm,simulation.viscosity,simulation.layer,metrics,analysis.cpu,batch_job_binder_cell,default \
        --concurrency="$BUILD_CONCURRENCY" \
        --loglevel=INFO \
        --hostname="build@%h" \
        > "$LOG_DIR/celery-build.log" 2>&1 &
    echo "$!" > "$PID_DIR/celery-build.pid"

    # GPU pool: GPU-bound work ONLY. concurrency == total GPU slots ($CONCURRENCY).
    nohup setsid "$PYTHON_BIN" -m celery -A orchestrator.celery_app:celery_app worker \
        --queues=simulation.gpu,priority \
        --concurrency="$CONCURRENCY" \
        --loglevel=INFO \
        --hostname="gpu@%h" \
        > "$LOG_DIR/celery.log" 2>&1 &
    echo "$!" > "$PID_DIR/celery.pid"

    # Control pool: lightweight orchestration/beat tasks ONLY. Small, never starved.
    nohup setsid "$PYTHON_BIN" -m celery -A orchestrator.celery_app:celery_app worker \
        --queues=control \
        --concurrency="$CONTROL_CONCURRENCY" \
        --loglevel=INFO \
        --hostname="control@%h" \
        > "$LOG_DIR/celery-control.log" 2>&1 &
    echo "$!" > "$PID_DIR/celery-control.pid"

    # setsid re-forks celery — resolve the real PIDs by unique hostname marker.
    sleep 2
    local build_pid gpu_pid control_pid
    build_pid=$(pattern_pid "celery.*build@")
    gpu_pid=$(pattern_pid "celery.*gpu@")
    control_pid=$(pattern_pid "celery.*control@")
    [ -n "$build_pid" ] && echo "$build_pid" > "$PID_DIR/celery-build.pid"
    [ -n "$gpu_pid" ] && echo "$gpu_pid" > "$PID_DIR/celery.pid"
    [ -n "$control_pid" ] && echo "$control_pid" > "$PID_DIR/celery-control.pid"

    print_action_ok "Celery cpu pool (PID: ${build_pid:-?}, -c $BUILD_CONCURRENCY) + gpu pool (PID: ${gpu_pid:-?}, -c $CONCURRENCY) + control pool (PID: ${control_pid:-?}, -c $CONTROL_CONCURRENCY)"
}

start_beat() {
    # Celery beat drives the periodic safety nets that the event-driven
    # completion hook does NOT cover: recover-orphan-ready-allocations (60s,
    # reclaims GPU slots leaked by crashed workers) and schedule-ready-experiments
    # (5s sweep). Without beat these never fire (v01.05.56 P1). Uses the same
    # PYTHON_BIN as the workers (start_beat.sh's separate venv is inconsistent).
    print_action_start "Starting Celery beat (periodic recovery/maintenance)"

    export CELERY_BROKER_URL="redis://${REDIS_HOST}:${REDIS_PORT}/0"
    export CELERY_RESULT_BACKEND="redis://${REDIS_HOST}:${REDIS_PORT}/1"

    cd "$PROJECT_ROOT"
    nohup setsid "$PYTHON_BIN" -m celery -A orchestrator.celery_app:celery_app beat \
        --loglevel=INFO \
        --scheduler=celery.beat:PersistentScheduler \
        --schedule="$PROJECT_ROOT/celerybeat-schedule" \
        > "$LOG_DIR/celery-beat.log" 2>&1 &
    echo "$!" > "$PID_DIR/celery-beat.pid"
    sleep 1
    local beat_pid
    beat_pid=$(pattern_pid "celery_app beat")
    [ -n "$beat_pid" ] && echo "$beat_pid" > "$PID_DIR/celery-beat.pid"
    print_action_ok "Celery beat started (PID: ${beat_pid:-?})"
}

# =============================================================================
# Stop Services
# =============================================================================

stop_services() {
    print_header "Stopping All Services"

    # Stop celery first, then frontend, then api last.
    # api uses process-group kill (for uvicorn spawn workers) which can
    # accidentally kill celery if they share a PGID. By stopping celery
    # first we avoid the "was not running" false warning.
    local services=("celery" "frontend" "api")

    for service in "${services[@]}"; do
        local pid_file="$PID_DIR/${service}.pid"
        if [ -f "$pid_file" ]; then
            local pid=$(cat "$pid_file")
            if ps -p "$pid" > /dev/null 2>&1; then
                print_status "Stopping $service (PID: $pid)..."
                if [ "$service" = "api" ]; then
                    # API: process-group kill to catch uvicorn spawn workers
                    local pgid
                    pgid=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')
                    if [ -n "$pgid" ]; then
                        kill -TERM -"$pgid" 2>/dev/null || kill "$pid" 2>/dev/null || true
                    else
                        kill "$pid" 2>/dev/null || true
                    fi
                else
                    # Other services: individual PID kill only
                    kill "$pid" 2>/dev/null || true
                fi
                sleep 2
                # Force kill if still running
                if ps -p "$pid" > /dev/null 2>&1; then
                    kill -9 "$pid" 2>/dev/null || true
                fi
                print_success "$service stopped"
            else
                print_status "$service: not running"
            fi
            rm -f "$pid_file"
        else
            # No PID file: for API fall back to the live port listener.
            local fallback_pid=""
            [ "$service" = "api" ] && fallback_pid=$(port_listener_pid "$API_PORT")
            if [ -n "$fallback_pid" ]; then
                print_status "Stopping $service (port PID: $fallback_pid)..."
                local pgid
                pgid=$(ps -o pgid= -p "$fallback_pid" 2>/dev/null | tr -d ' ')
                { [ -n "$pgid" ] && kill -TERM -"$pgid" 2>/dev/null; } \
                    || kill "$fallback_pid" 2>/dev/null || true
                print_success "$service stopped"
            else
                print_status "$service: not running"
            fi
        fi
    done

    # Also kill any orphaned processes by cmdline pattern
    pkill -f "uvicorn api.main:app" 2>/dev/null || true
    pkill -f "celery.*orchestrator.celery_app" 2>/dev/null || true
    # Kill orphaned Vite/Node frontend processes
    pkill -f "node.*vite" 2>/dev/null || true
    pkill -f "node.*frontend/node_modules" 2>/dev/null || true

    # Give processes time to terminate gracefully
    sleep 2

    # Force kill any remaining stubborn processes
    pkill -9 -f "uvicorn api.main:app" 2>/dev/null || true
    # Both celery pools (build@/gpu@) match this pattern, so the pkill above and
    # below terminate both; clean the build pool's PID file (the services loop
    # only iterates celery.pid = gpu pool).
    pkill -9 -f "celery.*orchestrator.celery_app" 2>/dev/null || true
    rm -f "$PID_DIR/celery-build.pid" "$PID_DIR/celery-control.pid" "$PID_DIR/celery-beat.pid" 2>/dev/null || true
    # MPS clients (LAMMPS) are gone now that celery is killed — stop the daemon.
    stop_mps
    pkill -9 -f "node.*vite" 2>/dev/null || true

    # Port-based final sweep: uvicorn multiprocessing workers are spawned
    # via `python -c "from multiprocessing.spawn ..."`, so their cmdline
    # does NOT contain "uvicorn api.main:app". `pkill -f` misses them and
    # they keep binding the port after stop. Enumerate listeners on the
    # API port directly and kill them.
    local port_tool=""
    if command -v lsof >/dev/null 2>&1; then
        port_tool="lsof"
    elif command -v fuser >/dev/null 2>&1; then
        port_tool="fuser"
    fi

    if [ -n "$port_tool" ]; then
        local orphans=""
        if [ "$port_tool" = "lsof" ]; then
            orphans=$(lsof -ti:"$API_PORT" 2>/dev/null || true)
        else
            orphans=$(fuser "$API_PORT"/tcp 2>/dev/null | tr -s ' ' '\n' | grep -E '^[0-9]+$' || true)
        fi

        if [ -n "$orphans" ]; then
            print_warning "Port $API_PORT still held — sweeping orphan PIDs: $(echo "$orphans" | tr '\n' ' ')"
            echo "$orphans" | xargs -r kill -TERM 2>/dev/null || true
            sleep 1
            # Recheck
            if [ "$port_tool" = "lsof" ]; then
                orphans=$(lsof -ti:"$API_PORT" 2>/dev/null || true)
            else
                orphans=$(fuser "$API_PORT"/tcp 2>/dev/null | tr -s ' ' '\n' | grep -E '^[0-9]+$' || true)
            fi
            if [ -n "$orphans" ]; then
                print_warning "Force killing orphan PIDs: $(echo "$orphans" | tr '\n' ' ')"
                echo "$orphans" | xargs -r kill -9 2>/dev/null || true
            fi
        fi
    else
        print_warning "lsof/fuser not found — cannot perform port-based sweep on $API_PORT"
    fi

    print_success "All services stopped"
}

# =============================================================================
# Show Service Status
# =============================================================================

show_status() {
    print_header "Service Status"

    # API — prefer the live port listener (setsid re-fork makes the saved PID
    # unreliable); fall back to the PID file only when the port is silent.
    local api_live_pid
    api_live_pid=$(port_listener_pid "$API_PORT")
    if [ -n "$api_live_pid" ]; then
        echo "$api_live_pid" > "$PID_DIR/api.pid"
        print_success "API Server: Running (PID: $api_live_pid, Port: $API_PORT)"
    elif [ -f "$PID_DIR/api.pid" ] && ps -p "$(cat "$PID_DIR/api.pid")" > /dev/null 2>&1; then
        print_success "API Server: Running (PID: $(cat "$PID_DIR/api.pid"))"
    else
        rm -f "$PID_DIR/api.pid"
        print_warning "API Server: Not running"
    fi

    # Frontend
    if [ -f "$PID_DIR/frontend.pid" ]; then
        local pid=$(cat "$PID_DIR/frontend.pid")
        local frontend_port="5173"
        if [ -f "$PID_DIR/frontend.port" ]; then
            frontend_port=$(cat "$PID_DIR/frontend.port")
        fi
        if ps -p "$pid" > /dev/null 2>&1; then
            print_success "Frontend: Running (PID: $pid, Port: $frontend_port)"
        else
            rm -f "$PID_DIR/frontend.pid"
            print_warning "Frontend: Not running (stale PID file)"
        fi
    else
        print_warning "Frontend: Not started"
    fi

    # Celery — two pools (build@, gpu@). Saved PIDs unreliable after setsid
    # re-fork; confirm each by its unique hostname marker in the cmdline.
    local build_live_pid gpu_live_pid control_live_pid
    build_live_pid=$(pattern_pid "celery.*build@")
    gpu_live_pid=$(pattern_pid "celery.*gpu@")
    control_live_pid=$(pattern_pid "celery.*control@")
    if [ -n "$build_live_pid" ]; then
        echo "$build_live_pid" > "$PID_DIR/celery-build.pid"
        print_success "Celery cpu pool: Running (PID: $build_live_pid)"
    else
        rm -f "$PID_DIR/celery-build.pid"
        print_warning "Celery cpu pool: Not running"
    fi
    if [ -n "$gpu_live_pid" ]; then
        echo "$gpu_live_pid" > "$PID_DIR/celery.pid"
        print_success "Celery gpu pool: Running (PID: $gpu_live_pid)"
    else
        rm -f "$PID_DIR/celery.pid"
        print_warning "Celery gpu pool: Not running"
    fi
    if [ -n "$control_live_pid" ]; then
        echo "$control_live_pid" > "$PID_DIR/celery-control.pid"
        print_success "Celery control pool: Running (PID: $control_live_pid)"
    else
        rm -f "$PID_DIR/celery-control.pid"
        print_warning "Celery control pool: Not running"
    fi
    local beat_live_pid
    beat_live_pid=$(pattern_pid "celery_app beat")
    if [ -n "$beat_live_pid" ]; then
        echo "$beat_live_pid" > "$PID_DIR/celery-beat.pid"
        print_success "Celery beat: Running (PID: $beat_live_pid)"
    else
        rm -f "$PID_DIR/celery-beat.pid"
        print_warning "Celery beat: Not running"
    fi

    # Redis
    if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping &>/dev/null; then
        print_success "Redis: Running (${REDIS_HOST}:${REDIS_PORT})"
    else
        print_error "Redis: Not running"
    fi

    # Get frontend port
    local display_frontend_port="5173"
    if [ -f "$PID_DIR/frontend.port" ]; then
        display_frontend_port=$(cat "$PID_DIR/frontend.port")
    fi

    echo "URLs:"
    echo "  API:      http://localhost:${API_PORT}"
    echo "  API Docs: http://localhost:${API_PORT}/docs"
    echo "  Frontend: http://localhost:${display_frontend_port}"
    echo "Logs:"
    echo "  API:      $LOG_DIR/api.log"
    echo "  Frontend: $LOG_DIR/frontend.log"
    echo "  Celery:   $LOG_DIR/celery.log"
}

# =============================================================================
# Main Entry Point
# =============================================================================

main() {
    DEV_MODE=false

    case "${1:-}" in
        "--check")
            print_header "Dependency Check Only"
            local check_failed=0
            setup_conda_env
            install_python_deps || check_failed=1
            ensure_db_schema_compat || check_failed=1
            check_simulation_tools || check_failed=1
            check_redis || check_failed=1
            install_node_deps || check_failed=1
            print_version_summary
            print_dependency_summary
            if [ $check_failed -eq 0 ]; then
                print_success "All dependencies are ready!"
                exit 0
            else
                print_error "Dependency check completed with issues"
                exit 1
            fi
            ;;
        "--verify")
            print_header "Module Verification Only"
            setup_conda_env
            install_python_deps
            ensure_db_schema_compat
            verify_modules
            exit 0
            ;;
        "--stop")
            stop_services
            exit 0
            ;;
        "--status")
            show_status
            exit 0
            ;;
        "--dev")
            DEV_MODE=true
            print_status "Development mode enabled (auto-reload)"
            ;;
        "--help"|"-h")
            echo "Asphalt MD Agent - All Services Start Script (${DISPLAY_VERSION})"
            echo "Usage: $0 [OPTION]"
            echo "Options:"
            echo "  (none)     Start all services"
            echo "  --dev      Start with development mode (auto-reload for API)"
            echo "  --check    Check dependencies only"
            echo "  --verify   Verify module imports only"
            echo "  --stop     Stop all services"
            echo "  --status   Show status of all services"
            echo "  --help     Show this help"
            echo "Environment:"
            echo "  AUTO_INSTALL_SYSTEM_DEPS=true|false (default: true)"
            echo "Modules verified on startup:"
            echo "  Core:           contracts, common, config"
            echo "  Database:       SQLAlchemy, repositories"
            echo "  API:            FastAPI REST"
            echo "  Orchestrator:   Celery tasks, Pipeline, ContinuousLoop, GPUService, CeleryJobManager"
            echo "  Builder:        StructureBuilder, LayerBuilder"
            echo "  Forcefield:     INTERFACE FF, UFF fallback"
            echo "  Metrics:        MetricsCalculator, AdhesionEnergy"
            echo "  RDKit:          Chem, Descriptors"
            echo "  ML:             v1/v2, multi-target, OOD, uncertainty, feature store"
            echo "  MLOps:          Model Registry, Drift Detection, Auto-Retrainer"
            echo "  Recommendation: BO, Inverse Design, Pareto Frontier"
            echo "  Validation:     ReaxFF Validator + Selector"
            echo "  Monitoring:     GPU collector (nvidia-smi)"
            echo "  LLM:            Provider client (settings health probe)"
            exit 0
            ;;
    esac

    print_header "Asphalt MD Agent - Starting All Services"
    echo "Project Root: $PROJECT_ROOT"

    # Create required directories
    create_directories

    # Setup and check dependencies
    setup_conda_env
    install_python_deps
    ensure_db_schema_compat

    # Now that PYTHON_BIN/PYTHONPATH are ready, read slots/GPU from budget policy
    # and derive Celery concurrency (GPUs x slots). Must run after setup_conda_env.
    compute_concurrency

    # Verify module imports
    verify_modules || print_warning "Some modules failed verification, continuing anyway..."

    # Check simulation tools (Packmol, LAMMPS)
    check_simulation_tools || print_warning "Simulation tools check failed - simulations may not work correctly"

    if ! check_redis; then
        print_error "Redis is required. Please start Redis first."
        exit 1
    fi

    install_node_deps

    # Start all services
    print_header "Starting Services"

    start_api
    sleep 2

    start_mps   # MPS 데몬(slots>1일 때만) — celery 워커보다 먼저
    warm_lammps_caps  # Defense A: idle caps 워밍 — 워커 포크 전 정상 캐시 보장
    start_celery
    start_beat  # 주기 복구/유지보수 스케줄러 (orphan 슬롯 회수 등)
    sleep 2

    start_frontend
    sleep 2

    # Show final status
    show_status
    print_version_summary
    print_dependency_summary

    print_header "All Services Started Successfully! (${DISPLAY_VERSION})"
    echo "To stop:  ./start_all.sh --stop"
    echo "Logs:     tail -f $LOG_DIR/api.log"
    echo "          tail -f $LOG_DIR/celery.log"
    echo "          tail -f $LOG_DIR/frontend.log"
    echo "Modules (${DISPLAY_VERSION}):"
    echo "  Core:           contracts, common, config"
    echo "  Database:       SQLAlchemy + repositories"
    echo "  API:            FastAPI REST"
    echo "  Orchestrator:   Celery + GPUService + CeleryJobManager"
    echo "  Builder:        StructureBuilder + LayerBuilder"
    echo "  Forcefield:     INTERFACE FF + UFF fallback"
    echo "  Metrics:        MetricsCalculator + AdhesionEnergy"
    echo "  ML / MLOps:     Multi-target, OOD, UE, Registry, Drift, Retrainer"
    echo "  Recommendation: BO, Inverse Design, Pareto"
    echo "  Validation:     ReaxFF Validator + Selector"
    echo "  Monitoring:     GPU collector (nvidia-smi)"
    echo "  LLM:            Function-calling interface"

    # 프론트 접속 URL을 맨 마지막 줄에 다시 안내 (가장 자주 찾는 정보).
    local final_frontend_port="5173"
    [ -f "$PID_DIR/frontend.port" ] && final_frontend_port=$(cat "$PID_DIR/frontend.port")
    echo ""
    print_success "Frontend: http://localhost:${final_frontend_port}"
}

# Run main
main "$@"
