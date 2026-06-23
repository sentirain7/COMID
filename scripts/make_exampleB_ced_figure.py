"""Single-figure illustration of the CED gas-phase-reference-subtraction pipeline.

One frame, shared temperature axis (213-433 K, 12-point grid):
  - LEFT y-axis  : 32 single-molecule vacuum E_intra,i(T) reference curves
                   (the orchestrated dependency, looked up at the bulk T)
  - RIGHT y-axis : assembled CED labels (Eq. 1 output) coloured by additive
  - one bulk T highlighted to show lookup -> subtraction -> CED

Data (two sheets / two CSVs, both produced from git-tracked sidecars):
  docs/figures/exampleB_eintra_references.csv  (384 rows = 32 mols x 12 T)
  docs/figures/exampleB_ced_labels.csv         (107 committed CED labels)

Usage: python scripts/make_exampleB_ced_figure.py
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D

EI = "docs/figures/exampleB_eintra_references.csv"
CED = "docs/figures/exampleB_ced_labels.csv"
OUT = "docs/figures/fig_exampleB_ced_pipeline.png"
GRID = list(range(213, 434, 20))   # 12-point shared temperature grid
BULK_T = 293.0                     # highlighted bulk temperature (26 CED labels)
# vivid, saturated marker colours: blue kept, ochre -> vivid orange, muted -> vivid green
ADD_COLOR = {"none": "#3a78bc", "Lignin": "#00a14b", "SiO2": "#ff7f0e"}

plt.rcParams.update({"font.size": 12, "figure.dpi": 1200, "savefig.dpi": 1200,
                     "font.family": "Arial", "font.sans-serif": ["Arial"]})


def main():
    ei = pd.read_csv(EI)
    ced = pd.read_csv(CED)

    fig, axL = plt.subplots(figsize=(8.6, 5.6))
    axR = axL.twinx()

    # 12-point shared grid (vertical guides) + highlighted bulk T band
    for t in GRID:
        axL.axvline(t, color="#cccccc", ls=":", lw=0.7, zorder=0)
    axL.axvspan(BULK_T - 5, BULK_T + 5, color="#ffe08a", alpha=0.45, zorder=0)

    # LEFT: 32 vacuum E_intra reference curves (the dependency library)
    for _mid, g in ei.groupby("mol_id"):
        g = g.sort_values("temperature_K")
        axL.plot(g["temperature_K"], g["e_intra_kcal_mol"],
                 color="#aab4bf", lw=0.7, alpha=0.40, zorder=1)
    # markers at the lookup temperature on every reference curve (no legend label;
    # the E_intra family is represented in the legend by a solid line, below)
    look = ei[ei["temperature_K"] == BULK_T]
    axL.scatter(look["temperature_K"], look["e_intra_kcal_mol"], s=12,
                color="#5b6b7a", zorder=3)

    # RIGHT: assembled CED labels coloured by additive
    for add, c in ADD_COLOR.items():
        s = ced[ced["additive_type"] == add]
        axR.errorbar(s["temperature_K"], s["ced_MJ_m3"], yerr=s["ced_uncertainty"],
                     fmt="o", ms=6, color=c, ecolor=c, elinewidth=0.8, capsize=2,
                     mec="white", mew=0.6, alpha=0.95, zorder=5,
                     label=f"CED · {add} (n={len(s)})")

    # lookup -> subtraction -> CED annotation at the bulk T
    # placed in the upper empty band (T > 355 K has no CED points) so it never
    # overlaps the data points
    cbulk = ced[ced["temperature_K"] == BULK_T]["ced_MJ_m3"].mean()
    # point to the topmost SiO2 (orange) CED label in the highlighted column
    sio2_top = ced[(ced["additive_type"] == "SiO2") &
                   (ced["temperature_K"] == BULK_T)]["ced_MJ_m3"].max()
    axR.annotate(
        "lookup $E_{intra,i}(T_{bulk})$\n"
        r"$\rightarrow$ subtract: $-(PE_{bulk}-\Sigma n_i E_{intra,i})/V$"
        "\n$\\rightarrow$ assembled CED",
        xy=(BULK_T, sio2_top), xytext=(345, 430),
        fontsize=10.2, ha="left", va="center",
        bbox={"boxstyle": "round,pad=0.35", "fc": "#fff7e0", "ec": "#c8a23a", "lw": 0.8},
        arrowprops={"arrowstyle": "->", "color": "#c8a23a", "lw": 1.1,
                        "connectionstyle": "arc3,rad=0.0",
                        "relpos": (0.0, 0.5)})

    axL.set_xlabel("Temperature (K)  —  shared 12-point grid, 213–433 K (20 K spacing)",
                   fontweight="bold")
    axL.set_ylabel("Single-molecule vacuum $E_{intra,i}$  (kcal/mol)", color="black",
                   fontweight="bold")
    axR.set_ylabel("Cohesive energy density,  CED  (MJ/m$^3$)", color="black",
                   rotation=270, labelpad=18, fontweight="bold")
    axL.set_xlim(205, 441)
    axL.set_xticks(GRID)
    axL.set_xticklabels(GRID, rotation=0, fontsize=10)
    # unify tick-number sizes (10) and point ALL ticks inward, in black
    axL.tick_params(axis="x", labelsize=10, direction="in", color="black", labelcolor="black")
    axL.tick_params(axis="y", labelsize=10, direction="in", color="black", labelcolor="black")
    axR.tick_params(axis="y", labelsize=10, direction="in", color="black", labelcolor="black")
    for sp in axL.spines.values():
        sp.set_color("black")
    for sp in axR.spines.values():
        sp.set_color("black")

    # merged legend — E_intra curves represented by a SOLID LINE handle.
    # Aligned to the LOWER-LEFT INSIDE the figure (CED is high at low T, so this
    # corner is free of CED markers). A light white backdrop keeps it readable
    # over the faint E_intra reference lines. Molecule count is dynamic.
    eintra_handle = Line2D([0], [0], color="#8a97a4", lw=1.6,
                           label=f"{ei['mol_id'].nunique()} vacuum $E_{{intra,i}}$ refs")
    h2, l2 = axR.get_legend_handles_labels()
    axR.legend([eintra_handle] + h2, [eintra_handle.get_label()] + l2,
               fontsize=9.5, loc="lower left", frameon=True, framealpha=0.85,
               facecolor="white", edgecolor="#cccccc",
               handletextpad=0.5, borderpad=0.5)

    fig.tight_layout()
    fig.savefig(OUT, bbox_inches="tight")         # uses savefig.dpi (1200)
    pdf = OUT.replace(".png", ".pdf")
    try:
        fig.savefig(pdf, bbox_inches="tight")     # vector = infinite resolution
        pdf_msg = f" and {pdf} (vector)"
    except PermissionError:
        pdf_msg = f"  [PDF skipped: {pdf} is locked/open — close the viewer to update it]"
    plt.close(fig)
    print(f"wrote {OUT} (1200 dpi){pdf_msg}")
    print(f"  E_intra refs: {ei['mol_id'].nunique()} mols × "
          f"{ei['temperature_K'].nunique()} T = {len(ei)} rows")
    print(f"  CED labels: {len(ced)}  (highlighted bulk T = {BULK_T:.0f} K, "
          f"mean CED = {cbulk:.1f} MJ/m³)")


if __name__ == "__main__":
    main()
