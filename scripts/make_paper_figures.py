"""Generate publication figures for the COMID manuscripts.

Figure DATA is read from the Excel workbook docs/paper_data.xlsx (built by
scripts/build_paper_data.py). To add a figure, add a sheet there first, then a
plotting function here that reads that sheet. Schematic figures (architecture,
workflow) carry no data and are drawn directly.

Outputs (docs/figures/*.png, 300 dpi):
  fig_architecture.png        - module/two-tier architecture (SoftwareX Fig 1)
  fig_thermo_convergence.png  - density & temperature vs frame (Fig 2 / validation)
  fig_nanocomposite_ff.png    - per-type LJ epsilon & charge (Fig 5 / MethodsX)
  fig_methodsx_workflow.png   - Step 1-8 protocol workflow (MethodsX Fig 1)

Usage: python scripts/make_paper_figures.py
"""

import os

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Patch

DATA = "docs/paper_data.xlsx"
OUT = "docs/figures"
os.makedirs(OUT, exist_ok=True)
plt.rcParams.update({"font.size": 10, "figure.dpi": 300, "savefig.dpi": 300})


def fig_architecture():
    fig, ax = plt.subplots(figsize=(7.2, 4.3))
    ax.axis("off")
    core = ["builder\n(Packmol)", "forcefield\n(typing_router)", "protocols\n(Jinja2)",
            "parsers", "metrics", "ml", "recommendation\n(BO/Pareto)"]
    ax.add_patch(FancyBboxPatch((0.02, 0.86), 0.96, 0.1, boxstyle="round,pad=0.01",
                                fc="#d9e8f5", ec="#2c6fa6"))
    ax.text(0.5, 0.91, "SSOT: contracts/ (schemas + policies)  ·  common/ (pathing, hashing, logging)",
            ha="center", va="center", fontsize=9, weight="bold")
    ax.add_patch(FancyBboxPatch((0.02, 0.30), 0.96, 0.48, boxstyle="round,pad=0.01",
                                fc="#eef7ee", ec="#3a8f3a", lw=1.5))
    ax.text(0.5, 0.74, "Reviewable core  (no LAMMPS / no GPU)", ha="center",
            fontsize=9, weight="bold", color="#2f6f2f")
    for i, name in enumerate(core):
        x = 0.05 + i * 0.133
        ax.add_patch(FancyBboxPatch((x, 0.40), 0.12, 0.22, boxstyle="round,pad=0.008",
                                    fc="white", ec="#3a8f3a"))
        ax.text(x + 0.06, 0.51, name, ha="center", va="center", fontsize=7.2)
        if i < len(core) - 1:
            ax.add_patch(FancyArrowPatch((x + 0.12, 0.51), (x + 0.133, 0.51),
                                         arrowstyle="->", mutation_scale=9, color="#888"))
    ax.add_patch(FancyBboxPatch((0.02, 0.04), 0.96, 0.20, boxstyle="round,pad=0.01",
                                fc="#fdeee0", ec="#c8762b", lw=1.5))
    ax.text(0.5, 0.20, "Execution backend  (optional)", ha="center", fontsize=9,
            weight="bold", color="#a85f1f")
    for i, name in enumerate(["orchestrator\n(Celery+GPUService)", "LAMMPS\n(KOKKOS/CUDA)",
                              "Packmol / AmberTools"]):
        x = 0.10 + i * 0.30
        ax.add_patch(FancyBboxPatch((x, 0.07), 0.24, 0.09, boxstyle="round,pad=0.008",
                                    fc="white", ec="#c8762b"))
        ax.text(x + 0.12, 0.115, name, ha="center", va="center", fontsize=7.2)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig_architecture.png", bbox_inches="tight")
    plt.close(fig)


