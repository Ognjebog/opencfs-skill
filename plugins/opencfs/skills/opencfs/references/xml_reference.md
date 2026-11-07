# openCFS XML reference (v25.07)

Read the matching template in `assets/templates/` first — those are tested end to end.
This file covers structure and the options that the templates don't show. For anything
not listed, ask the schema: `python scripts/schema_lookup.py show <pde>/bcsAndLoads`.

## Contents
1. File skeleton
2. fileFormats: mesh input, output, materials
3. domain: regions, named nodes, coordinate systems
4. Analysis types
5. PDE quick reference (BCs, loads, results)
6. Couplings and multi-step workflows
7. Damping, PML, absorbing boundaries
8. Math expressions (space/time/frequency-dependent values)
9. Results at points: nodeList, sensorArray, text output
10. Material file

---

## 1. File skeleton

```xml
<?xml version="1.0"?>
<cfsSimulation xmlns="http://www.cfs++.org/simulation">
  <!-- comments go INSIDE the root; a comment before it makes cfs abort -->
  <fileFormats> input / output / materialData </fileFormats>
  <domain geometryType="plane|axi|3d"> regionList, surfRegionList?, nodeList? </domain>
  <sequenceStep index="1">
    <analysis> static | transient | harmonic | eigenFrequency | multiharmonic | buckling | ... </analysis>
    <pdeList> one or more PDEs </pdeList>
    <couplingList> optional direct/iterative coupling </couplingList>
    <linearSystems> optional solver settings </linearSystems>
  </sequenceStep>
  <sequenceStep index="2"> ... optional, can use results of step 1 ... </sequenceStep>
</cfsSimulation>
```

* Element order inside each block follows the schema `xsd:sequence`. Use the order shown here.
* `xsi:schemaLocation` is optional. cfs validates against `<install>/share/xml` anyway.
* Every name (`region`, `surfRegion`, BC `name=`) must be a Gmsh physical group or a name that
  the XML itself defines (`nodes`, `elems`, generated layers).

## 2. fileFormats

```xml
<fileFormats>
  <input>
    <gmsh fileName="model.msh" scaleFac="1e-3"/>   <!-- scaleFac: mm -> m -->
    <!-- also: <cdb fileName="x.cdb"/> (ANSYS/Cubit), <hdf5 fileName="x.cfs"/>, <mphtxt .../> (COMSOL) -->
    <!-- several meshes need an id="..." each -->
  </input>
  <output>
    <hdf5/>              <!-- results_hdf5/<job>.cfs  (ParaView CFSReader / h5py) -->
    <text id="txt"/>     <!-- history/*.hist text files for region/surfRegion/node-list results -->
  </output>
  <materialData file="mat.xml" format="xml"/>
</fileFormats>
```

Gmsh: physical groups name the regions. Use the legacy **msh 2.2 ASCII** format (`cfs_mesh.py` writes it).
The volume regions (dim 2 in 2D, dim 3 in 3D) carry materials. Lower-dimensional groups carry BCs.

## 3. domain

```xml
<domain geometryType="plane">          <!-- plane (2D), axi (2D axisymmetric, x=r, y=z), 3d -->
  <regionList>
    <region name="beam" material="Steel"/>
    <region name="pzt" material="PZT-5A"><matRotation alpha="0" beta="90" gamma="0"/></region>
  </regionList>
  <surfRegionList><surfRegion name="iface"/></surfRegionList>   <!-- optional -->
  <nodeList>
    <nodes name="probe"><coord x="0.5" y="0.05" z="0"/></nodes>  <!-- nearest node -->
  </nodeList>
</domain>
```

`geometryType` must match the PDE `subType` (mechanics: `planeStrain|planeStress|axi|3d|2.5d`).

## 4. Analysis types

