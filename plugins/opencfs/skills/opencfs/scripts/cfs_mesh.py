"""Small helper layer over the gmsh Python API for producing openCFS-ready meshes.

openCFS reads Gmsh meshes in the *legacy ASCII 2.2 format*; region names are the
Gmsh *physical group* names. This module takes care of those details and of the
most common pitfall: physical groups that end up empty (cfs then aborts with
"Region has neither volume nor surface elements").

Install gmsh once with:  python -m pip install gmsh

Typical use (write a small mesh script per model)::

    import sys; sys.path.insert(0, r"<skill>/scripts")
    from cfs_mesh import Mesh
    m = Mesh("beam")                       # starts gmsh, OCC kernel
    s = m.occ.addRectangle(0, 0, 0, 1.0, 0.1)
    m.sync()
    m.group(2, [s], "beam")                # volume region (2D model -> dim 2)
    m.group(1, m.in_box(1, xmax=0), "fix") # all curves with x == 0
    m.group(1, m.in_box(1, xmin=1.0), "tip")
    m.write("beam.msh", size=0.02, quads=True)   # meshes, checks, writes msh 2.2

Selection helpers:
    in_box(dim, xmin=..,xmax=.., ymin=.., ...)  entities fully inside the box
                                                (missing bounds = unbounded; tolerant)
    near(dim, x, y, z)                          entity whose centre of mass is closest
    all(dim)                                    all entity tags of a dimension

For multi-region geometry, call m.fragment() after creating all solids so the
regions share nodes at interfaces (conforming mesh — required for coupling and
for continuity between regions).
"""
import math
import sys

try:
    import gmsh
except ImportError:  # pragma: no cover
    sys.exit("gmsh python package missing: python -m pip install gmsh")


