#!/usr/bin/env python3
"""Query the openCFS XML schemas (shipped with the installation) so you never
have to guess element / attribute / enum names.

Usage examples
--------------
  python schema_lookup.py pdes                      # list all PDEs, analyses, couplings
  python schema_lookup.py show mechanic             # children + attributes of <mechanic>
  python schema_lookup.py show mechanic/bcsAndLoads # all BCs/loads of the mechanic PDE
  python schema_lookup.py show heatConduction/bcsAndLoads/heatTransport
  python schema_lookup.py show harmonic             # analysis parameters
  python schema_lookup.py results acoustic          # valid storeResults types for a PDE
  python schema_lookup.py show direct               # direct coupling options
  python schema_lookup.py show --material mechanical/elasticity/linear
  python schema_lookup.py grep pml                  # search element/type names + docs

Paths are '/'-separated element names starting at any globally declared element
(PDE names, analysis names, 'cfsSimulation', 'domain' is reachable as
cfsSimulation/domain, material classes via --material).

The schema root is found from $CFS_SCHEMA_ROOT, from cfs.exe on PATH
(<install>/share/xml), from $CFS_EXE, or from common install folders.
"""
import os
import re
import shutil
import sys
from pathlib import Path

try:
    from lxml import etree
except ImportError:  # pragma: no cover
    sys.exit("lxml is required: python -m pip install lxml")

XS = "{http://www.w3.org/2001/XMLSchema}"


def find_schema_root():
    env = os.environ.get("CFS_SCHEMA_ROOT")
    if env and Path(env).is_dir():
        return Path(env)
    cands = []
    for exe in (os.environ.get("CFS_EXE"), shutil.which("cfs"), shutil.which("cfs.exe")):
        if exe and Path(exe).exists():
            cands.append(Path(exe).resolve().parent.parent / "share" / "xml")
    for root in (Path("C:/Tools/OpenCFS"), Path("C:/Program Files/openCFS"), Path("/opt"), Path.home()):
        if root.exists():
            cands += [p / "share" / "xml" for p in sorted(root.glob("[Cc][Ff][Ss]*"), reverse=True)]
            cands += [p / "share" / "xml" for p in sorted(root.glob("openCFS*"), reverse=True)]
    cands += [Path("/opt/openCFS/share/xml"), Path.home() / "openCFS" / "share" / "xml"]
    for c in cands:
        if (c / "CFS-Simulation" / "CFS.xsd").exists():
            return c
    sys.exit("Could not locate openCFS schemas. Set CFS_SCHEMA_ROOT=<install>/share/xml")


