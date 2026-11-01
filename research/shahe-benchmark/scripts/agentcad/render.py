"""Supplement the CLI exports with orthographic views using AgentCAD's API."""
import json
import os
from pathlib import Path
from agentcad.policy import Policy
from agentcad.service import Runtime

root = Path(os.environ['SHAHE_AGENTCAD_OUT']).resolve()
runtime = Runtime(Policy(root=root))
report = runtime.export_drawing('shahe.FCStd', 'views.png', 'png', overwrite=True,
                                views=['front', 'top', 'right', 'iso'], image_size=768)
(root / 'export-views.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))
