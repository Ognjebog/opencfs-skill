# openCFS skill for Claude

A [Claude skill](https://code.claude.com/docs/en/skills) that lets Claude run complete
[openCFS](https://opencfs.gitlab.io/userdocu/) finite-element studies, from a plain-language problem
description to a checked answer:

**geometry → Gmsh mesh → material + simulation XML → `cfs` run → HDF5 results → plots and plausibility checks**

Ask things like:

> "What are the first four eigenfrequencies of a 1 m × 0.1 m steel cantilever?"
> "Stress concentration factor of a 200 × 100 mm plate with a 20 mm hole under 50 MPa tension?"
> "Simulate the admittance of a 40 mm × 2 mm PZT-5A disc from 30 to 70 kHz."
> "Sound pressure in a 1 m duct driven by a piston at 1 mm/s, 200–1000 Hz."

## What's inside

| Part | What it does |
|---|---|
| `SKILL.md` | The workflow Claude follows: problem setup, meshing, materials, XML, run, post-processing, checks |
| 8 tested templates | Static and eigenfrequency mechanics, steady + transient heat, harmonic acoustics, electrostatics, 2D magnetics with a coil, piezoelectric, vibro-acoustic coupling |
| `scripts/cfs_mesh.py` | Gmsh helper: tolerant entity selection, holes (`cut`), conforming multi-region meshes (`fragment`), local refinement, msh 2.2 output, empty-group detection |
| `scripts/run_cfs.py` | Pre-flight checks (names vs. mesh, materials, XML pitfalls), runs `cfs`, summarises the status, errors and history results |
| `scripts/cfs_results.py` | Reads `.cfs` HDF5 results without ParaView: info, CSV export, 2D plots (per-element polygons, deformation, symmetry mirroring), `.hist` files |
| `scripts/schema_lookup.py` | Queries the installed openCFS XSD schemas, so element names, attributes and allowed values are looked up instead of guessed |
| `scripts/piezo_material.py` | Corrects piezo permittivities in the bundled material database (see below) |
| `scripts/selftest.py` | Meshes and runs every template and compares against analytic results |
| `references/` | XML reference, results and HDF5 layout, troubleshooting table |

## Verified results

`selftest.py` on openCFS 25.07 (Windows):

| Check | openCFS | Analytic |
|---|---|---|
| Bar under axial load, tip displacement | 4.993e-6 m | 5.000e-6 m |
| Cantilever first eigenfrequency | 81.8 Hz | 81.4 Hz (Euler–Bernoulli) |
| Heat flux through convective edge | 198.75 W/m | 198.76 W/m |
| Plane wave in duct, \|p\| | 0.41329 Pa | ρcv = 0.41327 Pa |
| Parallel-plate field energy | 4.4295e-7 J/m | ½ε₀E²V = 4.4295e-7 J/m |
| PZT-5A cube, thickness displacement | 3.740e-8 m | d₃₃V = 3.74e-8 m |
| PZT-5A cube, electrode charge | 1.505e-9 C | ε₃₃ᵀAV/t = 1.505e-9 C |

Two harder problems, solved by Claude using only the skill:
- plate with a hole: K_t = 3.12, against Peterson 3.135;
- free PZT-5A disc, first radial resonance: 49.5 kHz, against 49.6 kHz analytic.

## Requirements

- **openCFS** (tested with 25.07). Installation: https://opencfs.gitlab.io/userdocu/Installation/.
  The scripts find `cfs` via `$CFS_EXE`, `PATH`, or common install folders.
- **Python 3** (tested with 3.12) with `gmsh h5py numpy matplotlib lxml`:
  ```bash
  python -m pip install gmsh h5py numpy matplotlib lxml
  ```
- Optional: ParaView with the CFSReader plugin for interactive 3D viewing.

## Installation

### Claude Code: plugin marketplace (recommended)
```bash
claude plugin marketplace add Ognjebog/opencfs-skill
claude plugin install opencfs@opencfs-skills
```
You can also run `/plugin marketplace add Ognjebog/opencfs-skill` and `/plugin install opencfs@opencfs-skills` inside a session.
The skill loads automatically when a task needs it. To call it explicitly, use `/opencfs:opencfs`.

### Claude Code: manual copy
```bash
git clone https://github.com/Ognjebog/opencfs-skill
cp -r opencfs-skill/plugins/opencfs/skills/opencfs ~/.claude/skills/
```

### Claude.ai / Claude desktop
Download `opencfs.skill` from the [releases page](https://github.com/Ognjebog/opencfs-skill/releases)
and upload it in Claude's skill settings. Running simulations requires an environment where openCFS
is installed (e.g. Claude Code or Cowork on your own machine).

### Check the installation
```bash
python ~/.claude/skills/opencfs/scripts/selftest.py
```
It should end with `SELFTEST PASSED`.

## openCFS pitfalls this skill handles

These came up during testing and may be useful even without Claude:

- **Piezo material data:** `MaterialDataBase.xml` stores the *free* permittivity ε^T for PZT-4/5A/5H and
  BaTiO₃-poled, but openCFS's stress-charge formulation needs the *clamped* ε^S. Displacements come out right,
  but capacitance comes out about 50 % too high and coupling factors too low. `piezo_material.py` adds
  corrected copies (`PZT-5A_epsS`). PZT-5H's tensor is inconsistent and must be entered by hand.
- **Piezo charge:** `elecCharge` stored under `<electrostatic>` only holds ε·E. The true electrode charge
  comes from `<piezoDirect><storeResults>`.
- **2D magnetics:** `<ground>` on the outer boundary validates but doesn't constrain the vector
  potential. The result is a near-singular system with plausible-looking but wrong fields. Use
  `<fluxParallel><comp dof="z"/></fluxParallel>`.
- `<windingTurns>` validates but isn't implemented. Use `<wireCrossSection>`.
- An XML comment before `<cfsSimulation>` aborts the run with "document root has 2 children".
- Gmsh physical groups must not be empty. Use msh 2.2 ASCII.

## Repository layout

```
.claude-plugin/marketplace.json        marketplace definition
plugins/opencfs/.claude-plugin/plugin.json
plugins/opencfs/skills/opencfs/        the skill (copy this folder for a manual install)
├── SKILL.md
├── assets/templates/                  tested XML templates + mesh scripts
├── references/                        loaded by Claude on demand
└── scripts/                           helper CLIs / library
```

## Contributing

Issues and pull requests are welcome, especially new tested templates (with an analytic check added
to `selftest.py`) and reports from other openCFS versions or Linux. Run `selftest.py` before submitting.
To build the `.skill` package, zip the `plugins/opencfs/skills/opencfs/` folder.

## License and disclaimer

MIT, see [LICENSE](LICENSE). This is an independent community project, not affiliated with or endorsed by the
openCFS developers. openCFS itself and its material database are distributed separately under their own terms.
Simulation results should always be checked independently before you rely on them.
