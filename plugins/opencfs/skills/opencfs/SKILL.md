---
name: opencfs
description: Set up, run, debug and post-process finite-element simulations with openCFS (CFS++, the "Coupled Field Simulation" solver), from geometry and Gmsh meshing through the XML simulation and material files and the cfs run, to reading .cfs/HDF5 results and plotting. Covers structural mechanics (static, eigenfrequency, harmonic, transient), acoustics, heat conduction, electrostatics, magnetics/coils and coupled problems (piezoelectric, vibro-acoustic, thermo-mechanical). Use this skill whenever the user mentions openCFS, CFS++, cfs, a cfsSimulation XML, .cfs result files or MaterialDataBase.xml, and also when they ask for an FE/FEM simulation of a physical field problem (e.g. "simulate the eigenfrequencies of this plate", "compute the sound pressure in this duct", "what is the capacitance", "temperature distribution in this heat sink", "piezo actuator displacement") and haven't named another solver.
---

# openCFS simulations

openCFS is an open-source FE solver. A simulation consists of:
**mesh** (Gmsh `.msh`, regions = physical groups) + **material file** (XML) + **simulation file**
(XML: regions → PDEs → BCs → analysis → stored results) → `cfs -p sim.xml job` →
`results_hdf5/job.cfs` (HDF5) + `history/*.hist` (text) + `job.info.xml` (status).

The bundled scripts handle the error-prone parts. Everything here was tested against openCFS 25.07 (Windows build).

## Environment check (do this once per session, before the first run)
- **Solver:** the scripts find `cfs` via `$CFS_EXE`, then `PATH`, then common install folders
  (`C:/Tools/OpenCFS/CFS-*/bin`, `/opt/openCFS/bin`, `~/openCFS/bin`). If none is found, ask the user where
  openCFS is installed and set `CFS_EXE=<install>/bin/cfs(.exe)`. If it isn't installed, point the user to
  https://opencfs.gitlab.io/userdocu/Installation/ (prebuilt Windows/Linux packages).
- **Install tree:** schemas are in `<install>/share/xml`. The material database is
  `<install>/share/xml/CFS-Material/Examples/MaterialDataBase.xml`. Set `CFS_SCHEMA_ROOT` if the schemas live elsewhere.
- **Python packages:** `gmsh`, `h5py`, `numpy`, `matplotlib`, `lxml`. Check with
  `python -c "import gmsh, h5py, numpy, matplotlib, lxml"`. If any is missing, install with
  `python -m pip install gmsh h5py numpy matplotlib lxml` (ask the user first).
- **New installation:** run `python scripts/selftest.py` once. It verifies solver, schemas and Python stack together.

Paths below are relative to this skill's directory. Use absolute paths when calling the scripts.

## Workflow

### 1. Pin down the problem
Decide these, stating sensible assumptions rather than asking about every detail:
physics (PDEs), dimensionality (2D `plane`, `axi`, or `3d`; prefer 2D or axi when symmetry
allows, since it's much faster and easier to check), analysis type (static / transient / harmonic /
eigenFrequency), loads and BCs, materials, and which outputs answer the user's question.
Write down a rough analytic estimate of the main result now. You'll need it in step 6.

### 2. Make a work folder
Use the folder the user names. Otherwise use their project or current folder (not a temp dir), one subfolder per study, e.g.
`./cfs_<name>/` containing `mesh.py`, `mat.xml`, `<name>.xml`. Results land next to the XML.

### 3. Mesh with Gmsh (scripts/cfs_mesh.py)
Write a small `mesh.py` using the helper. `assets/templates/meshes_example.py` has tested
examples for every template.
```python
import sys; sys.path.insert(0, r"<skill>/scripts")
from cfs_mesh import Mesh
m = Mesh("plate")
r = m.occ.addRectangle(0, 0, 0, 0.2, 0.1); d = m.occ.addDisk(0.1, 0.05, 0, 0.01, 0.01)
m.cut([d])          # HOLE: subtract the disk.  For an INCLUSION of another material use m.fragment()
                    # instead (both stay as regions with a shared, conforming interface).
m.group(2, m.all(2), "steel")                     # volume regions (dim 2 in 2D, 3 in 3D)
m.group(1, m.in_box(1, xmax=0), "clamp")          # boundary regions for BCs (dim-1)
hole = m.in_box(1, 0.09, 0.11, 0.04, 0.06)
m.group(1, hole, "hole")
m.refine(1, hole, size_min=2e-4, size_max=4e-3, dist_min=1e-3, dist_max=2e-2)  # local refinement
m.write("plate.msh", size=0.004, quads=True)      # meshes, verifies groups, writes msh 2.2 ASCII
```
Rules: every region and BC surface needs its own physical group. Use one shared name for an interface
between coupled regions. Use SI units, or `scaleFac` on input. Resolve waves with ≥ 10 linear
elements per wavelength. Refine where gradients are high (notches, holes, electrode edges).
Use symmetry to cut size: model a half or quarter and put a symmetry BC on the cut. Mechanics: `<fix>` only the
normal component (`<fix name="symX"><comp dof="x"/></fix>` on a plane x = 0). Heat, electrostatics, acoustics:
leave the cut free (natural BC = zero flux). Plot it whole again with `cfs_results.py plot --mirror xy`.
If the user supplies a mesh (`.msh`, `.cdb`, `.cfs/.h5`), use it directly and list its region names
with `run_cfs.py --check-only` (Gmsh) or `cfs_results.py info` (HDF5).

