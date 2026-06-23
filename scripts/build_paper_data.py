"""Build the Excel workbook that backs every paper figure (single source of truth).

Each figure reads from one sheet of docs/paper_data.xlsx. When new data is added,
append it as a NEW sheet (do not overwrite existing sheets).

Sources (real run data):
  - log.lammps  : thermo time series  -> sheet 'thermo'
  - data.lammps : per-type FF params and atom counts -> sheets 'ff_parameters',
                  'charge_neutrality', 'system_spec'

Usage: python scripts/build_paper_data.py [run_dir]
"""

import re
import sys

import pandas as pd

RUN = sys.argv[1] if len(sys.argv) > 1 else (
    "database/A1_X1_NA_SiO2_333K_910a9e/"
    "attempt_961bd40a-3dd9-4fa3-b593-5533dc385dfb/seed_20260613"
)
OUT = "docs/paper_data.xlsx"

_SECTIONS = {"Masses", "Pair Coeffs", "Bond Coeffs", "Angle Coeffs",
             "Dihedral Coeffs", "Improper Coeffs", "Atoms", "Velocities",
             "Bonds", "Angles", "Dihedrals", "Impropers"}
_MINERAL = ("Si", "_br", "_h", "_oh")


def parse_thermo(path):
    """Parse all thermo blocks. Column positions differ per stage (minimize has no
    Temp column), so map columns by header name within each block, not by fixed index."""
    blocks, header, cur = [], None, []
    with open(path) as fh:
        for line in fh:
            s = line.split()
            if s and s[0] == "Step" and "Density" in line:
                if cur:
                    blocks.append((header, cur))
                header, cur = s, []
                continue
            if header and s and re.match(r"^-?\d", s[0]):
                try:
                    v = [float(x) for x in s[: len(header)]]
                except ValueError:
                    if cur:
                        blocks.append((header, cur))
                    header, cur = None, []
                    continue
                if len(v) >= len(header) - 1:
                    cur.append(v)
            elif header and s and s[0].startswith(("Loop", "WARNING", "@@", "#")):
                if cur:
                    blocks.append((header, cur))
                header, cur = None, []
    if cur:
        blocks.append((header, cur))

    want = {"step": "Step", "temp": "Temp", "poteng": "PotEng",
            "volume": "Volume", "density": "Density"}
    rows, frame = [], 0
    for bi, (hdr, data) in enumerate(blocks):
        ci = {k: (hdr.index(col) if col in hdr else None) for k, col in want.items()}
        for v in data:
            row = {k: (v[ci[k]] if ci[k] is not None and ci[k] < len(v) else None)
                   for k in want}
            row["frame"], row["stage"] = frame, bi
            rows.append(row)
            frame += 1
    return pd.DataFrame(rows, columns=["frame", "stage", "step", "temp",
                                       "density", "poteng", "volume"])


def parse_data(path):
    masses, pair, charge, count = {}, {}, {}, {}
    section = None
    with open(path) as fh:
        for line in fh:
            t = line.strip()
            if t in _SECTIONS:
                section = t
                continue
            if not t:
                continue
            s = t.split()
            if section == "Masses" and s[0].isdigit():
                m = re.search(r"#\s*\S+\s+(\S+)", t)
                masses[int(s[0])] = m.group(1) if m else s[0]
            elif section == "Pair Coeffs" and s[0].isdigit():
                pair[int(s[0])] = (float(s[1]), float(s[2]))
            elif section == "Atoms" and len(s) >= 7:
                try:
                    typ, q = int(s[2]), float(s[3])
                except ValueError:
                    continue
                charge.setdefault(typ, q)
                count[typ] = count.get(typ, 0) + 1
    rows = []
    for typ in sorted(masses):
        eps, sig = pair.get(typ, (None, None))
        label = masses[typ]
        rows.append({
            "type": typ, "label": label,
            "ff_class": "mineral" if any(k in label for k in _MINERAL) else "organic",
            "epsilon_kcal_mol": eps, "sigma_A": sig,
            "charge_e": charge.get(typ), "count_total": count.get(typ, 0),
        })
    return pd.DataFrame(rows)


def charge_neutrality(ff_df, n_particles=2):
    """Per-particle CLAYFF charge audit for the silica nanoparticle."""
    mineral = ff_df[ff_df["ff_class"] == "mineral"].copy()
    mineral["count_per_particle"] = (mineral["count_total"] / n_particles).round().astype(int)
    mineral["subtotal_e"] = mineral["count_per_particle"] * mineral["charge_e"]
    out = mineral[["label", "count_per_particle", "charge_e", "subtotal_e"]].copy()
    total = pd.DataFrame([{"label": "TOTAL",
                           "count_per_particle": int(out["count_per_particle"].sum()),
                           "charge_e": None,
                           "subtotal_e": round(out["subtotal_e"].sum(), 6)}])
    return pd.concat([out, total], ignore_index=True)


def system_spec(ff_df, thermo_df):
    n_atoms = int(ff_df["count_total"].sum())
    n_min = int(ff_df[ff_df["ff_class"] == "mineral"]["count_total"].sum())
    rows = [
        ("system_id", "A1_X1_NA_SiO2_333K"),
        ("binder", "AAA1 (SARA, X1 = 72 molecules)"),
        ("total_atoms", n_atoms),
        ("atom_types", int(ff_df["type"].max())),
        ("mineral_atoms_total", n_min),
        ("SiO2_particles", 2),
        ("atoms_per_SiO2", n_min // 2 if n_min else None),
        ("temperature_K", 333.0),
        ("boundary", "p p p (bulk)"),
        ("pair_style", "lj/cut/coul/long 12.0"),
        ("mixing", "Lorentz-Berthelot (arithmetic)"),
        ("kspace", "pppm 1.0e-4"),
        ("thermo_frames", int(len(thermo_df))),
    ]
    return pd.DataFrame(rows, columns=["property", "value"])


if __name__ == "__main__":
    thermo = parse_thermo(f"{RUN}/log.lammps")
    ff = parse_data(f"{RUN}/data.lammps")
    cn = charge_neutrality(ff)
    spec = system_spec(ff, thermo)

    with pd.ExcelWriter(OUT, engine="openpyxl") as w:
        spec.to_excel(w, sheet_name="system_spec", index=False)
        ff.to_excel(w, sheet_name="ff_parameters", index=False)
        cn.to_excel(w, sheet_name="charge_neutrality", index=False)
        thermo.to_excel(w, sheet_name="thermo", index=False)

    print(f"wrote {OUT}")
    print(f"  system_spec: {len(spec)} rows; ff_parameters: {len(ff)} types; "
          f"thermo: {len(thermo)} frames")
    print(f"  charge neutrality total = {cn.iloc[-1]['subtotal_e']} e")
