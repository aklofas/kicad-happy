#!/usr/bin/env python3
"""Refactor checker for kicad-happy (v3 arc).

Subcommands (added across round 1):
  compare   strict-field JSON comparison of two snapshot directories
  snapshot  run the analyzers over a fixture tree into a snapshot directory
  imports   dependency-direction check (tools/layer_rules.json)
  tags      literal detector/rule_id/schema_era scan (tools/tag_baseline.json)
  install-smoke  copy core (+ one optional skill) to a temp dir, run CLIs from an unrelated cwd
  determinism    snapshot twice with random hash seeds and compare
  aba       in-process A/B/A: analyse two boards in one interpreter (+ a built-in KiCad-10 pair), A must not change
  sync-offline   distributor sync/fetch scripts over recorded fixtures vs the frozen expected outputs
  text-compare  byte-compare two directories of masked text artefacts (snapshot writes them beside the JSON)
  quick     imports + tags + install-smoke + determinism + aba (+ compare when --baseline given) + sync-offline
            (+ text-compare when --text-baseline given)

Stdlib only. Exit 0 = pass, 1 = findings, 2 = usage/setup error.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
DEFAULT_POLICY = TOOLS_DIR / "volatile_leaves_v1.json"
LAYER_RULES = TOOLS_DIR / "layer_rules.json"
IMPORT_BASELINE = TOOLS_DIR / "import_baseline.json"
TAG_BASELINE = TOOLS_DIR / "tag_baseline.json"
TAG_KEYS = ("detector", "rule_id", "schema_era")
DISTRIBUTOR_EXPECTED = TOOLS_DIR / "tests" / "fixtures" / "distributor" / "expected"

SKILL_CLIS = {
    "kicad": ["skills/kicad/scripts/analyze_schematic.py", "skills/kicad/scripts/analyze_pcb.py",
              "skills/kicad/scripts/analyze_gerbers.py", "skills/kicad/scripts/analyze_thermal.py",
              "skills/kicad/scripts/cross_analysis.py", "skills/kicad/scripts/diff_analysis.py",
              "skills/kicad/scripts/what_if.py", "skills/kicad/scripts/summarize_findings.py",
              "skills/kicad/review/scripts/deep_review_gate.py", "skills/kicad/scripts/lifecycle_audit.py",
              "action/format-report.py"],
    "datasheets": ["skills/datasheets/scripts/datasheet_verify.py", "skills/datasheets/scripts/plan_extraction.py"],
    "emc": ["skills/emc/scripts/analyze_emc.py"],
    "spice": ["skills/spice/scripts/simulate_subcircuits.py", "skills/spice/scripts/extract_parasitics.py"],
    "bom": ["skills/bom/scripts/bom_manager.py"],
    "digikey": ["skills/digikey/scripts/fetch_datasheet_digikey.py", "skills/digikey/scripts/sync_datasheets_digikey.py"],
    "mouser": ["skills/mouser/scripts/fetch_datasheet_mouser.py", "skills/mouser/scripts/sync_datasheets_mouser.py"],
    "element14": ["skills/element14/scripts/fetch_datasheet_element14.py", "skills/element14/scripts/sync_datasheets_element14.py"],
    "lcsc": ["skills/lcsc/scripts/fetch_datasheet_lcsc.py", "skills/lcsc/scripts/sync_datasheets_lcsc.py", "skills/lcsc/scripts/search_lcsc.py"],
}
SCHEMA_CLIS = ["skills/kicad/scripts/analyze_schematic.py", "skills/kicad/scripts/analyze_pcb.py",
               "skills/kicad/scripts/analyze_gerbers.py", "skills/kicad/scripts/analyze_thermal.py",
               "skills/kicad/scripts/cross_analysis.py", "skills/emc/scripts/analyze_emc.py"]

Delta = tuple  # (path, kind, base, cand)


def load_policy(path: Path = DEFAULT_POLICY) -> set[str]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return set(data["volatile_leaves"])


def _norm_path(path: str) -> str:
    """Replace every [N] index with [*] so wildcards in the policy match."""
    return re.sub(r"\[\d+\]", "[*]", path)


def _is_volatile(path: str, volatile: set[str]) -> bool:
    """Exact match (index-normalised), or a policy entry ending in `*` (not `[*]`) as a path prefix."""
    if not path:
        return False
    norm = _norm_path(path)
    if path in volatile or norm in volatile:
        return True
    return any(v.endswith("*") and not v.endswith("[*]") and (path.startswith(v[:-1]) or norm.startswith(v[:-1]))
               for v in volatile)


SNAP_TOKEN = "<SNAP>"


def _substitute_root(obj, root_str: str, *alt_roots: str):
    """Rewrite dict keys and string values under any given root to start with <SNAP> instead.

    A root only matches at a path-separator boundary (or the end of the string).
    """
    roots = sorted({r for r in (root_str, *alt_roots) if r}, key=len, reverse=True)

    def sub(x):
        if isinstance(x, str):
            for r in roots:
                if x.startswith(r) and (len(x) == len(r) or x[len(r)] in "/\\"):
                    return SNAP_TOKEN + x[len(r):]
            return x
        if isinstance(x, list):
            return [sub(v) for v in x]
        if isinstance(x, dict):
            return {sub(k): sub(v) for k, v in x.items()}
        return x
    return sub(obj)


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
    base_roots, cand_roots = (str(base_dir), str(base_dir.resolve())), (str(cand_dir), str(cand_dir.resolve()))
    base_files = {p.relative_to(base_dir).as_posix(): p for p in base_dir.rglob("*.json")}
    cand_files = {p.relative_to(cand_dir).as_posix(): p for p in cand_dir.rglob("*.json")}
    for rel in sorted(base_files):
        if rel not in cand_files:
            report["missing_in_candidate"].append(rel)
            continue
        b = _substitute_root(json.loads(base_files[rel].read_text(encoding="utf-8")), *base_roots)
        c = _substitute_root(json.loads(cand_files[rel].read_text(encoding="utf-8")), *cand_roots)
        deltas = compare_json(b, c, volatile)
        if deltas:
            report["files"][rel] = [list(d) for d in deltas]
            report["total_deltas"] += len(deltas)
    report["extra_in_candidate"] = sorted(set(cand_files) - set(base_files))
    return report


def _check_base_dir(base: Path) -> str | None:
    """Error text when the baseline directory is missing or holds no *.json, else None."""
    if not base.is_dir():
        return f"base directory not found: {base}"
    if not any(base.rglob("*.json")):
        return f"base directory contains no *.json: {base}"
    return None


def cmd_compare(args) -> int:
    base, cand = Path(args.base), Path(args.cand)
    if not cand.is_dir():
        print(f"compare: cand directory not found: {cand}", file=sys.stderr)
        return 2
    msg = _check_base_dir(base)
    if msg:
        print(f"compare: {msg}", file=sys.stderr)
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


GERBER_EXTS = {".gbr", ".gbl", ".gtl", ".gm1", ".gko", ".drl", ".gbs", ".gts", ".gbo", ".gto", ".gbp", ".gtp"}
ANALYZERS = {
    "schematic": "skills/kicad/scripts/analyze_schematic.py",
    "pcb": "skills/kicad/scripts/analyze_pcb.py",
    "gerber": "skills/kicad/scripts/analyze_gerbers.py",
    "thermal": "skills/kicad/scripts/analyze_thermal.py",
    "emc": "skills/emc/scripts/analyze_emc.py",
    "cross_analysis": "skills/kicad/scripts/cross_analysis.py",
}


def discover_fixtures(root: Path) -> list[dict]:
    out = []
    for p in sorted(root.rglob("*")):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(root).as_posix()
        if p.suffix == ".kicad_sch" and p.is_file():
            out.append({"kind": "sch", "rel": rel, "path": p})
        elif p.suffix == ".kicad_pcb" and p.is_file():
            out.append({"kind": "pcb", "rel": rel, "path": p})
        elif p.is_dir() and any(c.suffix.lower() in GERBER_EXTS for c in p.iterdir() if c.is_file()):
            out.append({"kind": "gerber", "rel": rel, "path": p})
    return out


def _slot(out_dir: Path, rel: str) -> Path:
    d = out_dir / rel.replace("/", "__")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _run(cmd: list[str], env: dict, timeout: int = 300) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s"
    lines = (proc.stderr or "").strip().splitlines()
    return proc.returncode, (lines[-1] if lines else "")


def _produce(cmd: list[str], target: Path, label: str, env: dict, stats: dict) -> None:
    """Run one analyzer into `target`; a stale file is removed first, a missing result is a failure."""
    target.unlink(missing_ok=True)
    rc, err = _run(cmd, env)
    if not target.exists():
        stats["failures"].append({"fixture": label, "exit": rc, "stderr": err})


def run_snapshot(fixtures_root: Path, out_dir: Path, product_root: Path, env: dict) -> dict:
    py = sys.executable
    stats = {"sch": 0, "pcb": 0, "gerber": 0, "chain": 0, "failures": []}
    by_dir: dict[str, dict] = {}
    for fx in discover_fixtures(fixtures_root):
        slot = _slot(out_dir, fx["rel"])
        path, rel = str(fx["path"]), fx["rel"]
        if fx["kind"] == "sch":
            script = str(product_root / ANALYZERS["schematic"])
            _produce([py, script, path, "-o", str(slot / "schematic.json")], slot / "schematic.json", rel, env, stats)
            stats["sch"] += 1
            by_dir.setdefault(str(fx["path"].parent), {})["sch"] = slot / "schematic.json"
        elif fx["kind"] == "pcb":
            script = str(product_root / ANALYZERS["pcb"])
            _produce([py, script, path, "-o", str(slot / "pcb.json")], slot / "pcb.json", rel, env, stats)
            _produce([py, script, path, "--full", "-o", str(slot / "pcb_full.json")],
                     slot / "pcb_full.json", f"{rel}:pcb_full.json", env, stats)
            stats["pcb"] += 1
            by_dir.setdefault(str(fx["path"].parent), {})["pcb"] = slot / "pcb.json"
        else:
            script = str(product_root / ANALYZERS["gerber"])
            _produce([py, script, path, "-o", str(slot / "gerber.json")], slot / "gerber.json", rel, env, stats)
            stats["gerber"] += 1
    # Chained analyzers where a directory produced both schematic and pcb outputs.
    for d, outs in sorted(by_dir.items()):
        if "sch" in outs and "pcb" in outs:
            slot = outs["sch"].parent
            for kind in ("emc", "thermal", "cross_analysis"):
                script = str(product_root / ANALYZERS[kind])
                _produce([py, script, "--schematic", str(outs["sch"]), "--pcb", str(outs["pcb"]),
                          "-o", str(slot / f"{kind}.json")], slot / f"{kind}.json", f"{d}:{kind}", env, stats)
            stats["chain"] += 1
    return stats


def analyzer_env(seed: str) -> dict:
    env = dict(os.environ)
    if seed == "random":
        env.pop("PYTHONHASHSEED", None)
    else:
        env["PYTHONHASHSEED"] = seed
    return env


def _check_inputs(label: str, fixtures, product) -> str | None:
    """Error text when the fixtures/product paths cannot yield a meaningful run, else None."""
    if not Path(product).is_dir():
        return f"{label}: product is not a directory: {product}"
    if not Path(fixtures).is_dir():
        return f"{label}: fixtures path is not a directory: {fixtures}"
    if not discover_fixtures(Path(fixtures)):
        return f"{label}: no fixtures discovered under {fixtures}"
    return None


def cmd_snapshot(args) -> int:
    msg = _check_inputs("snapshot", args.fixtures, args.product)
    if msg:
        print(msg, file=sys.stderr)
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stats = run_snapshot(Path(args.fixtures), out, Path(args.product), analyzer_env(args.seed))
    stats["text_artefacts"] = run_text_snapshot(Path(args.fixtures), out, out, Path(args.product),
                                                _text_env(args.seed))
    print(json.dumps(stats, indent=1, default=str))
    return 1 if stats["failures"] else 0


def _py_files(root: Path):
    for p in sorted((root / "skills").rglob("*.py")):
        if "__pycache__" not in p.parts:
            yield p


def _skill_of(rel: str) -> str | None:
    parts = rel.split("/")
    return parts[1] if len(parts) > 2 and parts[0] == "skills" else None


def _assign_ordinals(items: list[dict], group) -> None:
    """Sort by (file, line) and give each item its 0-based index within its group."""
    items.sort(key=lambda d: (d["file"], d["line"]))
    seen: dict[tuple, int] = {}
    for d in items:
        g = group(d)
        d["ordinal"] = seen.get(g, 0)
        seen[g] = d["ordinal"] + 1


def _tag_key(d: dict) -> tuple:
    return (d["file"], d["function"], d["callee"], d["ordinal"])


def _import_key(d: dict) -> tuple:
    return (d["file"], d["module"], d["rule"], d["ordinal"])


def scan_imports(root: Path, errors: list | None = None) -> list[dict]:
    edges = []
    for p in _py_files(root):
        rel = p.relative_to(root).as_posix()
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
            if errors is not None:
                errors.append((rel, str(exc)))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    edges.append({"file": rel, "module": a.name.split(".")[0], "line": node.lineno})
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                edges.append({"file": rel, "module": node.module.split(".")[0], "line": node.lineno})
    return edges


def _module_index(root: Path) -> dict[str, str]:
    """bare module/package name -> owning skill (first match wins, sorted for determinism)."""
    idx: dict[str, str] = {}
    for p in _py_files(root):
        rel = p.relative_to(root).as_posix()
        skill = _skill_of(rel)
        name = p.parent.name if p.name == "__init__.py" else p.stem
        idx.setdefault(name, skill)
    return idx


def classify_edges(edges: list[dict], rules: dict, root: Path) -> list[dict]:
    idx = _module_index(root)
    stdlib = set(sys.stdlib_module_names)
    core = set(rules["core_skills"])
    stdlib_only = tuple(rules["stdlib_only_packages"])
    clis = set(rules["cli_modules"])
    out = []
    for e in edges:
        mod, src = e["module"], e["file"]
        if mod in stdlib or mod == "__future__":
            continue
        src_skill = _skill_of(src)
        src_dir = (root / src).parent
        if (src_dir / f"{mod}.py").is_file() or (src_dir / mod / "__init__.py").is_file():
            target_skill = src_skill  # resolves beside the importing file: same skill
        else:
            target_skill = idx.get(mod)
        if src.startswith(stdlib_only):
            if mod != "kicad_core" and (target_skill is not None or mod not in stdlib):
                out.append({**e, "rule": "core-package-stdlib-only"})
                continue
        if mod in clis and Path(src).stem != mod:
            out.append({**e, "rule": "no-cli-import"})
            continue
        if target_skill is None:
            continue  # third-party or unknown: not a layering question
        if src_skill not in core and target_skill not in core and target_skill != src_skill:
            out.append({**e, "rule": "optional-to-optional"})
    excepted = {(x["file"], x["module"], x["rule"]) for x in rules.get("exceptions", [])}
    out = [e for e in out if (e["file"], e["module"], e["rule"]) not in excepted]
    _assign_ordinals(out, lambda d: (d["file"], d["module"], d["rule"]))
    return out


def _call_name(node: ast.Call) -> str | None:
    fn = node.func
    return fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None


def _classify_factories(tree: ast.AST) -> tuple[set[str], set[str]]:
    """(wrappers, dict_factories) among the file's `_make_*` definitions.

    wrapper: its body calls make_finding/_make_finding, so that inner call is the emit site.
    dict_factory: returns a dict literal with a "detector" key, so its callers are the emit sites.
    Any other `_make_*` definition is not a finding factory.
    """
    wrappers: set[str] = set()
    dict_factories: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("_make_") or node.name == "_make_finding":
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and _call_name(sub) in ("make_finding", "_make_finding"):
                wrappers.add(node.name)
            elif isinstance(sub, ast.Return) and isinstance(sub.value, ast.Dict) and any(
                    isinstance(k, ast.Constant) and k.value == "detector" for k in sub.value.keys):
                dict_factories.add(node.name)
    return wrappers, dict_factories - wrappers


def scan_tags(root: Path, errors: list | None = None) -> list[dict]:
    sites = []
    for p in _py_files(root):
        rel = p.relative_to(root).as_posix()
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
            if errors is not None:
                errors.append((rel, str(exc)))
            continue
        wrappers, dict_factories = _classify_factories(tree)

        def visit(node, scope):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                scope = scope + [node.name]
            if isinstance(node, ast.Call):
                name = _call_name(node)
                if name in ("make_finding", "_make_finding") or (name and name in dict_factories):
                    kws = {k.arg: k.value for k in node.keywords if k.arg}
                    missing = [k for k in TAG_KEYS if k not in kws]
                    nonliteral = [k for k in TAG_KEYS if k in kws and not (isinstance(kws[k], ast.Constant) and isinstance(kws[k].value, str))]
                    if missing or nonliteral:
                        sites.append({"file": rel, "line": node.lineno, "callee": name,
                                      "function": ".".join(scope) or "<module>",
                                      "missing": missing, "nonliteral": nonliteral})
            for child in ast.iter_child_nodes(node):
                visit(child, scope)

        visit(tree, [])
    _assign_ordinals(sites, lambda d: (d["file"], d["function"], d["callee"]))
    return sites


def _ratchet(current: list[dict], baseline_path: Path, update: bool, key_fields: tuple[str, ...], key_fn=None,
             moved_from: tuple[str, ...] = ()) -> int:
    def key(d): return key_fn(d) if key_fn else tuple(d[k] for k in key_fields)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else []
    base_keys = {key(d) for d in baseline}
    new = [d for d in current if key(d) not in base_keys]
    gone = len(base_keys - {key(d) for d in current})
    if new and update and not baseline_path.exists():
        new = []  # first generation of a baseline
    if new and update and moved_from:
        from collections import Counter

        cur_keys = {key(d) for d in current}

        def shape(d):
            return (d.get("callee") or d.get("rule"), tuple(d.get("missing", [])),
                    tuple(d.get("nonliteral", [])), d.get("module", ""))
        pool = Counter(shape(d) for d in baseline if key(d) not in cur_keys and d["file"] in moved_from)
        need = Counter(shape(d) for d in new)
        if not (need - pool):
            print(f"{baseline_path.name}: {len(new)} relocated entries matched against "
                  f"{sum(pool.values())} retired from moved files")
            new = []
    for d in new:
        print(f"NEW {d['file']}:{d['line']} {d.get('rule') or d['callee']} {d.get('module','')} "
              f"{'missing=' + ','.join(d['missing']) if d.get('missing') else ''} "
              f"{'nonliteral=' + ','.join(d['nonliteral']) if d.get('nonliteral') else ''}".rstrip())
    if new:
        print(f"{baseline_path.name}: FAIL ({len(new)} new, baseline {len(base_keys)})")
        return 1
    if update:
        baseline_path.write_text(json.dumps(current, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"{baseline_path.name}: updated ({len(current)} entries, {gone} retired)")
    else:
        print(f"{baseline_path.name}: OK ({len(current)} known, {gone} retired since baseline)")
    return 0


def _report_parse_errors(errors: list) -> bool:
    for rel, msg in errors:
        print(f"PARSE-ERROR {rel}: {msg}")
    return bool(errors)


def cmd_imports(args) -> int:
    if args.moved_from and not args.update_baseline:
        print("--moved-from requires --update-baseline", file=sys.stderr)
        return 2
    rules = json.loads(LAYER_RULES.read_text(encoding="utf-8"))
    root = Path(args.product)
    errors: list = []
    edges = scan_imports(root, errors)
    if _report_parse_errors(errors):
        return 1
    v = classify_edges(edges, rules, root)
    print(f"exceptions: {len(rules.get('exceptions', []))} listed in layer_rules.json (see retire_by)")
    for e in rules.get("exceptions", []):
        print(f"  exception: {e['file']} -> {e['module']} [{e['rule']}] retire_by={e['retire_by']}")
    return _ratchet(v, IMPORT_BASELINE, args.update_baseline, (), key_fn=_import_key,
                    moved_from=tuple(args.moved_from or ()))


def cmd_tags(args) -> int:
    if args.moved_from and not args.update_baseline:
        print("--moved-from requires --update-baseline", file=sys.stderr)
        return 2
    errors: list = []
    sites = scan_tags(Path(args.product), errors)
    if _report_parse_errors(errors):
        return 1
    return _ratchet(sites, TAG_BASELINE, args.update_baseline, (), key_fn=_tag_key,
                    moved_from=tuple(args.moved_from or ()))


def install_smoke(product_root: Path, optional_skill: str | None, workdir: Path) -> list[str]:
    """Copy core skills (+ one optional skill) into workdir/plugin and run every CLI --help
    (and --schema for envelope CLIs) with cwd = an unrelated empty directory."""
    plugin = workdir / "plugin" / "skills"
    plugin.mkdir(parents=True)
    skills = ["kicad", "datasheets"]
    if optional_skill and optional_skill not in skills:
        skills.append(optional_skill)
    for sk in skills:
        shutil.copytree(product_root / "skills" / sk, plugin / sk,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (workdir / "plugin" / "action").mkdir()
    shutil.copy2(product_root / "action" / "format-report.py", workdir / "plugin" / "action" / "format-report.py")
    cwd = workdir / "elsewhere"
    cwd.mkdir()
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    failures = []

    def run(script, flag, rel):
        try:
            return subprocess.run([sys.executable, str(script), flag], cwd=cwd, env=env, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=120)
        except subprocess.TimeoutExpired:
            failures.append(f"{rel} {flag} timeout after 120s")
            return None

    clis = [c for sk in skills for c in SKILL_CLIS.get(sk, [])]
    for rel in clis:
        script = workdir / "plugin" / rel
        proc = run(script, "--help", rel)
        if proc is not None and proc.returncode != 0:
            failures.append(f"{rel} --help exit {proc.returncode}: {(proc.stderr or '').strip().splitlines()[-1:]}")
        if rel in SCHEMA_CLIS:
            proc = run(script, "--schema", rel)
            if proc is not None and (proc.returncode != 0 or not proc.stdout.lstrip().startswith("{")):
                failures.append(f"{rel} --schema exit {proc.returncode}")
    return failures


def cmd_install_smoke(args) -> int:
    targets = [args.skill] if args.skill else [None] + [sk for sk in SKILL_CLIS if sk not in ("kicad", "datasheets")]
    rc = 0
    for t in targets:
        with tempfile.TemporaryDirectory() as td:
            f = install_smoke(Path(args.product), t, Path(td))
        label = t or "core"
        print(f"install-smoke[{label}]: " + ("OK" if not f else "FAIL"))
        for line in f:
            print("   " + line)
        rc |= 1 if f else 0
    return rc


def cmd_determinism(args) -> int:
    msg = _check_inputs("determinism", args.fixtures, args.product)
    if msg:
        print(msg, file=sys.stderr)
        return 2
    volatile = load_policy(Path(args.policy))
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        sa = run_snapshot(Path(args.fixtures), Path(a), Path(args.product), analyzer_env("random"))
        sb = run_snapshot(Path(args.fixtures), Path(b), Path(args.product), analyzer_env("random"))
        rep = compare_dirs(Path(a), Path(b), volatile)
    args.snapshot_failures = sa["failures"]
    bad = (rep["total_deltas"] or rep["missing_in_candidate"] or rep["extra_in_candidate"]
           or sa["failures"] or sb["failures"])
    print("determinism: " + ("FAIL" if bad else "OK") + f" ({rep['total_deltas']} delta(s), "
          f"{len(sa['failures'])}+{len(sb['failures'])} snapshot failure(s))")
    for f in sa["failures"] + sb["failures"]:
        print(f"   snapshot failure: {f}")
    for rel, ds in rep["files"].items():
        for d in ds[:10]:
            print(f"   {rel} {d[1]} {d[0]}")
    return 1 if bad else 0


_KICAD10_HEADER = ('(kicad_pcb (version 20260101) (generator "pcbnew") (generator_version "10.0")\n'
                   '  (general (thickness 1.6))\n'
                   '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))\n')


def _kicad10_pad(ref, x, net_name):
    return (f'  (footprint "Test:Pad" (layer "F.Cu") (uuid "aaaaaaaa-0000-0000-0000-00000000{x:04d}") (at {x} 100)\n'
            f'    (property "Reference" "{ref}")\n'
            f'    (pad "1" smd rect (at 0 0) (size 2 2) (layers "F.Cu" "F.Mask") (net "{net_name}"))\n'
            f'  )\n')


KICAD10_BOARD_A = _KICAD10_HEADER + _kicad10_pad("U1", 100, "COMMON") + ")\n"
KICAD10_BOARD_B = _KICAD10_HEADER + _kicad10_pad("U1", 100, "AAA") + _kicad10_pad("U2", 110, "COMMON") + ")\n"

ABA_PROGRAM = r"""
import json, sys
from pathlib import Path
scripts, out, spec = sys.argv[1], Path(sys.argv[2]), json.loads(sys.argv[3])
sys.path.insert(0, scripts)
import analyze_schematic, analyze_pcb
fn = {"sch": analyze_schematic.analyze_schematic, "pcb": analyze_pcb.analyze_pcb,
      "pcb10": analyze_pcb.analyze_pcb}
