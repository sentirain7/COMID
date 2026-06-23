"""Render the MethodsX graphical abstract from docs/figures/graphical_abstract_spec.md.

Self-contained matplotlib schematic (no external assets). Embeds real
repository run data (Squalane E_intra(T), AAA1 density(T)). Output is a wide
landscape banner (>= 531 x 1328 px h x w) suitable for MethodsX.

Usage:
    python scripts/make_graphical_abstract.py
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

# ---- real data (from repository run logs) -------------------------------
SQUALANE_T = [213, 233, 253, 273, 293, 313, 333, 353, 373, 393, 413, 433]
SQUALANE_EINTRA = [94.2, 100.4, 106.4, 112.2, 119.5, 124.1, 129.4, 137.4, 142.3, 147.3, 150.6, 158.4]
AAA1_T = [273, 293, 313, 333, 353, 373, 393, 413, 433]
AAA1_DENSITY = [0.947, 0.959, 0.945, 0.939, 0.919, 0.908, 0.896, 0.876, 0.863]

BLUE, TEAL, AMBER, SLATE, BG = "#2563eb", "#0d9488", "#d97706", "#1e293b", "#f1f5f9"


def _card(ax, x, y, w, h, color, lw=2.0, fc="white"):
    box = FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.01,rounding_size=0.02",
        ec=color, fc=fc, lw=lw, transform=ax.transAxes, zorder=2,
    )
    ax.add_patch(box)


def _arrow(ax, x0, y0, x1, y1, color="#94a3b8"):
    ax.add_patch(FancyArrowPatch(
        (x0, y0), (x1, y1), transform=ax.transAxes,
        arrowstyle="-|>", mutation_scale=28, lw=4, color=color, zorder=1,
    ))


def main(out="docs/figures/graphical_abstract.png"):
    fig = plt.figure(figsize=(8.0, 3.2), dpi=300)  # -> 2400 x 960 px
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")

    # title strip
    ax.add_patch(mpatches.Rectangle((0, 0.90), 1, 0.10, transform=ax.transAxes,
                                    fc=SLATE, ec="none", zorder=1))
    ax.text(0.5, 0.95,
            "Automated GAFF2/AM1-BCC parameterization + per-molecule E$_{intra}$  →  cohesive energy density (CED)",
            transform=ax.transAxes, ha="center", va="center",
            color="white", fontsize=11, fontweight="bold")

    # ---- Panel 1: FF parameterization ----
    _card(ax, 0.015, 0.30, 0.27, 0.55, BLUE)
    ax.text(0.15, 0.81, "1 · Force-field parameterization",
            transform=ax.transAxes, ha="center", fontsize=9.5, fontweight="bold", color=BLUE)
    ax.text(0.055, 0.67, "molecule\n(.mol)", transform=ax.transAxes, ha="center", fontsize=8)
    _arrow(ax, 0.105, 0.66, 0.155, 0.66)
    _card(ax, 0.16, 0.55, 0.115, 0.22, BLUE, lw=1.2, fc="#eff6ff")
    ax.text(0.2175, 0.745, "GAFF2 / AM1-BCC\nartifact", transform=ax.transAxes,
            ha="center", va="top", fontsize=7.2, color=BLUE, fontweight="bold")
    ax.text(0.2175, 0.665, "ff_type\nε, σ,  q\nbond/angle/dih.",
            transform=ax.transAxes, ha="center", va="top", fontsize=6.6)
    ax.text(0.15, 0.40, "escalation (fail-closed):", transform=ax.transAxes,
            ha="center", fontsize=7, color="#475569")
    ax.text(0.15, 0.345, "baseline → robust-SCF → fragment*",
            transform=ax.transAxes, ha="center", fontsize=7, color=SLATE, fontweight="bold")

    _arrow(ax, 0.30, 0.575, 0.355, 0.575)

    # ---- Panel 2: E_intra(T) ----
    _card(ax, 0.365, 0.30, 0.27, 0.55, TEAL)
    ax.text(0.5, 0.81, "2 · Per-molecule E$_{intra}$(T)",
            transform=ax.transAxes, ha="center", fontsize=9.5, fontweight="bold", color=TEAL)
    # dashed vacuum box with molecule
    ax.add_patch(mpatches.Rectangle((0.385, 0.56), 0.085, 0.17, transform=ax.transAxes,
                                    fc="none", ec=TEAL, ls="--", lw=1.3))
    ax.text(0.4275, 0.645, "1 molecule\n(vacuum)", transform=ax.transAxes,
            ha="center", va="center", fontsize=6.8, color=TEAL)
    # inset plot
    iax = fig.add_axes([0.50, 0.355, 0.125, 0.20])
    iax.plot(SQUALANE_T, SQUALANE_EINTRA, "-o", color=TEAL, ms=2.2, lw=1.3)
    iax.set_title("E$_{intra}$ vs T", fontsize=6.5, color=TEAL, pad=2)
    iax.set_xlabel("T (K)", fontsize=6, labelpad=1)
    iax.tick_params(labelsize=5.5, length=2)
    iax.set_yticks([100, 130, 160])
    ax.text(0.5, 0.335, "method-aware key (mol, FF, ver, T, method)",
            transform=ax.transAxes, ha="center", fontsize=6.6, color="#475569")

    _arrow(ax, 0.65, 0.575, 0.705, 0.575)

    # ---- Panel 3: bulk CED ----
    _card(ax, 0.715, 0.30, 0.27, 0.55, AMBER)
    ax.text(0.85, 0.81, "3 · Multi-component bulk → CED",
            transform=ax.transAxes, ha="center", fontsize=9.5, fontweight="bold", color=AMBER)
    # periodic box with glyphs
    ax.add_patch(mpatches.Rectangle((0.735, 0.56), 0.085, 0.17, transform=ax.transAxes,
                                    fc="#fffbeb", ec=AMBER, lw=1.3))
    for gx in (0.75, 0.772, 0.794):
        for gy in (0.59, 0.64, 0.69):
            ax.add_patch(mpatches.Circle((gx, gy), 0.006, transform=ax.transAxes,
                                         fc=AMBER, ec="none"))
    ax.text(0.7775, 0.545, "binder (periodic)", transform=ax.transAxes,
            ha="center", va="top", fontsize=6.6, color=AMBER)
    iax2 = fig.add_axes([0.85, 0.355, 0.125, 0.20])
    iax2.plot(AAA1_T, AAA1_DENSITY, "-o", color=AMBER, ms=2.2, lw=1.3)
    iax2.set_title("density vs T", fontsize=6.5, color=AMBER, pad=2)
    iax2.set_xlabel("T (K)", fontsize=6, labelpad=1)
    iax2.tick_params(labelsize=5.5, length=2)
    iax2.set_yticks([0.88, 0.92, 0.96])

    # ---- formula band ----
    ax.add_patch(mpatches.Rectangle((0, 0), 1, 0.255, transform=ax.transAxes,
                                    fc=BG, ec="none", zorder=0))
    ax.text(0.5, 0.165,
            r"CED(T) = $-\,[\,$PE$_{bulk}$(T) $-\ \sum_i n_i\cdot$E$_{intra,i}$(T)$\,]\ /\ V$(T)",
            transform=ax.transAxes, ha="center", va="center",
            fontsize=13, color=SLATE, fontweight="bold")
    ax.text(0.5, 0.055,
            "same force field · same temperature · same method  ⇒  bulk and single-molecule energies always matched (fail-closed)",
            transform=ax.transAxes, ha="center", va="center",
            fontsize=8, color="#475569")

    fig.savefig(out, dpi=300, facecolor="white", bbox_inches=None)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
