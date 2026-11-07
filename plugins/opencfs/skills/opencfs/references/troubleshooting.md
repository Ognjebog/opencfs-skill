# Troubleshooting openCFS runs

cfs prints a `>> Error:` block, writes `status="aborted"` to `<job>.info.xml` and exits with 1.
`run_cfs.py` prints that block. Find the message below.

| message (excerpt) | cause | fix |
|---|---|---|
| `document root has 2 children, expected 1` | an XML comment (or second element) before/after `<cfsSimulation>` | move comments inside the root element |
| `XML parsing error: 'no declaration found for element 'X''` | typo or wrong element name, or a wrong/missing `xmlns` | `schema_lookup.py grep X`; root needs `xmlns="http://www.cfs++.org/simulation"` |
| `element 'A' is not allowed for content model '(...)'` | wrong child or wrong order. The model lists what's allowed, `|` = choose ONE | reorder or replace per the listed model; `schema_lookup.py show <path>` |
| `attribute 'v' is not declared for element 'E'` | wrong attribute name (e.g. `windingTurns value=` → `number=`) | `schema_lookup.py show <path to E>` |
| `No entities with name 'X' are defined in the grid` | BC/region name not a Gmsh physical group | check names with `run_cfs.py --check-only` (lists mesh groups) |
| `Region has neither volume nor surface elements: X` | physical group exists but is empty (selection missed) | use `cfs_mesh.Mesh.group` (refuses empty groups); OCC bounding boxes need a tolerance |
| `Cannot find material 'X'` | material name not in the material file (case-sensitive) | `grep '<material name' mat.xml` |
| `Could not assign material ... of materialClass 'mechanical'` | the material lacks that class block | add `<mechanical>` / `<acoustic>`... to the material |
| `Currently the windingTurns can not be specified` | `<windingTurns>` isn't implemented (25.07) | use `<wireCrossSection area="A_wire"/>` |
| solver diverges / NaN / huge values | missing Dirichlet BC (rigid-body modes, floating potential), or bad elements | constrain rigid-body motion (`fix`), ground a potential; check mesh quality |
| harmonic acoustic results "ring" / standing waves where free field is expected | reflecting boundary | `absorbingBCs` or a PML layer, and a larger domain |

## Pitfalls that DON'T give an error (verified)
* **Magnetic 2D:** `<ground name="outer"/>` is accepted but does not constrain A. The result
  looks plausible from far away, but A carries a ~1e7 offset, B has hot spots and energies are
  absurd. Use `<fluxParallel name="outer"><comp dof="z"/></fluxParallel>`.
* **Docs vs schema:** some doc pages show outdated syntax (e.g. `<fluxParallel name=".."/>` with no
  `comp`, or misspelled `thermalExpanison`). When they disagree, the schema in `<install>/share/xml` wins.
* **Gmsh format:** msh 4.x is rejected or misread. Always write `Mesh.MshFileVersion = 2.2`, ASCII.
* **Non-conforming multi-region meshes:** separately meshed touching solids create cracks (no
  coupling). Use `occ.fragment` (`Mesh.fragment()`).
* **Units:** SI throughout. If the geometry is in mm, set `scaleFac="1e-3"` on the mesh input, or model in metres.
* **2D plane results are per unit depth** (verified: elecEnergy and heatFlux are per metre). In axi use x = r ≥ 0
  and y = axial. Check how region results are normalised (per radian or the full 360°) against a hand calculation.
* **Mechanical `pressure` sign:** positive pushes into the body.
* **`force` on a surface region** is applied at its nodes. Check the total against the intended load.
* **Piezo sign:** the displacement sign follows the poling direction in the material data. Use `matRotation` to orient it.
* **Piezo charge / admittance:** store `elecCharge` (and `elecFluxDensity`) in
  `<couplingList><direct><piezoDirect><storeResults>`. That gives the full D = e·S + ε·E. The same result
  under `<electrostatic><storeResults>` is only ε·E, which is wrong. If both are stored, they go into
  the same `.hist` file one after the other (`run_cfs.py` flags "2 result blocks").
* **Piezo permittivity in MaterialDataBase.xml is ε^T, not ε^S** (PZT-4/5A/5H, BaTiO₃-poled).
  Use `scripts/piezo_material.py` (verified: corrected PZT-5A gives the datasheet free capacitance exactly).
* **Axisymmetric piezo:** use `geometryType="axi"`, `mechanic subType="axi"`, x = r, y = axial. With no
  `matRotation`, material axis 3 (poling) maps to the axial direction (tested), and `alpha="90"` flips the
  poling sign. Only u_r needs fixing on the axis if anything. A free body is fine for harmonic
  analysis at f > 0. The warnings "No implementation for principal stress/strain in axi-formulation yet" are harmless.
* **Gmsh `transfinite=True`** picks the node count per curve from `size`, so element counts can be
  one off from L/size. Set them explicitly with `gmsh.model.mesh.setTransfiniteCurve` if exact counts matter.

## Performance
* `-t N` / `CFS_NUM_THREADS` sets OpenMP threads (`run_cfs.py` defaults to half the cores, at most 8).
* 2D models with < 1e5 nodes solve in seconds. For large 3D models, use linear elements first and
  check memory in `<job>.info.xml` (`<memory peak=...>`).
* Solver options go in `<linearSystems><system><solverList>` (e.g. `<pardiso/>`, `<directLU/>`,
  `<cg>` with preconditioner). Look them up with `schema_lookup.py show cfsSimulation/sequenceStep/linearSystems/system`.
  The default direct solver is fine for most models.