for kind, (a, b) in spec.items():
    r1 = fn[kind](a)
    fn[kind](b)
    r2 = fn[kind](a)
    (out / f"{kind}_A1.json").write_text(json.dumps(r1, default=str), encoding="utf-8")
    (out / f"{kind}_A2.json").write_text(json.dumps(r2, default=str), encoding="utf-8")
"""


def cmd_aba(args) -> int:
    msg = _check_inputs("aba", args.fixtures, args.product)
    if msg:
        print(msg, file=sys.stderr)
        return 2
    fx = discover_fixtures(Path(args.fixtures))
    spec = {}
    for kind in ("sch", "pcb"):
        paths = [str(f["path"].resolve()) for f in fx if f["kind"] == kind][:2]
        if len(paths) == 2:
            spec[kind] = paths
    if not spec:
        print("aba: need at least two .kicad_sch or two .kicad_pcb fixtures", file=sys.stderr)
        return 2
    volatile = load_policy(Path(args.policy))
    scripts = Path(args.product).resolve() / "skills" / "kicad" / "scripts"
    bad = False
    with tempfile.TemporaryDirectory() as td:
        a = Path(td) / "k10_a.kicad_pcb"; a.write_text(KICAD10_BOARD_A, encoding="utf-8")
        b = Path(td) / "k10_b.kicad_pcb"; b.write_text(KICAD10_BOARD_B, encoding="utf-8")
        spec["pcb10"] = [str(a), str(b)]
        try:
            proc = subprocess.run([sys.executable, "-c", ABA_PROGRAM, str(scripts), td, json.dumps(spec)],
                                  cwd=td, env=analyzer_env("0"), capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=900)
        except subprocess.TimeoutExpired:
            print("aba: FAIL (timeout after 900s)")
            return 1
        if proc.returncode != 0:
            tail = (proc.stderr or "").strip().splitlines()[-3:]
            print(f"aba: FAIL (in-process run exit {proc.returncode}): {' | '.join(tail)}")
            return 1
        for kind in spec:
            a1 = json.loads((Path(td) / f"{kind}_A1.json").read_text(encoding="utf-8"))
            a2 = json.loads((Path(td) / f"{kind}_A2.json").read_text(encoding="utf-8"))
            deltas = compare_json(a1, a2, volatile)
            for d in deltas[:20]:
                print(f"   {kind} {d[1]:8} {d[0]}: {d[2]!r} -> {d[3]!r}")
            bad = bad or bool(deltas)
    print("aba: " + ("FAIL" if bad else "OK") + f" (kinds checked: {', '.join(sorted(spec))})")
    return 1 if bad else 0


def _git_sha(root: Path) -> str:
    def git(*a):
        return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    try:
        head = git("rev-parse", "--short", "HEAD")
        if head.returncode != 0 or not head.stdout.strip():
            return "unknown"
        status = git("status", "--porcelain")
        if status.returncode != 0:
            return "unknown"
    except OSError:
        return "unknown"
    return head.stdout.strip() + ("-dirty" if status.stdout.strip() else "")


def _fixtures_digest(fixtures) -> str | None:
    """sha256 over each fixture's relative path and bytes (gerber dirs: each member file)."""
    if not fixtures:
        return None
    root = Path(fixtures)
    h = hashlib.sha256()
    for f in discover_fixtures(root):
        members = ([(f["rel"], f["path"])] if f["kind"] != "gerber" else
                   [(f"{f['rel']}/{c.name}", c) for c in sorted(f["path"].iterdir(), key=lambda c: c.name) if c.is_file()])
        for rel, p in members:
            data = p.read_bytes()
            h.update(f"{rel}\0{len(data)}\0".encode("utf-8"))
            h.update(data)
    return h.hexdigest()


