#!/usr/bin/env python3
"""Add a permittivity-corrected copy of a piezo material to an openCFS material file.

Why: openCFS uses the stress-charge (e-form) piezo law  T = c^E S - e^T E,  D = e S + eps^S E,
so <electric><permittivity> must be the CLAMPED permittivity eps^S. The bundled
MaterialDataBase.xml stores the datasheet FREE permittivity eps^T for PZT-4, PZT-5A, PZT-5H and
BariumTitanatePoled (1300/1700/3400/1700 eps0). Used as-is, capacitance, charge, admittance
and coupling factors come out wrong (e.g. PZT-5A: free capacitance +51 %, k_eff too low), while
displacements (d = e s^E) are right.

Fix: eps^S = eps^T - d e^T  with d = e (c^E)^-1.

Usage:
  python piezo_material.py mat.xml PZT-5A [PZT-4 ...]      -> appends "PZT-5A_epsS" etc. to mat.xml
  python piezo_material.py mat.xml --check                 -> prints eps33 (DB) vs model eps33^T for all piezo materials
"""
import copy
import sys
import xml.etree.ElementTree as ET

import numpy as np

NS = "http://www.cfs++.org/material"
ET.register_namespace("", NS)
n = lambda t: f"{{{NS}}}{t}"
E0 = 8.854187817e-12


def tensor(el):
    t = el.find(f".//{n('tensor')}")
    vals = np.array([float(x) for x in t.find(n("real")).text.split()])
    return vals.reshape(int(t.get("dim1")), int(t.get("dim2"))), t


def analyse(mat):
    C, _ = tensor(mat.find(f"{n('mechanical')}/{n('elasticity')}"))
    e, _ = tensor(mat.find(n("piezo")))
    P, pt = tensor(mat.find(f"{n('electric')}/{n('permittivity')}"))
    d = e @ np.linalg.inv(C)
    return C, e, P, pt, d


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    path = argv[1]
    tree = ET.parse(path)
    root = tree.getroot()
    mats = {m.get("name"): m for m in root.iter(n("material"))}
    if argv[2] == "--check":
        for name, m in mats.items():
            if m.find(n("piezo")) is None:
                continue
            try:
                C, e, P, pt, d = analyse(m)
            except Exception:
                continue
            epsT = P + d @ e.T
            print(f"{name:22s} eps33(file)={P[2,2]/E0:7.0f} eps0   model eps33^T={epsT[2,2]/E0:7.0f} eps0   d33={d[2,2]*1e12:5.0f} pC/N")
        return
    for name in argv[2:]:
        if name not in mats:
            sys.exit(f"material '{name}' not in {path}")
        C, e, P, pt, d = analyse(mats[name])
        epsS = P - d @ e.T  # treat the file value as eps^T
        if np.any(np.linalg.eigvalsh(0.5 * (epsS + epsS.T)) <= 0):
            print(f"SKIPPED {name}: eps^T - d e^T is not positive definite, so the file data is inconsistent "
                  f"(known for PZT-5H). Write that material by hand with datasheet eps^S values "
                  f"(PZT-5H: eps11^S = 1700 eps0, eps33^S = 1470 eps0).")
            continue
        new = copy.deepcopy(mats[name])
        new.set("name", name + "_epsS")
        _, nt = tensor(new.find(f"{n('electric')}/{n('permittivity')}"))
        nt.find(n("real")).text = " " + " ".join(f"{x:.6e}" for x in epsS.ravel()) + " "
        if (name + "_epsS") in mats:
            root.remove(mats[name + "_epsS"])
        root.append(new)
        print(f"added {name}_epsS: eps33^S = {epsS[2,2]/E0:.0f} eps0 (was {P[2,2]/E0:.0f}), eps11^S = {epsS[0,0]/E0:.0f} eps0")
    tree.write(path, xml_declaration=True, encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv)