class Schema:
    def __init__(self, main_xsd):
        self.elements, self.ctypes, self.stypes = {}, {}, {}
        self.groups, self.agroups, self.subst = {}, {}, {}
        self._seen = set()
        self._load(Path(main_xsd))

    def _load(self, path):
        path = path.resolve()
        if path in self._seen:
            return
        self._seen.add(path)
        root = etree.parse(str(path)).getroot()
        for inc in root.findall(XS + "include") + root.findall(XS + "import"):
            loc = inc.get("schemaLocation")
            if loc and not loc.startswith("http"):
                self._load(path.parent / loc)
        for child in root:
            if not isinstance(child.tag, str):
                continue
            tag, name = child.tag.replace(XS, ""), child.get("name")
            if not name:
                continue
            store = {"element": self.elements, "complexType": self.ctypes,
                     "simpleType": self.stypes, "group": self.groups,
                     "attributeGroup": self.agroups}.get(tag)
            if store is not None:
                store.setdefault(name, child)
            if tag == "element" and child.get("substitutionGroup"):
                sg = strip(child.get("substitutionGroup"))
                self.subst.setdefault(sg, []).append(name)

    # ---------------- helpers -----------------
    def ctype_of(self, el):
        """Return the complexType node describing element `el` (or None)."""
        if el.get("ref"):
            el = self.elements.get(strip(el.get("ref")), el)
        ct = el.find(XS + "complexType")
        if ct is not None:
            return ct
        t = el.get("type")
        if t:
            return self.ctypes.get(strip(t))
        return None

    def children(self, ct, _depth=0):
        """Yield (name, element_node, minOccurs, maxOccurs) of child elements."""
        if ct is None or _depth > 30:
            return
        for node in ct.iter():
            if not isinstance(node.tag, str):
                continue
            tag = node.tag.replace(XS, "")
            if tag in ("extension", "restriction") and node.get("base"):
                base = self.ctypes.get(strip(node.get("base")))
                if base is not None and base is not ct:
                    yield from self.children(base, _depth + 1)
            elif tag == "group" and node.get("ref"):
                g = self.groups.get(strip(node.get("ref")))
                if g is not None:
                    yield from self.children(g, _depth + 1)
            elif tag == "element" and node is not ct:
                # only direct structural children (not nested inside a child element's own type)
                if self._owner_element(node, ct) is not None:
                    continue
                if node.get("ref"):
                    ref = strip(node.get("ref"))
                    if ref in self.subst:  # abstract head -> list concrete members
                        for m in sorted(self.subst[ref]):
                            yield m, self.elements[m], node.get("minOccurs", "1"), node.get("maxOccurs", "1")
                        if self.elements.get(ref) is not None and self.elements[ref].get("abstract") != "true":
                            yield ref, self.elements[ref], node.get("minOccurs", "1"), node.get("maxOccurs", "1")
                        continue
                    yield ref, self.elements.get(ref, node), node.get("minOccurs", "1"), node.get("maxOccurs", "1")
                else:
                    yield node.get("name"), node, node.get("minOccurs", "1"), node.get("maxOccurs", "1")

    @staticmethod
    def _owner_element(node, ct):
        p = node.getparent()
        while p is not None and p is not ct:
            if isinstance(p.tag, str) and p.tag == XS + "element":
                return p
            p = p.getparent()
        return None

    def attributes(self, ct, _depth=0):
        if ct is None or _depth > 30:
            return
        for node in ct.iter():
            if not isinstance(node.tag, str):
                continue
            tag = node.tag.replace(XS, "")
            if tag in ("extension", "restriction") and node.get("base"):
                base = self.ctypes.get(strip(node.get("base")))
                if base is not None and base is not ct:
                    yield from self.attributes(base, _depth + 1)
            elif tag == "attributeGroup" and node.get("ref"):
                g = self.agroups.get(strip(node.get("ref")))
                if g is not None:
                    yield from self.attributes(g, _depth + 1)
            elif tag == "attribute" and node.get("name"):
                if self._owner_element(node, ct) is None:
                    yield node

    def enum_values(self, node):
        st = node.find(XS + "simpleType")
        if st is None and node.get("type"):
            st = self.stypes.get(strip(node.get("type")))
        vals, seen = [], set()
        def walk(s, d=0):
            if s is None or d > 10 or id(s) in seen:
                return
            seen.add(id(s))
            for e in s.iter(XS + "enumeration"):
                vals.append(e.get("value"))
            for r in s.iter(XS + "restriction"):
                if r.get("base") and strip(r.get("base")) in self.stypes:
                    walk(self.stypes[strip(r.get("base"))], d + 1)
            for u in s.iter(XS + "union"):
                for mt in (u.get("memberTypes") or "").split():
                    walk(self.stypes.get(strip(mt)), d + 1)
        walk(st)
        return list(dict.fromkeys(vals))

    def resolve(self, path):
        parts = [p for p in path.split("/") if p]
        if not parts:
            sys.exit("empty path")
        el = self.elements.get(parts[0])
        if el is None:
            sys.exit(f"'{parts[0]}' is not a global element. Try: schema_lookup.py grep {parts[0]}")
        for p in parts[1:]:
            nxt = None
            for name, node, *_ in self.children(self.ctype_of(el)):
                if name == p:
                    nxt = node
                    break
            if nxt is None:
                avail = sorted({n for n, *_ in self.children(self.ctype_of(el))})
                sys.exit(f"No child '{p}' here. Available: {', '.join(avail)}")
            el = nxt
        return el


def strip(qname):
    return qname.split(":")[-1]


def doc(node, width=110):
    d = node.find(f"{XS}annotation/{XS}documentation")
    if d is None or not (d.text or "").strip():
        return ""
    txt = re.sub(r"\s+", " ", d.text).strip()
    return txt if len(txt) <= width else txt[: width - 3] + "..."


