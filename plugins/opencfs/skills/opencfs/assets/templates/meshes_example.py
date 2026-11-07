"""TESTED mesh scripts for every template in this folder (gmsh python API via cfs_mesh.py).

Run:  python meshes_example.py <skill_dir>/scripts   (or put scripts/ on sys.path yourself)
Writes beam.msh, heat.msh, duct.msh, cap.msh, mag.msh, pz.msh, ma.msh in the current folder.
Copy the block you need into a per-model mesh.py and adapt geometry/sizes/names.
"""
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parents[2] / "scripts"))
from cfs_mesh import Mesh, msh_regions  # noqa: E402

# 2D cantilever 1 m x 0.1 m  -> mech_static_2d.xml, mech_eigen_2d.xml
m = Mesh("beam"); s = m.occ.addRectangle(0, 0, 0, 1.0, 0.1); m.sync()
m.group(2, [s], "beam"); m.group(1, m.in_box(1, xmax=0), "fix"); m.group(1, m.in_box(1, xmin=1.0), "tip")
m.write("beam.msh", size=0.02, quads=True)

# heat plate 0.1 x 0.1  -> heat_static_transient_2d.xml
m = Mesh("heat"); s = m.occ.addRectangle(0, 0, 0, .1, .1); m.sync()
m.group(2, [s], "plate"); m.group(1, m.in_box(1, xmax=0), "hot"); m.group(1, m.in_box(1, xmin=.1), "cold")
m.write("heat.msh", size=.005, quads=True)

# acoustic duct 1 x 0.1  -> acoustic_harmonic_2d.xml
m = Mesh("duct"); s = m.occ.addRectangle(0, 0, 0, 1, .1); m.sync()
m.group(2, [s], "air"); m.group(1, m.in_box(1, xmax=0), "inlet"); m.group(1, m.in_box(1, xmin=1), "outlet")
m.write("duct.msh", size=.01, quads=True)

# capacitor gap  -> electrostatic_2d.xml
m = Mesh("cap"); s = m.occ.addRectangle(0, 0, 0, .1, .01); m.sync()
m.group(2, [s], "gap"); m.group(1, m.in_box(1, ymax=0), "bottom"); m.group(1, m.in_box(1, ymin=.01), "top")
m.write("cap.msh", size=.001, quads=True)

# coil in air box (two regions -> fragment for a conforming mesh)  -> magnetic_static_2d.xml
m = Mesh("mag"); m.occ.addRectangle(-.1, -.1, 0, .2, .2); m.occ.addRectangle(-.01, -.01, 0, .02, .02); m.fragment()
coil = m.in_box(2, -.01, .01, -.01, .01); air = [t for t in m.all(2) if t not in coil]
m.group(2, coil, "coil"); m.group(2, air, "air")
m.group(1, m.in_box(1, xmax=-.1) + m.in_box(1, xmin=.1) + m.in_box(1, ymax=-.1) + m.in_box(1, ymin=.1), "outer")
m.write("mag.msh", size=.004)

# 3D piezo cube 1 mm, structured hexahedra  -> piezo_static_3d.xml
m = Mesh("pz"); v = m.occ.addBox(0, 0, 0, 1e-3, 1e-3, 1e-3); m.sync()
m.group(3, [v], "pzt"); m.group(2, m.in_box(2, zmax=0), "bottom"); m.group(2, m.in_box(2, zmin=1e-3), "top")
m.write("pz.msh", size=2.5e-4, transfinite=True, quads=True)

# plate + air, shared interface  -> mech_acoustic_harmonic_2d.xml
m = Mesh("ma"); m.occ.addRectangle(0, 0, 0, 1, .01); m.occ.addRectangle(0, .01, 0, 1, .49); m.fragment()
m.group(2, m.in_box(2, ymax=.01), "plate"); m.group(2, m.in_box(2, ymin=.01), "air")
m.group(1, m.in_box(1, xmax=0, ymax=.01) + m.in_box(1, xmin=1, ymax=.01), "clamp")
m.group(1, m.in_box(1, ymin=.01, ymax=.01), "iface"); m.group(1, m.in_box(1, ymax=0), "plate_bottom")
m.group(1, m.in_box(1, ymin=.5), "far")
m.write("ma.msh", size=.01, quads=True)

for f in ["beam", "heat", "duct", "cap", "mag", "pz", "ma"]:
    print(f, msh_regions(f + ".msh"))
