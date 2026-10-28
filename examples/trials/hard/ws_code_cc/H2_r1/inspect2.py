import ezdxf, sys
from collections import Counter
doc = ezdxf.readfile(sys.argv[1])
for lay in doc.layouts:
    print('layout', lay.name, Counter(e.dxftype() for e in lay))
blk = doc.blocks.get('Print#')
for m in blk:
    print('Print# MTEXT', repr(m.text), m.dxf.insert, m.dxf.char_height, m.dxf.get('attachment_point'))
ds = doc.dimstyles.get('2dTranslator Dimension Style')
for k, v in sorted(ds.dxf.all_existing_dxf_attribs().items()):
    print('  ', k, v)
print('blk2dCenterMark1', Counter(e.dxftype() for e in doc.blocks.get('2dCenterMark1')))
