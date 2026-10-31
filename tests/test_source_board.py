"""Source-capability board: field-review JSONs are consistent, the field README agrees, the SVGs are current."""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIELD = ROOT / "examples/source_capability/results/2026-10-31-field"
WEIGHTS = {"F": 25, "C": 20, "B": 15, "E": 15, "T": 15, "S": 10}
PRODUCTS = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(FIELD.glob("*.json"))]


def test_seven_servers_scored():
    assert len(PRODUCTS) == 7
    assert len({p["repository"] for p in PRODUCTS}) == 7


@pytest.mark.parametrize("product", PRODUCTS, ids=lambda p: p["repository"])
def test_scores_add_up_and_cite_the_pin(product):
    sha = product["product_sha"]
    assert re.fullmatch(r"[0-9a-f]{40}", sha)
    items = {i["id"]: i for i in product["items"]}
    assert len(items) == 20 and all(0 <= i["score"] <= i["max_score"] == 5 for i in items.values())
    categories = {c["id"]: c for c in product["categories"]}
    assert {k: c["weight"] for k, c in categories.items()} == WEIGHTS
    assert sorted(i for c in categories.values() for i in c["item_ids"]) == sorted(items)
    for c in categories.values():
        assert c["score"] == sum(items[i]["score"] for i in c["item_ids"]) <= c["weight"]
    assert product["total_score"] == sum(c["score"] for c in categories.values())
    for item in items.values():
        assert item["basis"] and item["source"]
        urls = [s.get("url") or "" for s in item["source"]]
        assert all(sha in url for url in urls if "github.com" in url)
    for path in product.get("evidence_paths", []):
        assert (ROOT / path).is_file() or (FIELD / path).is_file() or (FIELD / "evidence" / path).is_file(), path


def test_field_readme_matches_json():
    text = (FIELD / "README.md").read_text(encoding="utf-8")
    for product in PRODUCTS:
        line = next(l for l in text.splitlines() if l.startswith(f"| [{product['repository']}]"))
        cells = [c.strip(" *") for c in line.split("|")[1:-1]]
        assert product["product_sha"][:7] in cells[1]
        assert [int(c) for c in cells[3:10]] == [c["score"] for c in product["categories"]] + [product["total_score"]]


@pytest.mark.skipif(importlib.util.find_spec("matplotlib") is None, reason="matplotlib not installed")
def test_board_svgs_are_current():
    script = ROOT / "docs/assets/source-capability/make_board.py"
    r = subprocess.run([sys.executable, str(script), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