```xml
<static/>
<transient><numSteps>100</numSteps><deltaT>1e-3</deltaT></transient>
<harmonic><numFreq>50</numFreq><startFreq>10</startFreq><stopFreq>2000</stopFreq>
          <sampling>linear</sampling></harmonic>                      <!-- or log -->
<harmonic><frequencyList><freq value="100"/><freq value="250"/></frequencyList></harmonic>
<eigenFrequency><isQuadratic>no</isQuadratic><numModes>10</numModes>
                <freqShift>0</freqShift><writeModes>yes</writeModes></eigenFrequency>
```

* Harmonic and eigen results are complex. In HDF5 they're always stored as `Real` + `Imag`.
* Eigenfrequency: each mode is one step, and its step value is the frequency in Hz.
  `isQuadratic=yes` is needed for damped or gyroscopic problems.
* Transient time step: resolve the highest frequency of interest (≥ 20 steps per period). For heat,
  pick Δt small compared with the diffusion time L²·ρc/k.

## 5. PDE quick reference

| PDE element | material class | typical BCs / loads | node results | element / region results |
|---|---|---|---|---|
| `<mechanic subType=...>` | `mechanical` | `fix`(comp dof), `displacement`, `force`, `pressure`, `forceDensity`, `thermalStrain`, `normalStiffness` | mechDisplacement, mechVelocity, mechAcceleration | mechStress, mechStrain, vonMisesStress / mechDeformEnergy, mechKinEnergy |
| `<acoustic formulation="acouPressure">` | `acoustic` | `pressure`, `normalVelocity`, `normalAcceleration`, `soundSoft`, `impedance`, `absorbingBCs`, `rhsDensity` | acouPressure | acouVelocity, acouIntensity / acouPower(surf), acouEnergy |
| `<electrostatic>` | `electric` | `ground`, `potential`, `charge`, `chargeDensity` | elecPotential | elecFieldIntensity, elecEnergyDensity / elecEnergy, elecCharge(surf) |
| `<heatConduction>` | `heatConduction` | `temperature`, `heatFlux`, `heatSource`, `heatSourceDensity`, `heatTransport`(h, T∞) | heatTemperature | heatFluxDensity / heatFlux(surf) |
| `<magnetic>` (2D nodal) | `magnetic` | `fluxParallel`(+comp), `potential`, `coilList` | magPotential | magFluxDensity, magFieldIntensity, magEddyCurrentDensity / magEnergy, magJouleLossPower |
| `<magneticEdge>` (3D) | `magnetic` | `fluxParallel`, `coilList` | – | magFluxDensity, magPotential(elem) ... |
| `<elecConduction>` | `elecConduction` | `potential`, `ground`, `normalCurrentDensity` | elecPotential | elecCurrentDensity, elecPowerDensity |

Get the exact list for your version from the schema:
`python scripts/schema_lookup.py results <pde>` and `... show <pde>/bcsAndLoads[/<bc>]`.

BC syntax patterns:
```xml
<fix name="edge"><comp dof="x"/><comp dof="y"/></fix>                 <!-- dofs: x y z (r z for axi) -->
<displacement name="edge"><comp dof="y" value="1e-3"/></displacement>
<force name="pt"><comp dof="y" value="-100"/></force>
<pressure name="edge" value="1e6"/>                                   <!-- + = pushes into body -->
<pressure name="end" value="-50e6"/>                                  <!-- TENSION: negative pressure pulls (tested) -->
<fix name="symX"><comp dof="x"/></fix>                                <!-- symmetry plane x = const: fix the normal dof only -->
<normalVelocity name="inlet" volumeRegion="air" value="1e-3"/>        <!-- surface BCs that need the adjacent volume take volumeRegion -->
<heatTransport name="edge" volumeRegion="plate" heatTransferCoefficient="25" bulkTemperature="20"/>
<potential name="top" value="100"/>   <ground name="bottom"/>
```
Values can be expressions: `value="1e3*sin(2*pi*50*t)"`, `value="100*(x>0.5)"` (see §8).
For harmonic analysis you can add `phase="90"` (degrees).

