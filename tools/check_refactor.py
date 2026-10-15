#!/usr/bin/env python3
"""Refactor checker for kicad-happy (v3 arc).

Subcommands (added across round 1):
  compare   strict-field JSON comparison of two snapshot directories
  snapshot  run the analyzers over a fixture tree into a snapshot directory
  imports   dependency-direction check (tools/layer_rules.json)
  tags      literal detector/rule_id/schema_era scan (tools/tag_baseline.json)
  install-smoke  copy core (+ one optional skill) to a temp dir, run CLIs from an unrelated cwd
  determinism    snapshot twice with random hash seeds and compare
  quick     imports + tags + install-smoke + determinism (+ compare when --baseline given)

Stdlib only. Exit 0 = pass, 1 = findings, 2 = usage/setup error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
DEFAULT_POLICY = TOOLS_DIR / "volatile_leaves_v1.json"

Delta = tuple  # (path, kind, base, cand)


def load_policy(path: Path = DEFAULT_POLICY) -> set[str]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return set(data["volatile_leaves"])


def _norm_path(path: str) -> str:
    """Replace every [N] index with [*] so wildcards in the policy match."""
    out, i = [], 0
    while i < len(path):
        if path[i] == "[":
            j = path.index("]", i)
            out.append("[*]")
            i = j + 1
        else:
            out.append(path[i])
            i += 1
    return "".join(out)


def _is_volatile(path: str, volatile: set[str]) -> bool:
    return bool(path) and (path in volatile or _norm_path(path) in volatile)


def compare_json(base, cand, volatile: set[str], path: str = "") -> list[Delta]:
    if _is_volatile(path, volatile):
        return []
    if type(base) is not type(cand):
        return [(path, "type", base, cand)]
    if isinstance(base, dict):
        deltas: list[Delta] = []
        bk, ck = list(base), list(cand)
        if set(bk) == set(ck) and bk != ck:
            deltas.append((path, "order", bk, ck))
        for k in bk:
            sub = f"{path}.{k}" if path else k
            if k not in cand:
                if not _is_volatile(sub, volatile):
                    deltas.append((sub, "missing", base[k], None))
            else:
                deltas.extend(compare_json(base[k], cand[k], volatile, sub))
        for k in ck:
            if k not in base:
                sub = f"{path}.{k}" if path else k
                if not _is_volatile(sub, volatile):
                    deltas.append((sub, "added", None, cand[k]))
        return deltas
    if isinstance(base, list):
        if len(base) != len(cand):
            return [(path, "length", len(base), len(cand))]
        deltas = []
        for i, (b, c) in enumerate(zip(base, cand)):
            deltas.extend(compare_json(b, c, volatile, f"{path}[{i}]"))
        return deltas
    if base != cand:
        return [(path, "value", base, cand)]
    return []


def compare_dirs(base_dir: Path, cand_dir: Path, volatile: set[str]) -> dict:
    """Compare every *.json under base_dir with its counterpart. Returns a report dict."""
    report = {"files": {}, "missing_in_candidate": [], "extra_in_candidate": [], "total_deltas": 0}
    base_files = {p.relative_to(base_dir).as_posix(): p for p in base_dir.rglob("*.json")}
    cand_files = {p.relative_to(cand_dir).as_posix(): p for p in cand_dir.rglob("*.json")}
    for rel in sorted(base_files):
        if rel not in cand_files:
            report["missing_in_candidate"].append(rel)
            continue
        b = json.loads(base_files[rel].read_text(encoding="utf-8"))
        c = json.loads(cand_files[rel].read_text(encoding="utf-8"))
        deltas = compare_json(b, c, volatile)
        if deltas:
            report["files"][rel] = [list(d) for d in deltas]
            report["total_deltas"] += len(deltas)
    report["extra_in_candidate"] = sorted(set(cand_files) - set(base_files))
    return report


def cmd_compare(args) -> int:
    base, cand = Path(args.base), Path(args.cand)
    for label, d in (("base", base), ("cand", cand)):
        if not d.is_dir():
            print(f"compare: {label} directory not found: {d}", file=sys.stderr)
            return 2
    if not any(base.rglob("*.json")):
        print(f"compare: base directory contains no *.json: {base}", file=sys.stderr)
        return 2
    try:
        volatile = load_policy(Path(args.policy))
    except (OSError, ValueError, KeyError) as exc:
        print(f"compare: cannot load policy {args.policy}: {exc}", file=sys.stderr)
        return 2
    report = compare_dirs(base, cand, volatile)
    bad = report["total_deltas"] or report["missing_in_candidate"] or report["extra_in_candidate"]
    if args.json:
        print(json.dumps(report, indent=1, default=str))
    else:
        for rel, deltas in report["files"].items():
            print(f"{rel}: {len(deltas)} delta(s)")
            for d in deltas[:20]:
                print(f"   {d[1]:8} {d[0]}: {d[2]!r} -> {d[3]!r}")
        for rel in report["missing_in_candidate"]:
            print(f"MISSING in candidate: {rel}")
        for rel in report["extra_in_candidate"]:
            print(f"EXTRA in candidate: {rel}")
        print("compare: " + ("FAIL" if bad else "OK") + f" ({report['total_deltas']} delta(s), "
              f"{len(report['files'])} file(s) differ)")
    return 1 if bad else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="check_refactor.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compare", help="strict-field compare two snapshot dirs")
    c.add_argument("base")
    c.add_argument("cand")
    c.add_argument("--policy", default=str(DEFAULT_POLICY))
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_compare)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