def show(s, path):
    el = s.resolve(path)
    print(f"<{path.split('/')[-1]}>  " + doc(el, 300))
    ct = s.ctype_of(el)
    attrs = list(s.attributes(ct)) if ct is not None else []
    if attrs:
        print("\n  attributes:")
        for a in attrs:
            ev = s.enum_values(a)
            extra = f" one of {ev}" if ev else (f" ({strip(a.get('type'))})" if a.get("type") else "")
            req = " REQUIRED" if a.get("use") == "required" else ""
            dflt = f" default={a.get('default')!r}" if a.get("default") is not None else ""
            print(f"    @{a.get('name')}{req}{dflt}{extra}  {doc(a, 80)}")
    kids = list(s.children(ct)) if ct is not None else []
    if kids:
        print("\n  child elements:")
        seen = set()
        for name, node, mn, mx in kids:
            if name in seen:
                continue
            seen.add(name)
            # occurrences of enclosing choice/sequence override the element's own
            p = node.getparent() if node.getparent() is not None else None
            while p is not None and isinstance(p.tag, str) and p.tag in (XS + "choice", XS + "sequence"):
                if p.get("maxOccurs") == "unbounded":
                    mx = "unbounded"
                if p.get("minOccurs") == "0" or p.tag == XS + "choice":
                    mn = "0" if p.get("minOccurs") == "0" else mn
                p = p.getparent()
            occ = f"[{mn}..{'n' if mx == 'unbounded' else mx}]"
            # flag mutually exclusive alternatives (xsd:choice that is not repeatable)
            par = node.getparent()
            alt = ""
            if (par is not None and par.tag == XS + "choice" and par.get("maxOccurs") != "unbounded"
                    and len([c for c in par if isinstance(c.tag, str) and c.tag in (XS + "element", XS + "group", XS + "sequence")]) > 1):
                alt = f" (choice {id(par) % 997}: use only ONE of this group)"
            print(f"    <{name}> {occ}{alt}  {doc(node, 90)}")
    if ct is None or (not attrs and not kids):
        ev = s.enum_values(el)
        if ev:
            print("  allowed values:", ", ".join(ev))
        elif el.get("type"):
            print("  simple content of type", el.get("type"))


def results(s, pde):
    el = s.resolve(pde + "/storeResults")
    for name, node, *_ in s.children(s.ctype_of(el)):
        ct = s.ctype_of(node)
        types = []
        for a in (s.attributes(ct) if ct is not None else []):
            if a.get("name") == "type":
                types = s.enum_values(a)
        if types:
            print(f"<{name} type=...>: {', '.join(types)}")


def list_pdes(s):
    print("PDEs (inside <pdeList>):      ", ", ".join(sorted(s.subst.get("PDEBasic", []))))
    print("Analyses (inside <analysis>): ", ", ".join(sorted(s.subst.get("AnalysisBasic", []))))
    print("Couplings (<couplingList>):   ", ", ".join(sorted(s.subst.get("PDEBasicCoupling", []))))
    d = s.elements.get("direct")
    if d is not None:
        print("  direct couplings:            ", ", ".join(sorted({n for n, *_ in s.children(s.ctype_of(d))})))


def grep(s, pat):
    rx = re.compile(pat, re.I)
    for kind, store in (("element", s.elements), ("complexType", s.ctypes), ("simpleType", s.stypes)):
        for n, node in sorted(store.items()):
            if rx.search(n) or rx.search(doc(node, 500)):
                print(f"{kind:12s} {n:40s} {doc(node, 70)}")
    # also local element names
    hits = set()
    for ct in list(s.ctypes.values()) + list(s.elements.values()):
        for e in ct.iter(XS + "element"):
            if e.get("name") and rx.search(e.get("name")):
                owner = ct.get("name")
                hits.add((e.get("name"), owner))
    for n, owner in sorted(hits)[:80]:
        print(f"{'local elem':12s} {n:40s} (inside {owner})")


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    root = find_schema_root()
    material = "--material" in argv
    argv = [a for a in argv if a != "--material"]
    main_xsd = root / ("CFS-Material/CFS_Material.xsd" if material else "CFS-Simulation/CFS.xsd")
    s = Schema(main_xsd)
    cmd = argv[1]
    if cmd == "pdes":
        list_pdes(s)
    elif cmd == "show" and len(argv) > 2:
        path = argv[2]
        if material and not path.startswith("cfsMaterialDataBase"):
            path = "cfsMaterialDataBase/material/" + path
        show(s, path)
    elif cmd == "results" and len(argv) > 2:
        results(s, argv[2])
    elif cmd == "grep" and len(argv) > 2:
        grep(s, argv[2])
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
