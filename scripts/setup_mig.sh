#!/usr/bin/env bash
# =============================================================================
# MIG setup for datacenter GPUs (H200/H100/A100) — RUN WITH sudo.
#
# Enables MIG mode and creates MIG instances of the chosen profile on every
# MIG-capable GPU. Consumer GPUs (e.g. RTX 3050) are skipped automatically.
# Idempotent: GPUs already MIG-enabled with instances are left untouched.
#
# The app itself runs WITHOUT sudo and adapts automatically: with
# gpu_sharing_mode=auto (default), the orchestrator detects the MIG instances on
# its next start and routes jobs to them (MPS -> MIG) — no code/policy change.
#
# Usage:
#   sudo ./scripts/setup_mig.sh [profile] [max_per_gpu]
#     profile      MIG profile name (default: 1g.18gb)
#     max_per_gpu  cap on instances per GPU (default: 7)
#
# After it finishes:  ./start_all.sh --stop && ./start_all.sh
# =============================================================================
set -uo pipefail

PROFILE="${1:-1g.18gb}"
MAX_PER_GPU="${2:-7}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}[ERROR]${NC} Must run as root. MIG mode/instance ops require root:"
    echo "          sudo $0 $*"
    exit 1
fi
if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo -e "${RED}[ERROR]${NC} nvidia-smi not found."
    exit 1
fi

echo -e "${BLUE}=== MIG setup (profile=$PROFILE, max/gpu=$MAX_PER_GPU) ===${NC}"

changed=0
# index,uuid,name,mig.mode.current — one row per physical GPU.
while IFS=',' read -r idx uuid name migmode; do
    idx="$(echo "$idx" | xargs)"; name="$(echo "$name" | xargs)"
    migmode="$(echo "$migmode" | xargs)"

    if [ "$migmode" = "[N/A]" ]; then
        echo -e "${YELLOW}[SKIP]${NC} GPU $idx ($name): MIG not supported (consumer GPU)"
        continue
    fi

    # Active CUDA contexts block MIG-mode enable.
    apps="$(nvidia-smi -i "$idx" --query-compute-apps=pid --format=csv,noheader 2>/dev/null | sed '/^$/d')"
    if [ -n "$apps" ] && [ "$migmode" != "Enabled" ]; then
        echo -e "${YELLOW}[WARN]${NC} GPU $idx ($name): active CUDA contexts (PIDs: $(echo "$apps" | tr '\n' ' ')) block MIG enable."
        echo "        Stop them (e.g. gnome-remote-desktop) and re-run, or exclude this GPU."
        continue
    fi

    # 1) Enable MIG mode if needed.
    if [ "$migmode" != "Enabled" ]; then
        echo -e "${BLUE}[..]${NC}  GPU $idx: enabling MIG mode"
        if ! nvidia-smi -i "$idx" -mig 1; then
            echo -e "${YELLOW}[WARN]${NC} GPU $idx: '-mig 1' failed — may need 'nvidia-smi --gpu-reset -i $idx' or a reboot. Skipping."
            continue
        fi
        changed=1
    fi

    # 2) Count existing MIG instances under this GPU (idempotency).
    existing="$(nvidia-smi -L | awk -v gid="^GPU ${idx}:" '
        /^GPU / { inblk = ($0 ~ gid) }
        inblk && /MIG / { c++ }
        END { print c+0 }')"
    if [ "${existing:-0}" -gt 0 ]; then
        echo -e "${GREEN}[OK]${NC}  GPU $idx: $existing MIG instance(s) already present — skip create"
        continue
    fi

    # 3) Resolve the profile NAME -> numeric profile ID. `-cgi <name>` is
    #    rejected by some drivers; the ID from `-lgip` always works. The -lgip
    #    row looks like:  |  0  MIG 1g.18gb  19  7/7  ...  -> id is the field
    #    right after the profile name.
    pid="$(nvidia-smi mig -i "$idx" -lgip 2>/dev/null | awk -v p="$PROFILE" '
        { for (i = 1; i <= NF; i++) if ($i == "MIG" && $(i + 1) == p) { print $(i + 2); exit } }')"
    if [ -z "$pid" ]; then
        echo -e "${YELLOW}[WARN]${NC} GPU $idx: profile '$PROFILE' not found. Available profiles:"
        nvidia-smi mig -i "$idx" -lgip 2>/dev/null | awk '/MIG /{print "          " $0}'
        continue
    fi

    # 4) Create instances (GPU instance + compute instance) until capacity ends.
    #    Surface the real nvidia-smi error if a create fails (no more silent 0).
    echo -e "${BLUE}[..]${NC}  GPU $idx: creating up to $MAX_PER_GPU x $PROFILE (profile id $pid)"
    created=0
    last_err=""
    while [ "$created" -lt "$MAX_PER_GPU" ]; do
        if out="$(nvidia-smi mig -i "$idx" -cgi "$pid" -C 2>&1)"; then
            created=$((created + 1))
        else
            last_err="$out"
            break
        fi
    done
    if [ "$created" -gt 0 ]; then
        echo -e "${GREEN}[OK]${NC}  GPU $idx: created $created x $PROFILE"
        changed=1
    else
        echo -e "${YELLOW}[WARN]${NC} GPU $idx: created 0 instances. nvidia-smi said:"
        echo "          ${last_err:-<no output>}"
    fi
done < <(nvidia-smi --query-gpu=index,uuid,name,mig.mode.current --format=csv,noheader)

echo
echo -e "${BLUE}=== Result (nvidia-smi -L) ===${NC}"
nvidia-smi -L
echo
if [ "$changed" -eq 1 ]; then
    echo -e "${GREEN}[NEXT]${NC} Restart services to route jobs to MIG (auto-detected):"
    echo "        ./start_all.sh --stop && ./start_all.sh"
    echo "        (gpu_sharing_mode=auto switches MPS -> MIG automatically.)"
else
    echo -e "${YELLOW}[NOTE]${NC} No changes made (already configured, or all GPUs skipped/blocked)."
fi
