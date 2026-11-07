#!/usr/bin/env python3
"""Pre-flight check + run an openCFS simulation, then summarise the outcome.

Usage:
  python run_cfs.py <sim.xml> [jobname] [--threads N] [--check-only] [--mesh FILE]

What it does
  1. Locates cfs(.exe): $CFS_EXE, PATH, or common install folders (C:/Tools/OpenCFS/*, /opt/openCFS*, ~/openCFS*).
  2. Pre-flight (fast, catches the most common mistakes before cfs runs):
     - XML well-formed, root <cfsSimulation xmlns="http://www.cfs++.org/simulation">
     - every mesh file exists; Gmsh files are msh 2.x ASCII and every physical group has elements
     - every region/surfRegion/BC 'name' used in the XML exists in the mesh
     - every material referenced in <domain> exists in the material file
  3. Runs `cfs -p <sim.xml> <jobname>` in the XML's folder (log -> <jobname>.log).
  4. Reports status from <jobname>.info.xml, wall time, the error block (if any),
     produced files (results_hdf5/<job>.cfs, history/*.hist) and a short summary
     of the .hist files.

Exit code = cfs exit code (or 2 if pre-flight failed).
"""
import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).parent))
NS = "{http://www.cfs++.org/simulation}"
MNS = "{http://www.cfs++.org/material}"


def winpath(p):
    """Accept Git-Bash/MSYS style paths (/c/Users/...) on Windows."""
    import os, re
    if p and os.name == "nt":
        m = re.match(r"^/([a-zA-Z])(/.*)?$", str(p))
        if m:
            return f"{m.group(1).upper()}:{(m.group(2) or '/')}"
    return p


def find_cfs():
    for c in (os.environ.get("CFS_EXE"), shutil.which("cfs"), shutil.which("cfs.exe")):
        if c and Path(c).exists():
            return str(Path(c))
    hits = []
    for pat in ("C:/Tools/OpenCFS/*/bin/cfs.exe", "C:/Program Files/openCFS*/bin/cfs.exe",
                "/opt/openCFS*/bin/cfs", "/opt/CFS*/bin/cfs", str(Path.home() / "openCFS*/bin/cfs"),
                str(Path.home() / "CFS*/bin/cfs")):
        hits += sorted(glob.glob(pat), reverse=True)
    if hits:
        return hits[0]
    sys.exit("cfs executable not found. Set CFS_EXE or add <install>/bin to PATH.")


def preflight(xml_path, mesh_override=None):
    problems, warnings = [], []
    base = xml_path.parent
    raw = xml_path.read_text(errors="replace")
    head = re.sub(r"^\s*<\?xml[^>]*\?>", "", raw).lstrip()
    if head.startswith("<!--"):
        problems.append("a comment precedes the root element - cfs aborts with 'document root has 2 children'; "
                        "move the comment inside <cfsSimulation>")
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError as e:
        return [f"XML not well-formed: {e}"], warnings, {}
    if root.tag != NS + "cfsSimulation":
        problems.append(f"root element is {root.tag}; expected <cfsSimulation xmlns=\"http://www.cfs++.org/simulation\">")
        return problems, warnings, {}

    # ---- meshes
    mesh_regions = {}
    inputs = root.find(f"{NS}fileFormats/{NS}input")
    files = []
    if mesh_override:
        files.append(("cmdline", Path(mesh_override)))
    elif inputs is not None:
        for inp in inputs:
            fn = inp.get("fileName")
            if fn:
                files.append((inp.tag.replace(NS, ""), base / fn))
    for kind, fp in files:
        if not fp.exists():
            problems.append(f"mesh file not found: {fp}")
            continue
        if kind == "gmsh" or fp.suffix.lower() in (".msh", ".msh2"):
            try:
                from cfs_mesh import msh_regions
                regs = msh_regions(fp)
            except ValueError as e:
                problems.append(str(e))
                continue
            except Exception as e:  # binary msh etc.
                warnings.append(f"could not parse {fp.name} ({e}); is it msh 2.2 ASCII?")
                continue
            for nm, (d, n) in regs.items():
                if n == 0:
                    problems.append(f"physical group '{nm}' in {fp.name} has no elements")
            mesh_regions.update({k: v[0] for k, v in regs.items()})
        elif fp.suffix.lower() in (".cfs", ".h5", ".hdf5"):
            try:
                import h5py
                with h5py.File(fp, "r") as f:
                    for k, g in f["Mesh/Regions"].items():
                        mesh_regions[k] = int(g.attrs.get("Dimension", 0))
                    for k in f.get("Mesh/Groups", {}):
                        mesh_regions[k] = -1
            except Exception as e:
                warnings.append(f"could not read regions from {fp.name}: {e}")

    # names defined in the XML itself (nodes/elems lists, generated layers)
    xml_defined = {e.get("name") for tag in ("nodes", "elems", "newRegion") for e in root.iter(NS + tag) if e.get("name")}

    # ---- region / BC names used
    used = set()
    domain = root.find(NS + "domain")
    for r in root.iter(NS + "region"):
        if r.get("name"):
            used.add(r.get("name"))
    for r in root.iter(NS + "surfRegion"):
        if r.get("name"):
            used.add(r.get("name"))
    seq_tags = {"sequenceStep"}
    for ss in root.iter(NS + "bcsAndLoads"):
        for bc in ss:
            n = bc.get("name")
            if n and bc.tag.replace(NS, "") not in seq_tags:
                used.add(n)
            vr = bc.get("volumeRegion")
            if vr:
                used.add(vr)
    if mesh_regions:
        missing = sorted(n for n in used if n not in mesh_regions and n not in xml_defined)
        if missing:
            problems.append("names used in XML but not in mesh: " + ", ".join(missing)
                            + "\n      mesh has: " + ", ".join(f"{k}(dim{v})" for k, v in sorted(mesh_regions.items())))

    # ---- materials
    mat_el = root.find(f"{NS}fileFormats/{NS}materialData")
    mats_needed = {}
    if domain is not None:
        for r in domain.iter(NS + "region"):
            if r.get("material"):
                mats_needed[r.get("name")] = r.get("material")
    if mat_el is None and mats_needed:
        problems.append("no <materialData file=... format=\"xml\"/> in <fileFormats>")
    elif mat_el is not None:
        mf = base / mat_el.get("file", "")
        if not mf.exists():
            problems.append(f"material file not found: {mf}")
        else:
            try:
                mroot = ET.parse(mf).getroot()
                avail = {m.get("name"): {c.tag.replace(MNS, "") for c in m} for m in mroot.iter(MNS + "material")}
                if not avail:
                    problems.append(f"{mf.name}: no <material> found (namespace must be http://www.cfs++.org/material)")
                for reg, mat in mats_needed.items():
                    if mat not in avail:
                        close = [a for a in avail if a.lower() == mat.lower()]
                        hint = f" (did you mean '{close[0]}'? names are case-sensitive)" if close else ""
                        problems.append(f"material '{mat}' (region {reg}) not in {mf.name}{hint}")
                # material class check per PDE
                pde_class = {"mechanic": "mechanical", "acoustic": "acoustic", "electrostatic": "electric",
                             "heatConduction": "heatConduction", "magnetic": "magnetic", "magneticEdge": "magnetic",
                             "elecConduction": "elecConduction"}
                for pl in root.iter(NS + "pdeList"):
                    for pde in pl:
                        cls = pde_class.get(pde.tag.replace(NS, ""))
                        if not cls:
                            continue
                        for r in pde.iter(NS + "region"):
                            mat = mats_needed.get(r.get("name"))
                            if mat in avail and cls not in avail[mat]:
                                problems.append(f"material '{mat}' has no <{cls}> block but region "
                                                f"'{r.get('name')}' is in PDE <{pde.tag.replace(NS, '')}> (has: {sorted(avail[mat])})")
            except ET.ParseError as e:
                problems.append(f"material file not well-formed: {e}")
    return problems, warnings, mesh_regions


