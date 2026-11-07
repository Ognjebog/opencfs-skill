# Results and post-processing

## What a run produces (job name `job`, run in folder F)
| file | content |
|---|---|
| `F/results_hdf5/job.cfs` | HDF5: mesh + all `nodeResult`/`elemResult` fields + region/surfRegion results |
| `F/history/job-<quantity>-<kind>-<name>.hist` | text tables (needs `<text id=".."/>` in output) of region, surfRegion and node-list results. Static/transient: `t value(s)`. **Harmonic: `f  amplitude  phase(deg)`**, not Re/Im. Eigen: one row per mode. Several `# Result:` blocks in one file mean the quantity was stored twice (e.g. by a PDE and a coupling). |
| `F/job.info.xml` | run status (`<cfsInfo status="finished|aborted">`), timings, memory, mesh stats, solver info |
| `F/job.log` | console output (written by `run_cfs.py`) |

## HDF5 layout (verified, openCFS 25.07)
```
Mesh/Nodes/Coordinates                    (nNodes, 3)  float
Mesh/Elements/Connectivity                (nElems, maxNodes) 1-based node ids, 0 = padding
Mesh/Elements/Types                       element type codes
Mesh/Regions/<region>/Nodes               1-based global node ids of the region
Mesh/Regions/<region>/Elements            1-based global element ids  (attr Dimension)
Results/Mesh/MultiStep_<s>/               attrs AnalysisType ('static','transient','harmonic','eigenFrequency'), LastStepNum
   ResultDescription/<quantity>/          DOFNames, DefinedOn (1=nodes, 4=elements), EntityNames, StepValues, Unit
   Step_<n>/  (attr StepValue = time | frequency | eigenfrequency)
      <quantity>/<region>/Nodes/Real      (nRegionNodes, nDofs)   order = Mesh/Regions/<region>/Nodes
      <quantity>/<region>/Nodes/Imag      (harmonic / eigen only)
      <quantity>/<region>/Elements/Real   (nRegionElems, nDofs)  order = Mesh/Regions/<region>/Elements
Results/History/MultiStep_<s>/<quantity>/Regions|SurfRegions|Nodes/<name>/Real   (nSteps, nDofs)
```
* Each `sequenceStep` index i becomes `MultiStep_i`.
* Complex results always come as Real + Imag, whatever `complexFormat` says.
* Vector DOF names are `x`,`y`(,`z`), or `r`,`z` for axi. Scalars have an empty DOF name.
* The 6 stress/strain components are in Voigt order (`xx yy zz yz xz xy` in 3D, `xx yy xy` in 2D). Read `DOFNames` to be sure.

## cfs_results.py (bundled)
```bash
python scripts/cfs_results.py info   results_hdf5/job.cfs              # what is stored where
python scripts/cfs_results.py plot   results_hdf5/job.cfs heatTemperature --ms 2 --step 50 -o T.png
python scripts/cfs_results.py plot   results_hdf5/job.cfs mechDisplacement --comp y --deform 100 -o uy.png
python scripts/cfs_results.py export results_hdf5/job.cfs acouPressure --step all -o p.csv
python scripts/cfs_results.py hist   history/job-elecEnergy-region-gap.hist -o W.png
```
`plot` makes 2D contour plots. For 3D fields it plots the x-y projection, so use export or ParaView instead.
Complex fields are plotted as magnitudes.

Library use for custom analysis (FRFs, line plots, max values, comparisons):
```python
import sys; sys.path.insert(0, r"<skill>/scripts")
from cfs_results import CfsFile
import numpy as np
r = CfsFile("results_hdf5/job.cfs")
freqs = [v for _, v in r.steps(ms=1)]
# frequency response at the node closest to a point
X = r.coords("air"); i = np.argmin(np.linalg.norm(X - [0.5, 0.05, 0], axis=1))
p = np.array([r.get("acouPressure", "air", ms=1, step=s)[i, 0] for s, _ in r.steps(ms=1)])
spl = 20*np.log10(np.abs(p)/np.sqrt(2)/20e-6)    # SPL in dB re 20 uPa (|p| is a peak amplitude)
# integrated history results
sv, W = r.region_result("elecEnergy", "gap")
```
Line or profile along a path: pick the nodes within a tolerance of the line and sort them by coordinate.
If no nodes lie on the line, interpolate with `scipy.interpolate.griddata` (when SciPy is
installed), or put the line in the mesh as a physical group.

## Peak values (stress concentrations, field peaks)
Derived results (mechStress, vonMisesStress, heatFluxDensity, elecFieldIntensity, magFluxDensity) are
constant per element and stored at the centroid. At a notch, the largest element value sits about half an element
away from the true peak. In a tested plate-with-hole case with 0.5 mm elements, it read 148 MPa against 156 MPa.
1. Refine locally (`Mesh.refine`) to about 1/50 of the notch radius or finer.
2. Extrapolate to the surface. Take the elements along a line normal to the surface (e.g. a symmetry
   line), fit a quadratic to value vs. distance, and evaluate it at distance 0.
3. Show convergence. Repeat with h/2, and the extrapolated peak should change by < 1 %.
Plotting with `cfs_results.py plot` draws each element as a flat-coloured polygon, which shows the raw values honestly.

## openCFS's own python tools
`<install>/share/python/hdf5_tools.py` has `get_result(file, quantity, region, multistep, step)`
and `get_coordinates(file, region)`. `cfs_results.py` is a superset and doesn't depend on that folder.

## Visualising in ParaView
ParaView (≥5.6) reads `.cfs` directly with the CFSReader plugin. Open `results_hdf5/job.cfs` and
pick the multistep and step in the reader's properties. For harmonic results choose
amplitude/phase or real/imag. Tell the user this when they want interactive 3D views. If ParaView
isn't installed, use matplotlib plots or export CSV.

## Plausibility checks (always do at least one)
* Compare with an analytic estimate: beam deflection or frequency, ρc·v, ½CV², the 1D heat
  resistance, d33·V, and so on. A template's header shows the kind of check that fits.
* Check the primary field's range. Huge constant offsets (for example magPotential ≈ 1e7) mean the
  system lacks a Dirichlet condition.
* Symmetric problem → symmetric result.
* Mesh convergence: rerun with h/2 and compare the quantity of interest. The difference should be small.
* For wave problems: ≥ 10 linear elements per wavelength λ = c/f_max.