def cmd_sync_offline(args) -> int:
    if str(TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(TOOLS_DIR))
    import distributor_offline
    argv = ["--all", "--expected", str(args.expected), "--product", str(args.product)]
    if getattr(args, "fixtures", None):
        argv += ["--fixtures", str(args.fixtures)]
    return distributor_offline.main(argv)


# --- text oracle -----------------------------------------------------------------------------
# Freezes every --text/--audience/--stage/--compact rendering, every --help screen and every CLI
# exit code, so a render/argparse reshuffle that leaves the JSON untouched is still caught.

_STD_MODES = [("text", ["--text"]),
              ("text-designer", ["--text", "--audience", "designer"]),
              ("text-reviewer", ["--text", "--audience", "reviewer"]),
              ("text-manager", ["--text", "--audience", "manager"]),
              ("compact", ["--compact"])]
_MANAGER_MODES = [("text", ["--text"]), ("text-manager", ["--text", "--audience", "manager"])]

# (scope, cli, mode, extra args). Scopes: sch/pcb/gerber = one run per fixture of that kind;
# chain = one per directory holding both a schematic and a pcb; legacy/pcbpair = fixed diff pairs.
TEXT_RUNS = (
    [("sch", "analyze_schematic", m, a) for m, a in _STD_MODES + [("stage", ["--stage", "schematic"])]]
    + [("pcb", "analyze_pcb", m, a) for m, a in _STD_MODES + [("stage", ["--stage", "layout"]),
                                                              ("pcb-full-text", ["--full", "--text"])]]
    + [("gerber", "analyze_gerbers", m, a) for m, a in _STD_MODES + [("stage", ["--stage", "pre_fab"])]]
    + [("chain", cli, m, a) for cli in ("analyze_thermal", "analyze_emc", "cross_analysis")
       for m, a in _MANAGER_MODES + ([("compact", ["--compact"])] if cli == "analyze_emc" else [])]
    + [("sch", "diff_analysis", "diff-text", ["--text"]), ("sch", "diff_analysis", "diff-json", [])]
    + [("sch", "what_if", "suggest-text", ["--suggest-fixes", "--text"]),
       ("sch", "what_if", "suggest-json", ["--suggest-fixes"])]
    + [("sch", "summarize_findings", m, a) for m, a in (("table", []), ("json", ["--json"]),
                                                        ("confidence", ["--by-confidence"]),
                                                        ("warning", ["--severity", "warning"]))]
    + [("chain", "format-report", "report-md", [])]
    + [("legacy", "diff_analysis", "diff-text", ["--text"]), ("legacy", "diff_analysis", "diff-json", []),
       ("pcbpair", "diff_analysis", "diff-text", ["--text"])]
)
TEXT_SCRIPTS = {
    "analyze_schematic": ANALYZERS["schematic"], "analyze_pcb": ANALYZERS["pcb"],
    "analyze_gerbers": ANALYZERS["gerber"], "analyze_thermal": ANALYZERS["thermal"],
    "analyze_emc": ANALYZERS["emc"], "cross_analysis": ANALYZERS["cross_analysis"],
    "diff_analysis": "skills/kicad/scripts/diff_analysis.py", "what_if": "skills/kicad/scripts/what_if.py",
    "summarize_findings": "skills/kicad/scripts/summarize_findings.py",
    "format-report": "action/format-report.py",
}
NEG_MODES = {"noargs": [], "missing": ["./does-not-exist.kicad_sch"], "badflag": ["--no-such-flag"],
             "schema-noinput": ["--schema"]}