def summarize_hist(folder, job):
    out = []
    for h in sorted((folder / "history").glob(f"{job}-*.hist")):
        rows = [l.split() for l in h.read_text(errors="replace").splitlines() if l.strip() and not l.startswith("#")]
        if not rows:
            continue
        hdr = [l for l in h.read_text(errors="replace").splitlines() if l.startswith("# t") or l.startswith("# f")]
        last = rows[-1]
        nblocks = sum(1 for l in h.read_text(errors="replace").splitlines() if l.startswith("# Result:"))
        dup = f"  [{nblocks} result blocks - same quantity stored by 2 PDEs/couplings; values differ!]" if nblocks > 1 else ""
        out.append(f"  {h.name}: {len(rows)} rows; last = {' '.join(last[:6])}  {hdr[0][1:].strip() if hdr else ''}{dup}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xml")
    ap.add_argument("job", nargs="?")
    ap.add_argument("--threads", "-t", type=int, default=max(1, min(8, (os.cpu_count() or 2) // 2)))
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--mesh", "-m")
    ap.add_argument("--timeout", type=float, default=None, help="seconds")
    a = ap.parse_args()
    a.xml, a.mesh = winpath(a.xml), winpath(a.mesh)

    xml = Path(a.xml).resolve()
    job = a.job or xml.stem
    problems, warnings, regs = preflight(xml, a.mesh)
    for w in warnings:
        print("WARNING:", w)
    if problems:
        print("PRE-FLIGHT FAILED:")
        for p in problems:
            print("  -", p)
        sys.exit(2)
    print(f"pre-flight OK ({len(regs)} mesh regions/groups found)")
    if a.check_only:
        return

    cfs = find_cfs()
    cmd = [cfs, "-t", str(a.threads), "-p", xml.name]
    if a.mesh:
        cmd += ["-m", a.mesh]
    cmd.append(job)
    print("running:", " ".join(cmd), " (cwd:", xml.parent, ")")
    t0 = time.time()
    log = xml.parent / f"{job}.log"
    with open(log, "w", encoding="utf-8", errors="replace") as lf:
        try:
            rc = subprocess.run(cmd, cwd=xml.parent, stdout=lf, stderr=subprocess.STDOUT, timeout=a.timeout).returncode
        except subprocess.TimeoutExpired:
            print(f"TIMEOUT after {a.timeout}s - see {log}")
            sys.exit(124)
    dt = time.time() - t0
    text = log.read_text(errors="replace")
    info = xml.parent / f"{job}.info.xml"
    status = "unknown"
    if info.exists():
        m = re.search(r'<cfsInfo status="(\w+)"', info.read_text(errors="replace")[:500])
        status = m.group(1) if m else status
    print(f"exit code {rc}, status '{status}', {dt:.1f}s; log: {log}")
    if rc != 0 or status != "finished":
        i = text.find(">> Error")
        print("---- error ----")
        print(text[i:i + 2000] if i >= 0 else text[-2000:])
    else:
        lines = text.splitlines()
        for i, l in enumerate(lines):
            if "warning" in l.lower():
                nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
                print("cfs warning:", (l.strip() + " " + nxt).replace("WARNING:", "").strip())
    res = xml.parent / "results_hdf5" / f"{job}.cfs"
    if res.exists():
        print(f"results: {res} ({res.stat().st_size/1e6:.2f} MB)")
    for line in summarize_hist(xml.parent, job):
        print(line)
    sys.exit(rc)


if __name__ == "__main__":
    main()
