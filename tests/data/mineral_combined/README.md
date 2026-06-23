# Mineral + Binder Combined LAMMPS Data Fixtures (Wave 5)

These fixtures pair a small **silica slab** (frozen, INTERFACE FF) with
a small **organic binder fragment** (GAFF2 toluene-style ring) in a
single LAMMPS `full` atom-style data file. They exist to lock the
**cross-interaction LJ values** that the layered build pipeline emits
when both phases share one combined data file.

## Wave 5 contract

The Wave 1 LAYER_BULKFF protocol regression
(`tests/protocols/test_lammps_input.py::TestWave1LayeredCombinedRegression`)
already locks the *protocol* layer:

* `pair_modify mix arithmetic` (Lorentz-Berthelot) for layered builds
* `kspace_modify slab 3.0`
* `pair_style lj/cut/coul/long`

What the protocol regression does NOT cover is the **emitted Pair Coeffs
table** for the silica side: even with the right mix rule, if the
silica Si pair coefficient line drops to e.g. UFF Si ε=0.402 (instead
of the INTERFACE FF Si ε=0.00040), the build will be wrong by ~1000×
on the cross interaction.

The Wave 5 fixtures committed here serve TWO purposes:

1. **Reference snapshot** — `silica_binder_ref.lammps_data` is what
   a layered build SHOULD emit for a small Si4O8 slab plus a toluene
   ring fragment. The Wave 5 regression test
   (`tests/protocols/test_layered_combined_data.py`) parses this file
   and asserts the per-element Pair Coeffs values, the
   `pair_modify mix arithmetic` line, and the slab Ewald correction
   header.

2. **Drift lockdown** — if a future refactor changes how
   `MolTopologyBuilder` writes mineral pair coefficients (e.g.,
   accidentally promotes UFF over INTERFACE FF), the regression
   immediately fails with a diff that points at the offending Pair
   Coeffs row.

## Files

| Filename | Description |
|---|---|
| `silica_binder_ref.lammps_data` | Hand-curated reference: 12-atom Si4O8 slab + 6-atom binder ring stub |

### Atom-type ordering (Wave 5 reference)

1. `Si_tet` (interface-FF Si, ε=0.00040, σ=3.302)
2. `O_br`   (interface-FF bridging O, ε=0.15540, σ=3.166)
3. `CA`     (GAFF2 aromatic C, ε=0.07000, σ=3.5500)
4. `HA`     (GAFF2 aromatic H, ε=0.03000, σ=2.4200)

The order is fixed because the regression test reads the Pair Coeffs
table by row index. If a future refactor reorders atom types, BOTH
the fixture AND the test must be updated.

### Charge balance contract (read this before editing the fixture!)

The fixture has TWO sections with different neutrality semantics:

* **Silica slab (12 atoms, types 1-2): EXACTLY NEUTRAL.**
  4 × Si (+2.10) + 8 × O (-1.05) = 0. The CLAYFF charges sum cleanly,
  and the regression test asserts this with abs=1e-6. Any drift here
  is a bug.

* **Binder fragment (6 atoms, types 3-4): INTENTIONALLY NON-NEUTRAL.**
  4 × CA (-0.115) + 2 × HA (+0.115) = **-0.230**. This is NOT a
  complete toluene molecule — it is a *stub* of an aromatic ring,
  small enough to keep the regression fast. The two missing HA atoms
  would be needed to balance the ring. The regression test asserts
  the exact -0.230 sum so a future re-edit cannot silently change
  the stub.

* **Total system charge: -0.230** (silica 0 + binder stub -0.230).
  The regression test `test_total_system_charge_is_well_defined`
  locks this exact value.

The regression test names reflect this contract:

* `test_silica_section_neutral` — asserts neutrality (passes)
* `test_binder_stub_charge_sum_is_intentional_non_neutral` — asserts
  the EXACT non-neutral sum (-0.230). The "non_neutral" in the test
  name is deliberate: a check called "neutral" would be false-friend
  and would mask a future regression where someone "fixes" the stub
  by reverting it to 4 CA + 2 HA + 2 missing atoms.

If a future PR expands the binder fragment to a neutral aromatic
ring, ALL of the following must be updated in the same commit:

1. `silica_binder_ref.lammps_data` header comment
2. This README's charge balance contract section
3. The regression test name and the asserted total charge in
   `tests/protocols/test_layered_combined_data.py`