TEXT_BASE_SCH = "determinism__usb_dual_esd.kicad_sch"
LEGACY_A = TOOLS_DIR / "tests" / "fixtures" / "text" / "legacy_severity_a.json"
LEGACY_B = TOOLS_DIR / "tests" / "fixtures" / "text" / "legacy_severity_b.json"
TEXT_TIMEOUT = 120
_CRED_PREFIXES = ("DIGIKEY_", "MOUSER_", "ELEMENT14_", "LCSC_")


def _cli_stem(rel: str) -> str:
    return Path(rel).stem


def _cli_names() -> list[str]:
    return [_cli_stem(r) for rels in SKILL_CLIS.values() for r in rels]


def _slot_name(rel: str) -> str:
    return rel.replace("/", "__")


def text_artefact_names(sch: list[str], pcb: list[str], gerber: list[str], chain: list[str]) -> list[str]:
    """Artefact stems (no extension) for the given fixture slots, in TEXT_RUNS order."""
    slots = {"sch": sch, "pcb": pcb, "gerber": gerber, "chain": chain}
    names = []
    for scope, cli, mode, _ in TEXT_RUNS:
        if scope in slots:
            names.extend(f"{s}__{cli}__{mode}" for s in slots[scope])
        else:
            names.append(f"{scope}__{mode}")
    names += [f"help__{c}" for c in _cli_names()]
    for rel in (r for rels in SKILL_CLIS.values() for r in rels):
        names += [f"neg__{_cli_stem(rel)}__{m}" for m in NEG_MODES if m != "schema-noinput" or rel in SCHEMA_CLIS]
    return names


