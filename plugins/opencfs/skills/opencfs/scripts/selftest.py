#!/usr/bin/env python3
"""Self-test: mesh + run every template in assets/templates and compare with analytic values.

  python selftest.py [workdir]

Use it to verify a (new) openCFS installation or after editing a template.
Needs: cfs on PATH (or CFS_EXE), python packages gmsh, h5py, numpy.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from cfs_results import CfsFile  # noqa: E402
from run_cfs import find_cfs  # noqa: E402

TPL = HERE.parent / "assets" / "templates"


def material_db(cfs):
    p = Path(cfs).resolve().parent.parent / "share" / "xml" / "CFS-Material" / "Examples" / "MaterialDataBase.xml"
    if not p.exists():
        sys.exit(f"material database not found at {p}")
    return p


def main():
    work = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="cfs_selftest_"))
    work.mkdir(parents=True, exist_ok=True)
    cfs = find_cfs()
    shutil.copy(material_db(cfs), work / "mat.xml")
    subprocess.run([sys.executable, str(HERE / "piezo_material.py"), str(work / "mat.xml"), "PZT-5A"], check=True,
                   capture_output=True)
    for f in TPL.glob("*.xml"):
        shutil.copy(f, work / f.name)
    print("work dir:", work)
    r = subprocess.run([sys.executable, str(TPL / "meshes_example.py"), str(HERE)], cwd=work, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        sys.exit("meshing failed")

    runs = {"mech_static_2d": "beam", "mech_eigen_2d": "beam", "heat_static_transient_2d": "heat",
            "acoustic_harmonic_2d": "duct", "electrostatic_2d": "cap", "magnetic_static_2d": "mag",
            "piezo_static_3d": "pz", "mech_acoustic_harmonic_2d": "ma"}
    ok = True
    for xml in runs:
        p = subprocess.run([cfs, "-q", "-p", f"{xml}.xml", xml], cwd=work, capture_output=True, text=True)
        status = "ok" if p.returncode == 0 else "FAILED"
        print(f"{xml:28s} run {status}")
        if p.returncode:
            ok = False
            out = p.stdout + p.stderr
            print(out[out.find("Error"):][:800])

    def res(job):
        return CfsFile(work / "results_hdf5" / f"{job}.cfs")

    checks = []
    try:
        u = res("mech_static_2d").get("mechDisplacement", "beam")
        checks.append(("mech static u_x tip", np.abs(u[:, 0]).max(), 1e6 / 2e11, 0.02))
        f1 = res("mech_eigen_2d").steps()[0][1]
        checks.append(("mech eigen f1 [Hz]", f1, 1.875**2 / (2 * np.pi) * np.sqrt(2e11 * 0.1**2 / 12 / 7872), 0.02))
        sv, q = res("heat_static_transient_2d").region_result("heatFlux", "cold")
        k = 401.0 if True else None  # Copper in the DB; analytic 1D series resistance
        checks.append(("heat flux [W/m]", abs(np.real(q).ravel()[0]), 80 / (0.1 / k + 1 / 25) * 0.1, 0.01))
        p = res("acoustic_harmonic_2d").get("acouPressure", "air")
        checks.append(("acoustic |p| [Pa]", np.abs(p).mean(), 1.204 * np.sqrt(1.41855e5 / 1.204) * 1e-3, 0.01))
        sv, w = res("electrostatic_2d").region_result("elecEnergy", "gap")
        checks.append(("elec energy [J/m]", float(np.real(w).ravel()[0]), 0.5 * 8.859e-12 * (100 / .01) ** 2 * 0.1 * 0.01, 0.01))
        rm = res("magnetic_static_2d")
        A = rm.get("magPotential", "air")
        checks.append(("mag A on boundary ~0 (|A|min)", float(np.abs(A).min()), 0.0, None))
        u = res("piezo_static_3d").get("mechDisplacement", "pzt")
        checks.append(("piezo |u_z| [m]", np.abs(u[:, 2]).max(), 374e-12 * 100, 0.05))
        sv, q = res("piezo_static_3d").region_result("elecCharge", "top")
        checks.append(("piezo charge [C] (eps33T*A*V/t)", abs(float(np.real(q).ravel()[0])), 1.505e-8 * 1e-6 * 100 / 1e-3, 0.02))
        pm = res("mech_acoustic_harmonic_2d").get("acouPressure", "air")
        checks.append(("vibroacoustic |p|>0", float(np.abs(pm).max()), None, None))
    except Exception as e:  # noqa: BLE001
        ok = False
        print("result check error:", e)

    print("\n%-32s %14s %14s  %s" % ("check", "openCFS", "expected", "ok"))
    for name, got, exp, tol in checks:
        if exp is None:
            good = got > 0
        elif tol is None:
            good = abs(got - exp) < 1e-9
        else:
            good = abs(got - exp) <= tol * abs(exp)
        ok &= bool(good)
        print("%-32s %14.6g %14s  %s" % (name, got, "-" if exp is None else f"{exp:.6g}", "OK" if good else "MISMATCH"))
    print("\nSELFTEST", "PASSED" if ok else "FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