storeResults pattern:
```xml
<storeResults>
  <nodeResult type="mechDisplacement"><allRegions/></nodeResult>
  <elemResult type="mechStress"><regionList><region name="beam"/></regionList></elemResult>
  <regionResult type="mechDeformEnergy"><allRegions/></regionResult>
  <surfRegionResult type="heatFlux"><surfRegionList><surfRegion name="cold"/></surfRegionList></surfRegionResult>
  <nodeResult type="mechDisplacement"><allRegions/>
     <nodeList><nodes name="probe" outputIds="txt"/></nodeList></nodeResult>   <!-- point history -->
</storeResults>
```

## 6. Couplings and multi-step workflows

Direct (monolithic) coupling: put both PDEs in one `pdeList` and add
```xml
<couplingList><direct>
  <piezoDirect><regionList><region name="pzt"/></regionList></piezoDirect>          <!-- mech + electrostatic -->
  <acouMechDirect><surfRegionList><surfRegion name="iface"/></surfRegionList></acouMechDirect>  <!-- mech + acoustic -->
</direct></couplingList>
```
Couplings have their own `<storeResults>` for coupled quantities. For piezo, the electrode charge
(full D = e·S + ε·E) must be stored there, NOT under `<electrostatic>`:
```xml
<piezoDirect><regionList><region name="pzt"/></regionList>
  <storeResults><surfRegionResult type="elecCharge"><surfRegionList><surfRegion name="top"/></surfRegionList></surfRegionResult></storeResults>
</piezoDirect>
```
List what a coupling can store with `schema_lookup.py results direct/piezoDirect`.
Other direct couplings in 25.07: thermoMechDirect, thermoElectricDirect, magnetoStrictDirect,
linFlowAcouDirect, linFlowMechDirect, linFlowHeatDirect, waterWaveAcouDirect, waterWaveMechDirect.
Coupled regions must share nodes. In Gmsh, use `fragment`.

Sequential (one-way) coupling, e.g. a thermal-stress pipeline: solve heat in step 1, then read
the temperature in step 2:
```xml
<sequenceStep index="2"><analysis><static/></analysis><pdeList>
  <mechanic subType="planeStress">
    <regionList><region name="beam"/></regionList>
    <bcsAndLoads>
      <fix name="fix"><comp dof="x"/><comp dof="y"/></fix>
      <thermalStrain name="beam">
        <sequenceStep index="1">
          <quantity name="heatTemperature" pdeName="heatConduction"/>
          <timeFreqMapping><constant step="1"/></timeFreqMapping>
        </sequenceStep>
      </thermalStrain>
    </bcsAndLoads>
    <storeResults><elemResult type="mechThermalStress"><allRegions/></elemResult></storeResults>
  </mechanic></pdeList></sequenceStep>
```
The material's `<mechanical>` block then needs
`<thermalExpansion><isotropic><real>22e-6</real></isotropic><refTemperature><real>20</real></refTemperature></thermalExpansion>`.
Some docs pages misspell it `thermalExpanison`. Confirm with
`schema_lookup.py grep thermalExpan --material`.
Induction heating (magnetic → heat) uses the same pattern with `heatSourceDensity` fed by `magJouleLossPowerDensity`.
These sequential recipes come from the docs and weren't run in the tests here. Run them once and
sanity-check the result before trusting it.

## 7. Damping, PML, absorbing boundaries

Rayleigh damping (mechanics/acoustics), set per region:
```xml
<regionList><region name="solid" dampingId="ray"/></regionList>
<dampingList><rayleigh id="ray"/></dampingList>
<!-- material, inside <mechanical>: -->
<damping><rayleigh><coefficients><alpha>30</alpha><beta>2e-5</beta></coefficients></rayleigh></damping>
<!-- or loss factor at a frequency: -->
<damping><rayleigh><computeFromTanDeltaAtFrequency><centerFreq>100</centerFreq>
  <ratioDeltaF>0.1</ratioDeltaF><lossTangensDelta>0.01</lossTangensDelta></computeFromTanDeltaAtFrequency></rayleigh></damping>
```
Acoustic free field. The simplest option is `<absorbingBCs name="outer" volumeRegion="air"/>` (first-order,
best at normal incidence). For better accuracy use a PML layer region:
```xml
<regionList><region name="air"/><region name="pml" dampingId="myPml"/></regionList>
<dampingList><pml id="myPml"><type>inverseDist</type><dampFactor>1.0</dampFactor></pml></dampingList>
```
The PML region is meshed as its own layer (≥ 4–6 elements thick) around the domain, and its
material is the same fluid.