def mask_text(text: str, work: str, product: str) -> str:
    """Replace the volatile tokens of a captured run: dirs, run ids, timestamps, run-dir stamps, elapsed_s,
    hashes of generated JSON inputs, interpreter."""
    for root, token in sorted(((work, "<WORK>"), (product, "<PRODUCT>")), key=lambda t: -len(t[0])):
        for r in sorted({root, str(Path(root).resolve())}, key=len, reverse=True):
            text = text.replace(r, token)
    text = re.sub(r"\d{8}T\d{6}Z-[0-9a-f]{6}", "<RUN_ID>", text)
    text = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?", "<TS>", text)
    text = re.sub(r'("elapsed_s":\s*)-?\d+(\.\d+)?([eE][-+]?\d+)?', r"\1<ELAPSED>", text)
    text = re.sub(r", line \d+, in ", ", line <N>, in ", text)  # traceback frames
    text = re.sub(r"\d{4}-\d{2}-\d{2}_\d{4}", "<RUN_STAMP>", text)  # analysis run-dir name
    text = re.sub(r'(\.json"(?:\s*:|,\s*"sha256"\s*:)\s*")[0-9a-f]{64}"', r'\1<SHA256>"', text)  # hash of a generated analyzer JSON
    return re.sub(r"python3\.\d+", "python3", text)


