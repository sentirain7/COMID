#!/usr/bin/env bash
# =============================================================================
# Pin Xorg to the DISPLAY (consumer) GPU so the datacenter GPUs (H200) are never
# grabbed by Xorg and stay FREE for MIG/compute — permanently, across reboots.
# RUN WITH sudo. A reboot is required for it to take effect.
#
# Why: MIG instance creation fails with "In use by another client" because Xorg
# attaches a 4MiB graphics context to every H200. This pins Xorg to the small
# display card (RTX 3050) only, via AutoAddGPU=false + an explicit Device BusID.
#
# Usage:
#   sudo ./scripts/install_xorg_display_pin.sh            # install + show next steps
#   sudo ./scripts/install_xorg_display_pin.sh --uninstall  # remove (revert)
# =============================================================================
set -uo pipefail

CONF="/etc/X11/xorg.conf.d/10-nvidia-display-pin.conf"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}[ERROR]${NC} Run as root: sudo $0 $*"
    exit 1
fi

if [ "${1:-}" = "--uninstall" ]; then
    if [ -f "$CONF" ]; then
        rm -f "$CONF"
        echo -e "${GREEN}[OK]${NC} Removed $CONF. Reboot to revert: sudo reboot"
    else
        echo -e "${YELLOW}[NOTE]${NC} $CONF not present — nothing to remove."
    fi
    exit 0
fi

command -v nvidia-smi >/dev/null 2>&1 || { echo -e "${RED}[ERROR]${NC} nvidia-smi not found"; exit 1; }

# 1) Find the display GPU = the consumer card (MIG mode reported as [N/A]).
disp_line="$(nvidia-smi --query-gpu=name,mig.mode.current,pci.bus_id --format=csv,noheader \
    | awk -F', ' '$2 ~ /N\/A/ {print; exit}')"
if [ -z "$disp_line" ]; then
    echo -e "${RED}[ERROR]${NC} No non-MIG (consumer/display) GPU found. Aborting to avoid"
    echo "          pinning Xorg to a datacenter GPU. Set BusID manually if needed."
    exit 1
fi
disp_name="$(echo "$disp_line" | awk -F', ' '{print $1}')"
pcibus="$(echo "$disp_line" | awk -F', ' '{print $3}' | xargs)"

# 2) Convert pci.bus_id (e.g. 00000000:A2:00.0) -> Xorg "PCI:bus:dev:func" (decimal).
bus_hex="$(echo "$pcibus" | cut -d: -f2)"
devfunc="$(echo "$pcibus" | cut -d: -f3)"
dev_hex="$(echo "$devfunc" | cut -d. -f1)"
func="$(echo "$devfunc" | cut -d. -f2)"
busid="PCI:$((16#$bus_hex)):$((16#$dev_hex)):${func}"

echo -e "${BLUE}=== Display GPU pin ===${NC}"
echo "  display GPU : $disp_name"
echo "  pci.bus_id  : $pcibus  ->  Xorg BusID $busid"
echo "  config file : $CONF"
echo

# 3) Back up any existing file, then write the config.
if [ -f "$CONF" ]; then
    cp -a "$CONF" "${CONF}.bak.$(date +%s 2>/dev/null || echo prev)" 2>/dev/null || true
fi
cat > "$CONF" <<EOF
# Pin Xorg to the display GPU ($disp_name) so datacenter GPUs (H200) stay free
# for MIG/compute. Written by scripts/install_xorg_display_pin.sh.
Section "ServerFlags"
    Option "AutoAddGPU" "false"
EndSection

Section "Device"
    Identifier "nvidia-display"
    Driver     "nvidia"
    BusID      "$busid"
EndSection

Section "Screen"
    Identifier "screen-display"
    Device     "nvidia-display"
EndSection

Section "ServerLayout"
    Identifier "layout"
    Screen 0   "screen-display"
EndSection
EOF

echo -e "${GREEN}[OK]${NC} Wrote $CONF:"
sed 's/^/    /' "$CONF"
echo
echo -e "${BLUE}=== Next steps ===${NC}"
echo "  1) Reboot:                 sudo reboot"
echo "  2) After reboot, H200s are free of Xorg. Create MIG instances:"
echo "        sudo ./scripts/setup_mig.sh"
echo "  3) Start services (auto -> mig):"
echo "        ./start_all.sh --stop && ./start_all.sh"
echo
echo -e "${YELLOW}[RECOVERY]${NC} If the display/desktop fails to come up after reboot:"
echo "  SSH into the machine and run:"
echo "        sudo $0 --uninstall && sudo reboot"
echo -e "${YELLOW}[NOTE]${NC} MIG instances do NOT survive reboot — re-run setup_mig.sh after each"
echo "  boot (idempotent), or enable a systemd oneshot (see docs/operations/mig-setup-xorg.md)."
