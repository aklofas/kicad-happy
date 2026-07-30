"""Figure generation pipeline runner.

Orchestrates the prepare → hash-check → render pipeline for all
registered generators.  Each generator's ``prepare()`` output is
written to a ``.json`` file that serves as both the input contract
and the cache key.  If the JSON hasn't changed since last render,
the figure is skipped.

Zero external dependencies — Python 3.8+ stdlib only.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import time
from typing import List, Optional

from .lib.theme import FigureTheme
from .registry import get_registry, check_requires, GeneratorEntry


def run_all(analysis: dict, config: dict, output_dir: str,
            theme: Optional[FigureTheme] = None,
            force: bool = False) -> List[str]:
    """Run the full prepare → hash-check → render pipeline.

    For each registered generator:
    1. Call ``prepare(analysis, config)`` to extract input data
    2. Serialize to JSON, compare hash with existing ``.json`` file
    3. If changed (or *force*), write ``.json`` and call ``render()``
    4. If unchanged, skip render and collect existing outputs

    Args:
        analysis: Unified analysis dict (schematic + thermal + emc + spice).
        config: Project config from ``.kicad-happy.json``.
        output_dir: Directory for ``.json`` and ``.svg`` output files.
        theme: Figure theme (built from config if *None*).
        force: If True, re-render all figures regardless of cache.

    Returns:
        List of generated/existing SVG file paths.
    """
    os.makedirs(output_dir, exist_ok=True)
    theme = theme or FigureTheme.from_config(config)
    outputs: List[str] = []

    for entry in get_registry():
        has_deps = check_requires(entry)

        try:
            data = entry.generator_cls.prepare(analysis, config)
        except Exception as exc:
            if has_deps:
                print(f"  [{entry.name}] prepare failed: {exc}",
                      file=sys.stderr)
            continue

        if data is None:
            continue

        if not has_deps:
            missing = [m for m in entry.requires
                       if importlib.util.find_spec(m) is None]
            print(f"  WARNING: {entry.name} figure has data but cannot "
                  f"render — missing {', '.join(missing)}. "
                  f"Run from the reports venv to generate.",
                  file=sys.stderr)
            continue

        if entry.multi_output:
            # data is list of (key, input_dict) tuples
            if not isinstance(data, list):
                continue
            for key, input_dict in data:
                json_path = os.path.join(output_dir, f"{key}.json")
                svg_path = os.path.join(output_dir, f"{key}.svg")
                if _should_render(json_path, svg_path, input_dict, force):
                    _write_json(json_path, input_dict)
                    t0 = time.monotonic()
                    try:
                        path = entry.generator_cls.render(
                            input_dict, svg_path, theme=theme)
                    except Exception as exc:
                        print(f"  [{entry.name}/{key}] render failed: {exc}",
                              file=sys.stderr)
                        continue
                    elapsed = int((time.monotonic() - t0) * 1000)
                    if path:
                        outputs.append(path)
                        print(f"  [{entry.name}/{key}] rendered ({elapsed}ms)",
                              file=sys.stderr)
                else:
                    if os.path.exists(svg_path):
                        outputs.append(svg_path)
        else:
            json_path = os.path.join(output_dir, f"{entry.name}.json")
            svg_path = os.path.join(output_dir, entry.output)
            if _should_render(json_path, svg_path, data, force):
                _write_json(json_path, data)
                t0 = time.monotonic()
                try:
                    path = entry.generator_cls.render(
                        data, svg_path, theme=theme)
                except Exception as exc:
                    print(f"  [{entry.name}] render failed: {exc}",
                          file=sys.stderr)
                    continue
                elapsed = int((time.monotonic() - t0) * 1000)
                if path:
                    outputs.append(path)
                    print(f"  [{entry.name}] rendered ({elapsed}ms)",
                          file=sys.stderr)
            else:
                if os.path.exists(svg_path):
                    outputs.append(svg_path)

    return outputs


def _should_render(json_path: str, svg_path: str,
                   new_data: dict, force: bool) -> bool:
    """Check whether the figure needs (re-)rendering.

    Returns True if:
    - *force* is set
    - The ``.json`` input file doesn't exist
    - The ``.svg`` output file doesn't exist
    - The serialized *new_data* differs from the existing ``.json``
    """
    if force:
        return True
    if not os.path.exists(json_path):
        return True
    if not os.path.exists(svg_path):
        return True

    new_bytes = _serialize(new_data)
    try:
        with open(json_path, 'rb') as f:
            existing_bytes = f.read()
    except OSError:
        return True
    return new_bytes != existing_bytes


def _serialize(data: dict) -> bytes:
    """Deterministic JSON serialization (used for both writing and comparing)."""
    return (json.dumps(data, indent=2, sort_keys=True, default=str) + '\n').encode()


def _write_json(path: str, data: dict) -> None:
    """Write data to a JSON file."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'wb') as f:
        f.write(_serialize(data))