def _text_env(seed: str) -> dict:
    env = analyzer_env(seed)
    for k in [k for k in env if k.startswith(_CRED_PREFIXES)]:
        del env[k]  # no credentials: a distributor CLI must fail offline, deterministically
    env["COLUMNS"] = "80"  # argparse wraps --help at the terminal width
    return env


def _text_exec(cmd: list[str], cwd: Path, env: dict, merge: bool = False) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              env=env, cwd=cwd, timeout=TEXT_TIMEOUT, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {TEXT_TIMEOUT}s\n"
    return proc.returncode, proc.stdout + (proc.stderr if merge else "")


def _chain_slots(fixtures: list[dict]) -> dict[str, tuple[str, str]]:
    """schematic slot -> (schematic slot, pcb slot) per directory holding both; the last one in
    sorted order wins, as in run_snapshot (chain outputs live in that schematic's slot)."""
    by_dir: dict = {}
    for fx in fixtures:
        if fx["kind"] in ("sch", "pcb"):
            by_dir.setdefault(str(fx["path"].parent), {})[fx["kind"]] = _slot_name(fx["rel"])
    return {v["sch"]: (v["sch"], v["pcb"]) for _, v in sorted(by_dir.items()) if "sch" in v and "pcb" in v}


def run_text_snapshot(fixtures_root: Path, snap_dir: Path, txt_out: Path, product_root: Path, env: dict) -> int:
    """Write masked `<name>.txt` + `<name>.exit` artefacts into txt_out; returns the artefact count.

    The JSON outputs of a prior run_snapshot into snap_dir feed the downstream CLIs. Scratch files
    (analysis dirs, markdown) live in a temp work dir so nothing but .txt/.exit lands in txt_out.
    """
    txt_out.mkdir(parents=True, exist_ok=True)
    for stale in [*txt_out.glob("*.txt"), *txt_out.glob("*.exit")]:
        stale.unlink()
    py = sys.executable
    fixtures = discover_fixtures(fixtures_root)
    count = 0
    with tempfile.TemporaryDirectory() as td:
        work = Path(td) / "work"
        snap = work / "snap"
        shutil.copytree(snap_dir, snap, ignore=shutil.ignore_patterns("*.txt", "*.exit"))
        cwd = work / "cwd"
        cwd.mkdir()
        legacy = [shutil.copy2(f, work / f.name) for f in (LEGACY_A, LEGACY_B)]  # tool-tree paths must not reach the output

        def emit(name: str, rc: int, text: str) -> None:
            nonlocal count
            (txt_out / f"{name}.txt").write_text(mask_text(text, str(work), str(product_root)),
                                                 encoding="utf-8", newline="")
            (txt_out / f"{name}.exit").write_text(f"{rc}\n", encoding="utf-8")
            count += 1

        def script(cli: str) -> str:
            return str(product_root / TEXT_SCRIPTS[cli])

        def jpath(slot: str, name: str) -> str:
            return str(snap / slot / name)

        chains = _chain_slots(fixtures)
        for scope, cli, mode, args in TEXT_RUNS:
            if scope in ("sch", "pcb", "gerber"):
                for fx in (f for f in fixtures if f["kind"] == scope):
                    slot = _slot_name(fx["rel"])
                    if cli in ("analyze_schematic", "analyze_pcb", "analyze_gerbers"):
                        cmd = [py, script(cli), str(fx["path"]), *args]
                    elif cli == "diff_analysis":
                        cmd = [py, script(cli), jpath(TEXT_BASE_SCH, "schematic.json"),
                               jpath(slot, "schematic.json"), *args]
                    elif cli == "what_if":
                        cmd = [py, script(cli), jpath(slot, "schematic.json"), *args]
                    else:  # summarize_findings reads an analysis dir written by one analyzer run
                        adir = work / "analysis" / slot
                        if not adir.exists():
                            _text_exec([py, script("analyze_schematic"), str(fx["path"]),
                                        "--analysis-dir", str(adir)], cwd, env)
                        cmd = [py, script(cli), str(adir), *args]
                    rc, out = _text_exec(cmd, cwd, env)
                    emit(f"{slot}__{cli}__{mode}", rc, out)
            elif scope == "chain":
                for slot, (sch_slot, pcb_slot) in sorted(chains.items()):
                    sj, pj = jpath(sch_slot, "schematic.json"), jpath(pcb_slot, "pcb.json")
                    if cli == "format-report":
                        outs = [work / f"{slot}.{k}.md" for k in ("pr", "full", "summary")]
                        cmd = [py, script(cli), "--schematic", sj, "--pcb", pj]
                        for flag, fn in (("--emc", "emc.json"), ("--thermal", "thermal.json")):
                            if (snap / sch_slot / fn).exists():
                                cmd += [flag, jpath(sch_slot, fn)]
                        for flag, o in zip(("--output", "--output-full", "--output-summary"), outs):
                            cmd += [flag, str(o)]
                        rc, _ = _text_exec(cmd, cwd, env)
                        out = "\n===\n".join(o.read_text(encoding="utf-8") if o.exists() else "" for o in outs)
                    else:
                        rc, out = _text_exec([py, script(cli), "--schematic", sj, "--pcb", pj, *args], cwd, env)
                    emit(f"{slot}__{cli}__{mode}", rc, out)
            elif scope == "legacy":
                rc, out = _text_exec([py, script(cli), str(legacy[0]), str(legacy[1]), *args], cwd, env)
                emit(f"legacy__{mode}", rc, out)
            else:  # pcbpair
                rc, out = _text_exec([py, script(cli), jpath("simple-project__simple.kicad_pcb", "pcb.json"),
                                      jpath("kh408__qfn_rotated.kicad_pcb", "pcb.json"), *args], cwd, env)
                emit(f"pcbpair__{mode}", rc, out)
        for rel in (r for rels in SKILL_CLIS.values() for r in rels):
            cli = _cli_stem(rel)
            rc, out = _text_exec([py, str(product_root / rel), "--help"], cwd, env)
            emit(f"help__{cli}", rc, out)
            for mode, args in NEG_MODES.items():
                if mode == "schema-noinput" and rel not in SCHEMA_CLIS:
                    continue
                if cli == "format-report" and mode == "missing":
                    args = ["--schematic", *args]
                rc, out = _text_exec([py, str(product_root / rel), *args], cwd, env, merge=True)
                emit(f"neg__{cli}__{mode}", rc, out)
    return count


