#!/usr/bin/env python3
"""Inspect, extract and plot openCFS results (.cfs = HDF5) without ParaView.

CLI:
  python cfs_results.py info   results_hdf5/job.cfs
  python cfs_results.py export results_hdf5/job.cfs <quantity> [--region R] [--ms 1] [--step N|all] [-o out.csv]
  python cfs_results.py plot   results_hdf5/job.cfs <quantity> [--region R] [--ms 1] [--step N] [--comp x|y|z|mag]
                               [--deform SCALE] [--mirror x|y|xy] [-o fig.png]
  python cfs_results.py hist   history/<file>.hist [-o fig.png]

Library (import from your own analysis scripts):
  from cfs_results import CfsFile
  r = CfsFile("results_hdf5/job.cfs")
  r.summary()                                   # dict of multisteps -> analysis, steps, quantities
  vals = r.get("mechDisplacement", "beam", ms=1, step=1)   # ndarray (n, ncomp); complex if harmonic
  xyz  = r.coords("beam")                       # node coords of that region (same order as nodal results)
  xyzc = r.centroids("beam")                    # element centroids (same order as element results)
  steps = r.steps(ms=1)                         # [(step_no, step_value(time/freq/eigenfreq))]
  r.region_result("elecEnergy", "gap", ms=1)    # history (region/surfRegion) result: (step_values, values)

Notes
  * Harmonic/eigen results are stored as Real + Imag datasets even if complexFormat="amplPhase"
    was requested; get() returns a complex array -> use np.abs()/np.angle().
  * For eigenFrequency analyses the step value is the eigenfrequency in Hz.
  * Node indices in Mesh/Regions/<r>/Nodes are 1-based global node numbers.
"""
import argparse
import sys
from pathlib import Path

import numpy as np

try:
    import h5py
except ImportError:  # pragma: no cover
    sys.exit("h5py required: python -m pip install h5py")


def winpath(p):
    """Accept Git-Bash/MSYS style paths (/c/Users/...) on Windows."""
    import os, re
    if p and os.name == "nt":
        m = re.match(r"^/([a-zA-Z])(/.*)?$", str(p))
        if m:
            return f"{m.group(1).upper()}:{(m.group(2) or '/')}"
    return p


class CfsFile:
    def __init__(self, path):
        self.path = Path(path)
        self.f = h5py.File(self.path, "r")

    # ---------------- mesh
    def regions(self):
        return {k: int(g.attrs.get("Dimension", 0)) for k, g in self.f["Mesh/Regions"].items()}

    def coords(self, region=None):
        X = self.f["Mesh/Nodes/Coordinates"][()]
        if region is None:
            return X
        return X[self.f[f"Mesh/Regions/{region}/Nodes"][()].astype(int) - 1]

    def connectivity(self, region):
        el = self.f[f"Mesh/Regions/{region}/Elements"][()].astype(int) - 1
        return self.f["Mesh/Elements/Connectivity"][()][el].astype(int) - 1  # 0-based global node ids (0 = padding -> -1)

    def centroids(self, region):
        X = self.f["Mesh/Nodes/Coordinates"][()]
        C = self.connectivity(region)
        out = np.zeros((len(C), 3))
        for i, row in enumerate(C):
            row = row[row >= 0]
            out[i] = X[row].mean(0)
        return out

    # ---------------- results
    def multisteps(self):
        g = self.f.get("Results/Mesh")
        return sorted(int(k.split("_")[1]) for k in g if k.startswith("MultiStep_")) if g else []

    def steps(self, ms=1, kind="Mesh"):
        g = self.f[f"Results/{kind}/MultiStep_{ms}"]
        if kind == "Mesh":
            st = [(int(k.split("_")[1]), float(g[k].attrs.get("StepValue", np.nan))) for k in g if k.startswith("Step_")]
            return sorted(st)
        return []

    def quantities(self, ms=1):
        g = self.f[f"Results/Mesh/MultiStep_{ms}/ResultDescription"]
        out = {}
        for q in g:
            d = g[q]
            ent = [x.decode() if isinstance(x, bytes) else str(x) for x in d["EntityNames"][()]]
            dofs = [x.decode() if isinstance(x, bytes) else str(x) for x in d["DOFNames"][()]]
            on = int(d["DefinedOn"][()][0])
            out[q] = {"regions": ent, "dofs": dofs, "on": {1: "nodes", 4: "elements"}.get(on, f"type{on}")}
        return out

    def get(self, quantity, region=None, ms=1, step=1):
        base = f"Results/Mesh/MultiStep_{ms}/Step_{step}/{quantity}"
        if base not in self.f:
            raise KeyError(f"{quantity} not stored for ms={ms} step={step}. Available: "
                           f"{list(self.f[f'Results/Mesh/MultiStep_{ms}/Step_{step}'].keys())}")
        regs = list(self.f[base].keys())
        region = region or regs[0]
        g = self.f[f"{base}/{region}"]
        loc = "Nodes" if "Nodes" in g else "Elements"
        d = g[loc]
        re_ = d["Real"][()]
        if "Imag" in d:
            return re_ + 1j * d["Imag"][()]
        return re_

    def location(self, quantity, region, ms=1, step=1):
        g = self.f[f"Results/Mesh/MultiStep_{ms}/Step_{step}/{quantity}/{region}"]
        return "Nodes" if "Nodes" in g else "Elements"

    def region_result(self, quantity, region, ms=1):
        g = self.f[f"Results/History/MultiStep_{ms}/{quantity}"]
        for kind in g:
            if region in g[kind]:
                d = g[kind][region]
                v = d["Real"][()]
                if "Imag" in d:
                    v = v + 1j * d["Imag"][()]
                sv = self.f[f"Results/History/MultiStep_{ms}/ResultDescription/{quantity}/StepValues"][()]
                return sv, v
        raise KeyError(f"{region} not found for {quantity}")

    def summary(self):
        out = {}
        for ms in self.multisteps():
            g = self.f[f"Results/Mesh/MultiStep_{ms}"]
            st = self.steps(ms)
            out[ms] = {"analysis": g.attrs.get("AnalysisType"), "n_steps": len(st),
                       "step_values": [v for _, v in st][:20], "quantities": self.quantities(ms)}
        hist = self.f.get("Results/History")
        if hist:
            for k in hist:
                ms = int(k.split("_")[1])
                out.setdefault(ms, {})["history"] = [q for q in hist[k] if q != "ResultDescription"]
        return out


