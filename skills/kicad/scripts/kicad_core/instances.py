"""Which instance data KiCad 10 uses for a placed symbol on one sheet path.

A placed symbol carries one instance (reference, unit) per sheet path it appears on.  KiCad
looks the sheet's full path up exactly (the root sheet uuid first, then the sheet uuids); with
no instance for that path it copies the first instance of the current project, else the first
instance (``SCH_SHEET_PATH::CheckForMissingSymbolInstances``).
"""
from __future__ import annotations

from kicad_core.sexp import find_first, get_value


def tilde_is_empty(file_version) -> bool:
    """True when a ``"~"`` field text means empty: files older than 20250318 (unreadable
    versions count as old)."""
    try:
        return int(file_version) < 20250318
    except (TypeError, ValueError):
        return True


def _norm_path(path: str) -> str:
    return path.rstrip("/").lower()


def resolve_instance(candidates: list[dict], instance_path: str,
                     project_name: str) -> dict | None:
    """Pick the instance KiCad uses on *instance_path*.

    *candidates* are dicts with ``path`` (full KIID path), ``project``, ``reference`` and
    ``unit``, in load order.  An exact path match wins, the last duplicate replacing earlier
    ones; otherwise the first candidate of *project_name*, else the first candidate; None when
    there are no candidates (the caller keeps the Reference field).
    """
    want = _norm_path(instance_path)
    hit = None
    for cand in candidates:
        if _norm_path(cand.get("path") or "") == want:
            hit = cand
    if hit is not None or not candidates:
        return hit
    for cand in candidates:
        if cand.get("project") == project_name:
            return cand
    return candidates[0]


def inline_instances(sym: list, tilde_empty: bool) -> list[dict]:
    """The ``(instances (project P (path X ...)))`` entries of a placed symbol, in file order.

    Each entry has ``project``, ``path``, ``reference`` and ``unit`` (None when absent), plus
    ``value`` / ``footprint`` when the path carries them.
    """
    out = []
    node = find_first(sym, "instances")
    if not node:
        return out
    for proj in node[1:]:
        if not isinstance(proj, list) or len(proj) < 2 or proj[0] != "project":
            continue
        for path_node in proj[2:]:
            if not isinstance(path_node, list) or not path_node or path_node[0] != "path":
                continue
            try:
                unit = int(get_value(path_node, "unit") or 0) or None
            except (TypeError, ValueError):
                unit = None
            entry = {"project": proj[1] if isinstance(proj[1], str) else "",
                     "path": path_node[1] if len(path_node) > 1 else "",
                     "reference": get_value(path_node, "reference") or "",
                     "unit": unit}
            for key in ("value", "footprint"):
                text = get_value(path_node, key)
                if text is not None:
                    entry[key] = "" if (tilde_empty and text == "~") else text
            out.append(entry)
    return out