def compare_text_dirs(base: Path, cand: Path) -> tuple[int, list[str]]:
    """Byte-compare every .txt/.exit in base against cand. Returns (artefacts in base, delta lines)."""
    def files(d: Path) -> dict:
        return {p.name: p for p in d.iterdir() if p.suffix in (".txt", ".exit")}
    b, c = files(base), files(cand)
    deltas = []
    for name in sorted(b):
        if name not in c:
            deltas.append(f"{name}: MISSING in candidate")
            continue
        bb, cb = b[name].read_bytes(), c[name].read_bytes()
        if bb != cb:
            bl, cl = bb.decode("utf-8", "replace").split("\n"), cb.decode("utf-8", "replace").split("\n")
            i = next((k for k in range(min(len(bl), len(cl))) if bl[k] != cl[k]), min(len(bl), len(cl)))
            deltas.append(f"{name}: line {i + 1}: base {bl[i] if i < len(bl) else '<EOF>'!r} "
                          f"| cand {cl[i] if i < len(cl) else '<EOF>'!r}")
    deltas += [f"{name}: EXTRA in candidate" for name in sorted(set(c) - set(b))]
    return len(b), deltas


def cmd_text_compare(args) -> int:
    for label, d in (("base", args.base), ("cand", args.cand)):
        if not Path(d).is_dir():
            print(f"text-compare: {label} directory not found: {d}", file=sys.stderr)
            return 2
    n, deltas = compare_text_dirs(Path(args.base), Path(args.cand))
    if not n:
        print(f"text-compare: base directory contains no artefacts: {args.base}", file=sys.stderr)
        return 2
    for d in deltas:
        print(d)
    print("text-compare: " + (f"FAIL ({len(deltas)} delta(s))" if deltas else f"OK ({n} artefacts)"))
    return 1 if deltas else 0