def _comp(vals, comp):
    v = np.abs(vals) if np.iscomplexobj(vals) else vals
    if v.ndim == 1 or v.shape[1] == 1:
        return v.reshape(-1)
    if comp in (None, "mag"):
        return np.linalg.norm(v, axis=1)
    idx = {"x": 0, "y": 1, "z": 2, "r": 0}.get(comp, None)
    return v[:, idx if idx is not None else int(comp)]


def cmd_info(a):
    r = CfsFile(a.file)
    print("regions:", ", ".join(f"{k}(dim{v})" for k, v in r.regions().items()))
    print("nodes:", len(r.coords()))
    for ms, s in r.summary().items():
        print(f"\nMultiStep_{ms}: {s.get('analysis')}, {s.get('n_steps')} steps; step values: {s.get('step_values')}")
        for q, d in s.get("quantities", {}).items():
            print(f"  {q:28s} on {d['on']:8s} dofs={d['dofs']} regions={d['regions']}")
        if s.get("history"):
            print("  history (region/surfRegion results):", ", ".join(s["history"]))


def cmd_export(a):
    r = CfsFile(a.file)
    steps = [s for s, _ in r.steps(a.ms)] if a.step == "all" else [int(a.step)]
    regions = [a.region] if a.region else r.quantities(a.ms)[a.quantity]["regions"]
    rows, header = [], None
    for st in steps:
        sv = dict(r.steps(a.ms))[st]
        for reg in regions:
            v = r.get(a.quantity, reg, a.ms, st)
            v = v.reshape(len(v), -1)
            xyz = r.coords(reg) if r.location(a.quantity, reg, a.ms, st) == "Nodes" else r.centroids(reg)
            dofs = [d or a.quantity for d in r.quantities(a.ms)[a.quantity]["dofs"]]
            if np.iscomplexobj(v):
                cols = [f"{d}_re" for d in dofs] + [f"{d}_im" for d in dofs] + [f"{d}_abs" for d in dofs]
                data = np.hstack([v.real, v.imag, np.abs(v)])
            else:
                cols, data = list(dofs), v
            header = ["step", "step_value", "region", "x", "y", "z"] + cols
            for i in range(len(v)):
                rows.append([st, sv, reg, *xyz[i], *data[i]])
    out = a.output or f"{Path(a.file).stem}_{a.quantity}.csv"
    with open(out, "w") as fh:
        fh.write(",".join(header) + "\n")
        for row in rows:
            fh.write(",".join(str(x) for x in row) + "\n")
    print(f"wrote {out} ({len(rows)} rows)")


