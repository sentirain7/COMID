#!/usr/bin/env bash
# =============================================================================
# MIG teardown — RUN WITH sudo. Reverts every MIG-enabled GPU to whole-GPU.
#
# Destroys compute instances + GPU instances, then disables MIG mode. After
# this the app (gpu_sharing_mode=auto) falls back to MPS on next start.
#
# Usage:  sudo ./scripts/teardown_mig.sh
# After it finishes:  ./start_all.sh --stop && ./start_all.sh
# =============================================================================
set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}[ERROR]${NC} Must run as root: sudo $0"
    exit 1
fi
command -v nvidia-smi >/dev/null 2>&1 || { echo -e "${RED}[ERROR]${NC} nvidia-smi not found."; exit 1; }

echo -e "${BLUE}=== MIG teardown ===${NC}"

changed=0
while IFS=',' read -r idx uuid name migmode; do
    idx="$(echo "$idx" | xargs)"; name="$(echo "$name" | xargs)"
    migmode="$(echo "$migmode" | xargs)"
    [ "$migmode" = "Enabled" ] || continue

    echo -e "${BLUE}[..]${NC}  GPU $idx ($name): destroying instances + disabling MIG"
    nvidia-smi mig -i "$idx" -dci >/dev/null 2>&1 || true   # destroy compute instances
    nvidia-smi mig -i "$idx" -dgi >/dev/null 2>&1 || true   # destroy GPU instances
    if nvidia-smi -i "$idx" -mig 0 >/dev/null 2>&1; then
        echo -e "${GREEN}[OK]${NC}  GPU $idx: MIG disabled"
        changed=1
    else
        echo -e "${YELLOW}[WARN]${NC} GPU $idx: '-mig 0' failed — may need 'nvidia-smi --gpu-reset -i $idx' or a reboot."
    fi
done < <(nvidia-smi --query-gpu=index,uuid,name,mig.mode.current --format=csv,noheader)

echo
nvidia-smi -L
echo
if [ "$changed" -eq 1 ]; then
    echo -e "${GREEN}[NEXT]${NC} Restart services (auto -> MPS): ./start_all.sh --stop && ./start_all.sh"
else
    echo -e "${YELLOW}[NOTE]${NC} No MIG-enabled GPUs found — nothing to do."
fi