def cmd_quick(args) -> int:
    for flag, val in (("--baseline", args.baseline), ("--text-baseline", args.text_baseline)):
        if val and not args.fixtures:
            print(f"quick: {flag} requires --fixtures", file=sys.stderr)
            return 2
    if args.fixtures:
        msg = _check_inputs("quick", args.fixtures, args.product)
        if msg:
            print(msg, file=sys.stderr)
            return 2
    elif not Path(args.product).is_dir():
        print(f"quick: product is not a directory: {args.product}", file=sys.stderr)
        return 2
    checks = []
    snapshot_failures: list = []
    text_compare: dict = {}

    def timed(name, fn):
        t0 = time.time()
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = fn()
            status = "ok" if rc == 0 else "error" if rc == 2 else "fail"
            detail = buf.getvalue()
        except Exception as exc:  # a crashing sub-check must still yield a report
            rc, status = 1, "error"
            detail = buf.getvalue() + f"{type(exc).__name__}: {exc}\n"
        checks.append({"name": name, "status": status,
                       "elapsed_s": round(time.time() - t0, 1), "detail": detail})
        return 1 if rc else 0

    rc = 0
    ns = argparse.Namespace(product=args.product, update_baseline=False, moved_from=None)
    rc |= timed("imports", lambda: cmd_imports(ns))
    rc |= timed("tags", lambda: cmd_tags(ns))
    rc |= timed("install-smoke", lambda: cmd_install_smoke(argparse.Namespace(product=args.product, skill=None)))
    counts = None
    if args.fixtures:
        counts = {}
        for f in discover_fixtures(Path(args.fixtures)):
            counts[f["kind"]] = counts.get(f["kind"], 0) + 1
        det_ns = argparse.Namespace(fixtures=args.fixtures, product=args.product, policy=args.policy)
        rc |= timed("determinism", lambda: cmd_determinism(det_ns))
        snapshot_failures = list(getattr(det_ns, "snapshot_failures", []))
        rc |= timed("aba", lambda: cmd_aba(argparse.Namespace(
            fixtures=args.fixtures, product=args.product, policy=args.policy)))
        if args.baseline:
            def _cmp():
                msg = _check_base_dir(Path(args.baseline))
                if msg:
                    print(f"compare-vs-baseline: {msg}")
                    return 2
                with tempfile.TemporaryDirectory() as td:
                    stats = run_snapshot(Path(args.fixtures), Path(td), Path(args.product), analyzer_env("0"))
                    snapshot_failures[:] = stats["failures"]
                    rep = compare_dirs(Path(args.baseline), Path(td), load_policy(Path(args.policy)))
                bad = (rep["total_deltas"] or rep["missing_in_candidate"] or rep["extra_in_candidate"]
                       or stats["failures"])
                print("compare-vs-baseline: " + ("FAIL" if bad else "OK") + f" ({rep['total_deltas']} delta(s))")
                for rel in rep["missing_in_candidate"]:
                    print(f"   MISSING in candidate: {rel}")
                for rel in rep["extra_in_candidate"]:
                    print(f"   EXTRA in candidate: {rel}")
                for f in stats["failures"]:
                    print(f"   snapshot failure: {f}")
                for rel, ds in rep["files"].items():
                    for d in ds[:10]:
                        print(f"   {rel} {d[1]} {d[0]}: {d[2]!r} -> {d[3]!r}")
                return 1 if bad else 0
            rc |= timed("compare-vs-baseline", _cmp)
        rc |= timed("sync-offline", lambda: cmd_sync_offline(argparse.Namespace(
            expected=DISTRIBUTOR_EXPECTED, product=args.product, fixtures=args.fixtures)))
        if args.text_baseline:
            def _text_cmp():
                base = Path(args.text_baseline)
                if not base.is_dir():
                    print(f"text-compare: base directory not found: {base}")
                    text_compare.update(ok=False, artefacts=0, deltas=[f"base directory not found: {base}"])
                    return 2
                with tempfile.TemporaryDirectory() as td:
                    snap, txt = Path(td) / "snap", Path(td) / "txt"
                    run_snapshot(Path(args.fixtures), snap, Path(args.product), analyzer_env("0"))
                    run_text_snapshot(Path(args.fixtures), snap, txt, Path(args.product), _text_env("0"))
                    n, deltas = compare_text_dirs(base, txt)
                text_compare.update(ok=not deltas and n > 0, artefacts=n, deltas=deltas)
                print("text-compare: " + (f"FAIL ({len(deltas)} delta(s))" if deltas else f"OK ({n} artefacts)"))
                for d in deltas:
                    print(f"   {d}")
                return 1 if deltas or not n else 0
            rc |= timed("text-compare", _text_cmp)
    summary = {"product_sha": _git_sha(Path(args.product)), "fixtures_digest": _fixtures_digest(args.fixtures),
               "fixtures": counts, "snapshot_failures": snapshot_failures,
               "policy": Path(args.policy).name, "checks": checks, "status": "ok" if rc == 0 else "fail"}
    if text_compare:
        summary["text_compare"] = text_compare
    if args.json:
        print(json.dumps(summary, indent=1))
    else:
        for c in checks:
            if c["status"] != "ok":
                print(c["detail"], end="")
        print("quick: " + summary["status"].upper() + "  " + ", ".join(f"{c['name']}={c['status']}({c['elapsed_s']}s)" for c in checks))
    return rc


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
    s = sub.add_parser("snapshot", help="run analyzers over a fixture tree")
    s.add_argument("--fixtures", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--product", default=str(REPO_ROOT))
    s.add_argument("--seed", default="0", help="PYTHONHASHSEED value, or 'random'")
    s.set_defaults(func=cmd_snapshot)
    for name, fn in (("imports", cmd_imports), ("tags", cmd_tags)):
        q = sub.add_parser(name)
        q.add_argument("--product", default=str(REPO_ROOT))
        q.add_argument("--update-baseline", action="store_true")
        q.add_argument("--moved-from", action="append", metavar="FILE",
                       help="root-relative POSIX path of a file whose entries moved; with --update-baseline, "
                            "accept new entries whose shapes match entries retired from it")
        q.set_defaults(func=fn)
    i = sub.add_parser("install-smoke")
    i.add_argument("--product", default=str(REPO_ROOT))
    i.add_argument("--skill")
    i.set_defaults(func=cmd_install_smoke)
    d = sub.add_parser("determinism")
    d.add_argument("--fixtures", required=True)
    d.add_argument("--product", default=str(REPO_ROOT))
    d.add_argument("--policy", default=str(DEFAULT_POLICY))
    d.set_defaults(func=cmd_determinism)
    a = sub.add_parser("aba", help="in-process A/B/A state-leak check")
    a.add_argument("--fixtures", required=True)
    a.add_argument("--product", default=str(REPO_ROOT))
    a.add_argument("--policy", default=str(DEFAULT_POLICY))
    a.set_defaults(func=cmd_aba)
    so = sub.add_parser("sync-offline", help="distributor sync/fetch offline oracle")
    so.add_argument("--expected", default=str(DISTRIBUTOR_EXPECTED))
    so.add_argument("--product", default=str(REPO_ROOT))
    so.add_argument("--fixtures")
    so.set_defaults(func=cmd_sync_offline)
    tc = sub.add_parser("text-compare", help="byte-compare two text-artefact directories")
    tc.add_argument("base")
    tc.add_argument("cand")
    tc.set_defaults(func=cmd_text_compare)
    q = sub.add_parser("quick")
    q.add_argument("--fixtures")
    q.add_argument("--baseline")
    q.add_argument("--text-baseline", help="text-artefact directory to byte-compare against (needs --fixtures)")
    q.add_argument("--product", default=str(REPO_ROOT))
    q.add_argument("--policy", default=str(DEFAULT_POLICY))
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_quick)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
