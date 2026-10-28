# usage: python diff_docs.py OLD.dxf NEW.dxf  -> per-handle tag diff of modelspace + blocks
import sys
import ezdxf
from ezdxf.lldxf.tagwriter import TagCollector

old = ezdxf.readfile(sys.argv[1])
new = ezdxf.readfile(sys.argv[2])


def tags(e):
    tc = TagCollector(dxfversion=e.doc.dxfversion)
    e.export_dxf(tc)
    return tc.tags


def cmp_layout(lo, ln, label):
    ho = {e.dxf.handle: e for e in lo}
    hn = {e.dxf.handle: e for e in ln}
    for h in sorted(set(ho) - set(hn)):
        print(label, "REMOVED", h, ho[h].dxftype())
    for h in sorted(set(hn) - set(ho)):
        print(label, "ADDED", h, hn[h].dxftype())
    for h in sorted(set(ho) & set(hn)):
        to, tn = tags(ho[h]), tags(hn[h])
        if to != tn:
            diffs = [(a, b) for a, b in zip(to, tn) if a != b]
            if len(to) != len(tn):
                diffs.append(("len", len(to), len(tn)))
            print(label, "CHANGED", h, ho[h].dxftype(), diffs)


cmp_layout(old.modelspace(), new.modelspace(), "MSP")
names_o = {b.name for b in old.blocks}
names_n = {b.name for b in new.blocks}
print("blocks only in old:", sorted(names_o - names_n), "only in new:", sorted(names_n - names_o))
for name in sorted(names_o & names_n):
    cmp_layout(old.blocks[name], new.blocks[name], "BLOCK " + name)
