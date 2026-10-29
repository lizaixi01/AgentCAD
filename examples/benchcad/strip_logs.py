"""Replace long base64 strings in agent run logs (inline images, thinking signatures) with a placeholder, in place.

The preview PNGs that export_drawing returns inline make up most of a run log's size. They can be
regenerated from the workspace, so the committed logs keep the trace and drop the pixels.

    python examples/benchcad/strip_logs.py examples/benchcad/runs/*/v2c/*.jsonl
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

B64 = re.compile(r"^[A-Za-z0-9+/=\r\n]+$")
MIN_LEN = 2000


def strip(v):
    if isinstance(v, str):
        if len(v) >= MIN_LEN and B64.match(v):
            return f"<base64 omitted, {len(v)} chars>"
        if len(v) >= MIN_LEN and v.lstrip().startswith(("{", "[")):
            try:  # tool results often carry JSON inside a string
                return json.dumps(strip(json.loads(v)), ensure_ascii=False)
            except ValueError:
                return v
        return v
    if isinstance(v, list):
        return [strip(x) for x in v]
    if isinstance(v, dict):
        return {k: strip(x) for k, x in v.items()}
    return v


def main(paths: list[str]) -> None:
    for p in map(Path, paths):
        out = []
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.dumps(strip(json.loads(line)), ensure_ascii=False))
            except ValueError:
                out.append(line)
        p.write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
