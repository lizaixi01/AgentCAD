"""Optimistic edit preconditions, independent of the journal's event sequence."""

from __future__ import annotations

import hashlib
import json

from ezdxf.lldxf.tagwriter import TagCollector

from .errors import input_error
from .store import sha256_file


def fingerprint(entity) -> str:
    tags = TagCollector.dxftags(entity)
    for attribute in getattr(entity, "attribs", ()):
        tags.extend(TagCollector.dxftags(attribute))
    raw = json.dumps([(t.code, str(t.value)) for t in tags], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def snapshot(store, doc) -> dict:
    return {
        "revision": store.head().get("revision", 0),
        "sha256": sha256_file(store.path),
        "entities": {e.dxf.handle: fingerprint(e) for lay in doc.layouts for e in lay},
    }


def check(store, doc, expected_revision=None, preconditions=None) -> dict:
    current = snapshot(store, doc)
    if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
        raise input_error("BAD_PARAMETER", "expected_revision must be a nonnegative integer")
    changed = []
    stale = expected_revision is not None and expected_revision != current["revision"]
    if preconditions is not None:
        if (
            not isinstance(preconditions, dict)
            or not preconditions
            or set(preconditions) - {"sha256", "entities"}
            or not isinstance(preconditions.get("entities", {}), dict)
        ):
            raise input_error(
                "BAD_PARAMETER", "preconditions needs sha256 and/or an entities handle-to-fingerprint map"
            )
        if "sha256" in preconditions:
            stale |= preconditions["sha256"] != current["sha256"]
        for handle, expected in preconditions.get("entities", {}).items():
            if expected != current["entities"].get(handle):
                changed.append(handle)
        stale |= bool(changed)
    if stale:
        raise input_error(
            "STALE_REVISION",
            "The drawing changed after the edit was planned",
            entities=changed,
            details={
                "expected_revision": expected_revision,
                "actual_revision": current["revision"],
                "changed_handles": changed,
            },
            hint="Read or preview again, then submit the new preconditions",
        )
    return current
