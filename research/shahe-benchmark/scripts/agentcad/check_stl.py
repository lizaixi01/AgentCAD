"""Read binary STL independently and report triangle count, bounds and defects."""
import json
import math
import os
import struct
from pathlib import Path

p = Path(os.environ['SHAHE_AGENTCAD_OUT']) / 'shahe.stl'
data = p.read_bytes()
n, = struct.unpack_from('<I', data, 80)
assert len(data) == 84 + n * 50, 'not a complete binary STL'
lo, hi = [math.inf]*3, [-math.inf]*3
nonfinite = 0
for i in range(n):
    v = struct.unpack_from('<12fH', data, 84 + 50*i)
    for j in (3, 6, 9):
        for k in range(3):
            x = v[j+k]
            nonfinite += not math.isfinite(x)
            lo[k] = min(lo[k], x)
            hi[k] = max(hi[k], x)
report = {'readable_binary_stl': True, 'triangles': n, 'bounds_mm': [lo, hi],
          'nonfinite_coordinates': nonfinite,
          'note': 'Structural readback only; manifoldness and architectural fidelity not checked.'}
assert n > 0 and nonfinite == 0
out = p.with_name('stl-readback.json')
out.write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))