## 8. Math expressions

Any `value=` accepts muParser expressions with the variables `x y z` (coordinates), `t` (time), `f`
(frequency) and `dt`, the functions `sin cos exp sqrt abs ...`, conditionals
`(t lt 1e-3) ? 1 : 0`, and constants `pi`. Tabulated data: `sample1D('file.txt', f, 1)`.
Define reusable variables in `<domain><variableList><var name="L" value="0.5"/></variableList>`.

## 9. Results at specific points

* `nodeList` / `<nodes name=...>` in `<domain>`, then `<nodeList><nodes name="..." outputIds="txt"/></nodeList>`
  inside a nodeResult. This writes `history/<job>-<quantity>-node-<id>-<name>.hist`.
* Line probes: `<sensorArray type="acouPressure" fileName="line"><parametric><list comp="x" start="0" stop="1" inc="0.01"/>
  <list comp="y" start="0.05" stop="0.05" inc="0"/></parametric></sensorArray>` inside storeResults.
* Simplest approach: store the field in HDF5 and pick values in Python (`cfs_results.py export`).

## 10. Material file

The database bundled with the install, `<install>/share/xml/CFS-Material/Examples/MaterialDataBase.xml`, covers:
Air, Aluminium, Copper, Steel, Iron/iron, Silicon, Water, Glass, Lead, Gold, Silver, PZT-4, PZT-5A, PZT-5H,
BariumTitanate, AlN, PVDF, LithiumNiobate, Polyethylene, Plexiglas, Vacuum, … Names are
case-sensitive. A material can only be used in a PDE if it has that PDE's class block
(`mechanical`, `acoustic`, `electric`, `heatConduction`, `magnetic`, `piezo`).

Custom material (copy the DB and append, or write a small file):
```xml
<?xml version="1.0"?>
<cfsMaterialDataBase xmlns="http://www.cfs++.org/material">
  <material name="myAlu">
    <mechanical>
      <density><linear><real>2700</real></linear></density>
      <elasticity><linear><isotropic>
        <elasticityModulus><real>70e9</real></elasticityModulus>
        <poissonNumber><real>0.33</real></poissonNumber>
      </isotropic></linear></elasticity>
    </mechanical>
    <heatConduction>
      <density><linear><real>2700</real></linear></density>
      <heatCapacity><linear><real>900</real></linear></heatCapacity>
      <heatConductivity><linear><isotropic><real>237</real></isotropic></linear></heatConductivity>
    </heatConduction>
    <acoustic>   <!-- fluids: density + compressionModulus K = rho*c^2 -->
      <density><linear><real>1.204</real></linear></density>
      <compressionModulus><linear><real>1.41855e5</real></linear></compressionModulus>
    </acoustic>
    <electric><permittivity><linear><isotropic><real>8.854e-12</real></isotropic></linear></permittivity></electric>
    <magnetic>
      <electricConductivity><linear><isotropic><real>0</real></isotropic></linear></electricConductivity>
      <permeability><linear><isotropic><real>1.2566e-6</real></isotropic></linear></permeability>
    </magnetic>
  </material>
</cfsMaterialDataBase>
```
Anisotropic elasticity: `<linear><tensor dim1="6" dim2="6"><real> 36 values </real></tensor></linear>`
(Voigt order xx yy zz yz xz xy). Look up other options with `schema_lookup.py show --material <class>`.