### 4. Materials
Copy `MaterialDataBase.xml` into the folder as `mat.xml`. It covers Air, Water, Steel, Aluminium,
Copper, Iron, Silicon, PZT-4/5A/5H, and more. Append custom materials as needed. Names are
case-sensitive, and each material needs a class block for every PDE it's used in. Syntax is in
`references/xml_reference.md` §10.
**Piezo materials:** the database stores the datasheet *free* permittivity ε^T, but openCFS needs the
*clamped* ε^S. Run `python scripts/piezo_material.py mat.xml PZT-5A` (also works for PZT-4) and use `PZT-5A_epsS`.
Without it, displacements are right but charge/capacitance is about 50 % too high and coupling factors too low.
The tool skips PZT-5H because its data is inconsistent; write that one by hand.

### 5. Simulation XML, starting from a tested template
| need | template |
|---|---|
| static stress / deformation | `assets/templates/mech_static_2d.xml` |
| eigenfrequencies / modes | `assets/templates/mech_eigen_2d.xml` |
| temperature, steady + transient, convection | `assets/templates/heat_static_transient_2d.xml` |
| acoustic field, frequency sweep, free-field outlet | `assets/templates/acoustic_harmonic_2d.xml` |
| potential, field, capacitance | `assets/templates/electrostatic_2d.xml` |
| coil field, magnetic energy, inductance | `assets/templates/magnetic_static_2d.xml` |
| piezoelectric actuator / sensor, charge, admittance | `assets/templates/piezo_static_3d.xml` |
| structure radiating sound (vibro-acoustics) | `assets/templates/mech_acoustic_harmonic_2d.xml` |

Each template's header comment lists the mesh groups it expects, the verified check value, and
the gotchas. Combine them (e.g. harmonic analysis + piezo coupling) by swapping the `<analysis>` block.
Going to 3D means `geometryType="3d"`, `subType="3d"`, `dof="z"` comps, and dim-3/dim-2 mesh groups.

For anything the templates don't show, don't guess element names. Ask the installed schema:
```bash
python scripts/schema_lookup.py pdes                            # PDEs, analyses, couplings
python scripts/schema_lookup.py show acoustic/bcsAndLoads       # all BCs of a PDE
python scripts/schema_lookup.py show mechanic/bcsAndLoads/force # attributes + children of one BC
python scripts/schema_lookup.py results heatConduction          # valid result types
python scripts/schema_lookup.py results direct/piezoDirect      # coupled results (e.g. true piezo charge)
python scripts/schema_lookup.py show --material piezo           # material file syntax
python scripts/schema_lookup.py grep pml                        # search by keyword
```
`(choice N: use only ONE ...)` in the output marks mutually exclusive elements. Structure notes,
coupling patterns, damping/PML, expressions and point probes are in `references/xml_reference.md`.

### 6. Run (scripts/run_cfs.py)
```bash
python scripts/run_cfs.py path/to/sim.xml [jobname] [--threads N]
```
It pre-flights the files (comment before root, mesh format, empty or unknown region names,
missing or case-mismatched materials, material class vs PDE), runs cfs in the XML's folder,
writes `<job>.log`, and prints status, the error block, the result file and a summary of each
`.hist` file. Use `--check-only` to validate without solving. Run long 3D jobs in the background.
On errors, read `references/troubleshooting.md`, fix, and rerun. Most failures are naming or schema issues
with exact messages.

### 7. Post-process and check (scripts/cfs_results.py)
```bash
python scripts/cfs_results.py info results_hdf5/job.cfs                       # what is stored
python scripts/cfs_results.py plot results_hdf5/job.cfs <quantity> [--step N] [--comp x|y|z] [--deform S] -o f.png
python scripts/cfs_results.py export results_hdf5/job.cfs <quantity> --step all -o f.csv
python scripts/cfs_results.py hist history/<file>.hist -o h.png
```
For custom quantities (FRFs, SPL, line plots, capacitance, max stress), import `CfsFile` in
a short script. See `references/results_and_postprocessing.md` for the HDF5 layout and examples.
Harmonic results are complex, so use `np.abs`. Eigenfrequencies are the step values.
Stresses, fluxes and fields are **element-centroid values** (openCFS has no nodal stress output),
so the max element value underestimates peaks at notches and edges. For peak values, follow
"Peak values" in the results reference.

**Check plausibility before reporting.** Compare against your analytic estimate from step 1, check
the primary field's range and symmetry, and for important numbers rerun with a finer mesh.
A plausible-looking plot can hide a wrong BC (see the magnetic `ground` pitfall in troubleshooting).

### 8. Report
Give the answer to the question (numbers with units), how it compares with the estimate,
key assumptions (2D/per-metre depth, materials, BCs, mesh size), and the files (XML, mesh script,
plots), so the user can rerun or modify the study. Mention ParaView (CFSReader opens `.cfs`)
for interactive 3D viewing.

## Self-test
`python scripts/selftest.py [workdir]` meshes and runs all eight templates and compares them with analytic
values. Use it after installing or updating openCFS, or after editing a template.