def cmd_plot(a):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.tri as mtri
    from matplotlib.collections import PolyCollection

    r = CfsFile(a.file)
    st = int(a.step)
    regions = [a.region] if a.region else r.quantities(a.ms)[a.quantity]["regions"]
    Xall = r.f["Mesh/Nodes/Coordinates"][()].copy()
    if a.deform:
        # displace every node that has a displacement value (any region)
        for reg in r.regions():
            try:
                u = np.real(r.get("mechDisplacement", reg, a.ms, st))
            except KeyError:
                continue
            gid = r.f[f"Mesh/Regions/{reg}/Nodes"][()].astype(int) - 1
            Xall[gid, : u.shape[1]] = r.f["Mesh/Nodes/Coordinates"][()][gid, : u.shape[1]] + a.deform * u
    mirrors = [()]  # list of axes to negate, built from --mirror x|y|xy
    for ax_ in (a.mirror or ""):
        mirrors += [m + ({"x": 0, "y": 1}[ax_],) for m in mirrors]

    fig, ax = plt.subplots(figsize=(8, 6))
    items, allv = [], []
    for reg in regions:
        v = _comp(r.get(a.quantity, reg, a.ms, st), a.comp)
        loc = r.location(a.quantity, reg, a.ms, st)
        conn = r.connectivity(reg)
        is2d = r.regions().get(reg) == 2 and np.ptp(Xall[:, 2]) <= 1e-9 * max(np.ptp(Xall[:, 0]), 1e-30)
        if not is2d:
            print(f"note: {reg} is 3D - plotting an x-y projection of node/centroid values (use ParaView for 3D)")
        items.append((reg, v, loc, conn, is2d))
        allv.append(v)
    vmin, vmax = min(x.min() for x in allv), max(x.max() for x in allv)
    norm = matplotlib.colors.Normalize(vmin, vmax if vmax > vmin else vmin + 1e-30)
    levels = np.linspace(norm.vmin, norm.vmax, 31)
    mappable = None
    for reg, v, loc, conn, is2d in items:
        for neg in mirrors:
            X = Xall.copy()
            for k in neg:
                X[:, k] *= -1
            if is2d and loc == "Elements":
                # one coloured polygon per element: exact, respects holes, shows the raw element values
                polys = []
                for row in conn:
                    row = row[row >= 0]
                    nc = 4 if len(row) in (4, 8, 9) else 3
                    polys.append(X[row[:nc], :2])
                pc = PolyCollection(polys, array=v, cmap="viridis", norm=norm, edgecolors="face", linewidths=0.2)
                ax.add_collection(pc)
                mappable = pc
            elif is2d:
                gid = r.f[f"Mesh/Regions/{reg}/Nodes"][()].astype(int) - 1
                pos = -np.ones(len(Xall), int)
                pos[gid] = np.arange(len(gid))
                t = []
                for row in conn:
                    row = pos[row[row >= 0]]
                    c = row[:4] if len(row) in (4, 8, 9) else row[:3]
                    t += [c[[0, 1, 2]], c[[0, 2, 3]]] if len(c) == 4 else [c]
                tri = mtri.Triangulation(X[gid, 0], X[gid, 1], np.array(t))
                mappable = ax.tricontourf(tri, v, levels=levels, cmap="viridis", norm=norm)
            else:
                P = X[r.f[f"Mesh/Regions/{reg}/Nodes"][()].astype(int) - 1] if loc == "Nodes" else r.centroids(reg)
                mappable = ax.scatter(P[:, 0], P[:, 1], c=v, s=4, cmap="viridis", norm=norm)
    ax.autoscale_view()
    fig.colorbar(mappable, ax=ax, label=f"{a.quantity} ({a.comp or 'mag'})")
    sv = dict(r.steps(a.ms)).get(st)
    ax.set_title(f"{a.quantity}  ms={a.ms} step={st} value={sv:g}")
    ax.set_aspect("equal")
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    out = a.output or f"{Path(a.file).stem}_{a.quantity}_s{st}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"wrote {out}  (min {vmin:.4g}, max {vmax:.4g})")
    if any(loc == "Elements" for _, _, loc, _, _ in items):
        print("note: element results are element-centroid values; peaks at notches/edges are underestimated "
              "(see references/results_and_postprocessing.md - peak values)")


def read_hist(path):
    lines = Path(path).read_text(errors="replace").splitlines()
    head = [l for l in lines if l.startswith("#")]
    data = np.array([[float(x) for x in l.split()] for l in lines if l.strip() and not l.startswith("#")])
    return head, data


def cmd_hist(a):
    head, data = read_hist(a.file)
    print("\n".join(head))
    print(data if len(data) < 40 else f"{len(data)} rows; first {data[0]} last {data[-1]}")
    if a.output:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots()
        for j in range(1, data.shape[1]):
            ax.plot(data[:, 0], data[:, j], label=f"col {j}")
        ax.set_xlabel(head[1].split()[1] if len(head) > 1 else "t/f")
        ax.set_title(head[0].lstrip("# ") if head else "")
        ax.legend()
        fig.savefig(a.output, dpi=150, bbox_inches="tight")
        print("wrote", a.output)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("info"); p.add_argument("file"); p.set_defaults(fn=cmd_info)
    for name, fn in (("export", cmd_export), ("plot", cmd_plot)):
        p = sub.add_parser(name)
        p.add_argument("file"); p.add_argument("quantity")
        p.add_argument("--region"); p.add_argument("--ms", type=int, default=1)
        p.add_argument("--step", default="1"); p.add_argument("-o", "--output")
        if name == "plot":
            p.add_argument("--comp", default=None)
            p.add_argument("--deform", type=float, default=0.0)
            p.add_argument("--mirror", default="", help="x, y or xy: mirror a symmetric (half/quarter) model about x=0 / y=0")
        p.set_defaults(fn=fn)
    p = sub.add_parser("hist"); p.add_argument("file"); p.add_argument("-o", "--output"); p.set_defaults(fn=cmd_hist)
    a = ap.parse_args()
    a.file = winpath(a.file)
    if getattr(a, "output", None):
        a.output = winpath(a.output)
    a.fn(a)


if __name__ == "__main__":
    main()