class Mesh:
    def __init__(self, name="model", verbose=False):
        if not gmsh.isInitialized():
            gmsh.initialize()
        gmsh.option.setNumber("General.Terminal", 1 if verbose else 0)
        gmsh.model.add(name)
        self.occ = gmsh.model.occ
        self.model = gmsh.model
        self.groups = []  # (dim, name)

    # ---------------------------------------------------------------- geometry
    def sync(self):
        self.occ.synchronize()

    def fragment(self):
        """Make all entities conforming (shared interfaces). Call after building solids."""
        top = max(d for d, _ in self.occ.getEntities()) if self.occ.getEntities() else 0
        ents = self.occ.getEntities(top)
        if len(ents) > 1:
            self.occ.fragment(ents[:1], ents[1:])
        self.sync()

    def _diag(self):
        xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(-1, -1)
        return max(math.dist((xmin, ymin, zmin), (xmax, ymax, zmax)), 1e-12)

    def in_box(self, dim, xmin=None, xmax=None, ymin=None, ymax=None, zmin=None, zmax=None, tol=None):
        """Tags of entities of `dim` lying completely inside the (tolerant) box.

        Unspecified bounds are open. A tolerance relative to the model size is
        added, because OCC bounding boxes are slightly inflated.
        """
        # OCC inflates bounding boxes by ~1e-7 (absolute), so never go below that
        tol = tol if tol is not None else max(1e-6 * self._diag(), 5e-7)
        big = 1e30
        b = [(-big if xmin is None else xmin) - tol, (-big if ymin is None else ymin) - tol,
             (-big if zmin is None else zmin) - tol, (big if xmax is None else xmax) + tol,
             (big if ymax is None else ymax) + tol, (big if zmax is None else zmax) + tol]
        return [t for _, t in gmsh.model.getEntitiesInBoundingBox(*b, dim)]

    def near(self, dim, x, y, z=0.0):
        best, bd = None, float("inf")
        for _, t in gmsh.model.getEntities(dim):
            c = self.occ.getCenterOfMass(dim, t)
            d = math.dist(c, (x, y, z))
            if d < bd:
                best, bd = t, d
        return [best] if best is not None else []

    def all(self, dim):
        return [t for _, t in gmsh.model.getEntities(dim)]

    def group(self, dim, tags, name):
        tags = list(dict.fromkeys(tags))
        if not tags:
            raise ValueError(f"physical group '{name}' (dim {dim}) would be empty - check the selection")
        gmsh.model.addPhysicalGroup(dim, tags, name=name)
        self.groups.append((dim, name))
        return tags

    def cut(self, tool_tags, dim=None, base_tags=None):
        """Subtract tool entities (e.g. a hole disk) from the base entities (default: all others)."""
        dim = dim or max(d for d, _ in self.occ.getEntities())
        tools = [(dim, t) for t in tool_tags]
        base = [(dim, t) for t in (base_tags or [t for _, t in self.occ.getEntities(dim) if t not in tool_tags])]
        out, _ = self.occ.cut(base, tools)
        self.sync()
        return [t for _, t in out]

    # ---------------------------------------------------------------- meshing
    def refine(self, entity_dim, tags, size_min, size_max, dist_min, dist_max):
        """Local refinement: element size grows from size_min (within dist_min of the given
        entities, e.g. a hole's curves) to size_max (beyond dist_max). Call before write()."""
        f = gmsh.model.mesh.field
        d = f.add("Distance")
        key = {0: "PointsList", 1: "CurvesList", 2: "SurfacesList"}[entity_dim]
        f.setNumbers(d, key, list(tags))
        f.setNumber(d, "Sampling", 200)
        th = f.add("Threshold")
        f.setNumber(th, "InField", d)
        for k, v in (("SizeMin", size_min), ("SizeMax", size_max), ("DistMin", dist_min), ("DistMax", dist_max)):
            f.setNumber(th, k, v)
        self._fields = getattr(self, "_fields", []) + [th]
        mn = f.add("Min")
        f.setNumbers(mn, "FieldsList", self._fields)
        f.setAsBackgroundMesh(mn)
        for opt in ("Mesh.MeshSizeExtendFromBoundary", "Mesh.MeshSizeFromPoints", "Mesh.MeshSizeFromCurvature"):
            gmsh.option.setNumber(opt, 0)

    def write(self, filename, size=None, size_min=None, order=1, quads=False, dim=None,
              transfinite=False, finalize=True):
        """Generate the mesh, verify every physical group got elements, write msh 2.2 ASCII."""
        if size:
            gmsh.option.setNumber("Mesh.MeshSizeMax", size)
        if size_min:
            gmsh.option.setNumber("Mesh.MeshSizeMin", size_min)
        if quads:
            gmsh.option.setNumber("Mesh.RecombineAll", 1)
        if transfinite:
            gmsh.model.mesh.setTransfiniteAutomatic()
        dim = dim or max(d for d, _ in gmsh.model.getEntities())
        gmsh.model.mesh.generate(dim)
        if order > 1:
            gmsh.model.mesh.setOrder(order)

        report, empty = [], []
        for d, tag in gmsh.model.getPhysicalGroups():
            name = gmsh.model.getPhysicalName(d, tag)
            n = 0
            for ent in gmsh.model.getEntitiesForPhysicalGroup(d, tag):
                types, elems, _ = gmsh.model.mesh.getElements(d, ent)
                n += sum(len(e) for e in elems)
            report.append(f"  dim{d} {name:20s} {n:8d} elements")
            if n == 0:
                empty.append(name)
        if not gmsh.model.getPhysicalGroups():
            empty.append("<no physical groups defined>")

        gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
        gmsh.option.setNumber("Mesh.Binary", 0)
        gmsh.option.setNumber("Mesh.SaveAll", 0)  # only elements in physical groups
        gmsh.write(filename)
        nn = len(gmsh.model.mesh.getNodes()[0])
        print(f"wrote {filename}: {nn} nodes")
        print("\n".join(report))
        if finalize:
            gmsh.finalize()
        if empty:
            raise RuntimeError(f"empty physical groups: {empty}")


def msh_regions(path):
    """Return {name: (dim, n_elements)} for a msh 2.2 ASCII file (used for pre-flight checks)."""
    names, counts, section = {}, {}, None
    with open(path, "r", errors="replace") as f:
        lines = iter(f)
        for line in lines:
            s = line.strip()
            if s == "$PhysicalNames":
                n = int(next(lines))
                for _ in range(n):
                    d, tag, nm = next(lines).split(maxsplit=2)
                    names[int(tag)] = (int(d), nm.strip().strip('"'))
            elif s == "$Elements":
                n = int(next(lines))
                for _ in range(n):
                    p = next(lines).split()
                    ntags = int(p[2])
                    if ntags:
                        phys = int(p[3])
                        counts[phys] = counts.get(phys, 0) + 1
            elif s == "$MeshFormat":
                ver = next(lines).split()[0]
                if not ver.startswith("2"):
                    raise ValueError(f"{path}: msh version {ver}; openCFS needs 2.2 ASCII")
    return {nm: (d, counts.get(tag, 0)) for tag, (d, nm) in names.items()}