def fig_thermo(df):
    fig, ax1 = plt.subplots(figsize=(6.8, 4.0))
    ax1.plot(df["frame"], df["density"], color="#1f6fb2", lw=1.4)
    ax1.set_xlabel("Thermo frame (minimize → NVT → NPT)")
    ax1.set_ylabel("Density (g/cm$^3$)", color="#1f6fb2")
    ax1.tick_params(axis="y", labelcolor="#1f6fb2")
    ax2 = ax1.twinx()
    ax2.plot(df["frame"], df["temp"], color="#c0392b", lw=0.9, alpha=0.6)
    ax2.set_ylabel("Temperature (K)", color="#c0392b")
    ax2.tick_params(axis="y", labelcolor="#c0392b")
    for b in df.groupby("stage")["frame"].min().tolist()[1:]:
        ax1.axvline(b, color="#999", ls="--", lw=0.7)
    ax1.set_title("AAA1 + SiO$_2$ nanocomposite: thermodynamic convergence")
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig_thermo_convergence.png", bbox_inches="tight")
    plt.close(fig)


def fig_nanocomposite(df):
    df = df[df["epsilon_kcal_mol"].notna()].reset_index(drop=True)
    colors = ["#c8762b" if c == "mineral" else "#3a78bc" for c in df["ff_class"]]
    fig, (axa, axb) = plt.subplots(2, 1, figsize=(7.4, 5.2), sharex=True)
    axa.bar(range(len(df)), df["epsilon_kcal_mol"], color=colors)
    axa.set_yscale("log")
    axa.set_ylabel("LJ $\\epsilon$ (kcal/mol, log)")
    axa.set_title("Per-type force-field parameters (GAFF2 organic vs INTERFACE-FF/CLAYFF mineral)")
    axa.legend(handles=[Patch(color="#3a78bc", label="GAFF2 (organic)"),
                        Patch(color="#c8762b", label="INTERFACE-FF/CLAYFF (mineral)")],
               fontsize=8, loc="upper right")
    axb.bar(range(len(df)), df["charge_e"].fillna(0), color=colors)
    axb.axhline(0, color="k", lw=0.6)
    axb.set_ylabel("Charge (e)")
    axb.set_xticks(range(len(df)))
    axb.set_xticklabels(df["label"], rotation=60, ha="right", fontsize=7)
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig_nanocomposite_ff.png", bbox_inches="tight")
    plt.close(fig)


def fig_workflow():
    steps = ["1. Define\ncomposition", "2. Pack bulk\n(Packmol, p p p)",
             "3. FF route\n(typing_router)", "4. Organic\nGAFF2/AM1-BCC",
             "5. Mineral\nINTERFACE+CLAYFF", "6. Couple\nL-B + PPPM",
             "7. Charge\nneutrality = 0", "8. MD\nmin→NVT→NPT"]
    fig, ax = plt.subplots(figsize=(7.6, 3.0))
    ax.axis("off")
    for i, s in enumerate(steps):
        col, row = i % 4, i // 4
        x, y = 0.02 + col * 0.25, 0.55 - row * 0.42
        fc = "#fdeee0" if i in (3, 4) else "#eef4fb"
        ax.add_patch(FancyBboxPatch((x, y), 0.21, 0.30, boxstyle="round,pad=0.01",
                                    fc=fc, ec="#34689a"))
        ax.text(x + 0.105, y + 0.15, s, ha="center", va="center", fontsize=7.6)
        if i not in (3, 7):
            ax.add_patch(FancyArrowPatch((x + 0.21, y + 0.15), (x + 0.25, y + 0.15),
                                         arrowstyle="->", mutation_scale=10, color="#777"))
    ax.add_patch(FancyArrowPatch((0.665, 0.55), (0.125, 0.43), arrowstyle="->",
                                 mutation_scale=10, color="#777",
                                 connectionstyle="arc3,rad=-0.2"))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_title("Dual force-field parameterization protocol (Steps 1–8)", fontsize=9)
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig_methodsx_workflow.png", bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    thermo = pd.read_excel(DATA, sheet_name="thermo")
    ff = pd.read_excel(DATA, sheet_name="ff_parameters")
    fig_architecture()
    fig_thermo(thermo)
    fig_nanocomposite(ff)
    fig_workflow()
    print(f"figures written to {OUT}/ (data from {DATA})")
