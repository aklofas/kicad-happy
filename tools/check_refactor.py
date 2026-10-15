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
import ast
import contextlib
import hashlib
import io
import json
import os
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

SKILL_CLIS = {
    "kicad": ["skills/kicad/scripts/analyze_schematic.py", "skills/kicad/scripts/analyze_pcb.py",
              "skills/kicad/scripts/analyze_gerbers.py", "skills/kicad/scripts/analyze_thermal.py",
              "skills/kicad/scripts/cross_analysis.py", "skills/kicad/scripts/diff_analysis.py",
              "skills/kicad/scripts/what_if.py", "skills/kicad/scripts/summarize_findings.py",
              "skills/kicad/review/scripts/deep_review_gate.py"],
    "datasheets": ["skills/datasheets/scripts/datasheet_verify.py", "skills/datasheets/scripts/plan_extraction.py"],
    "emc": ["skills/emc/scripts/analyze_emc.py"],
    "spice": ["skills/spice/scripts/simulate_subcircuits.py"],
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
    """Exact match (index-normalised), or a policy entry ending in `*` (not `[*]`) as a path prefix."""
    if not path:
        return False
    norm = _norm_path(path)
    if path in volatile or norm in volatile:
        return True
    return any(v.endswith("*") and not v.endswith("[*]") and (path.startswith(v[:-1]) or norm.startswith(v[:-1]))
               for v in volatile)


SNAP_TOKEN = "<SNAP>"


def _substitute_root(obj, root_str: str):
    """Rewrite dict keys and string values starting with root_str to start with <SNAP> instead."""
    if isinstance(obj, str):
        return SNAP_TOKEN + obj[len(root_str):] if obj.startswith(root_str) else obj
    if isinstance(obj, list):
        return [_substitute_root(x, root_str) for x in obj]
    if isinstance(obj, dict):
        return {_substitute_root(k, root_str): _substitute_root(v, root_str) for k, v in obj.items()}
    return obj


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
    base_root, cand_root = str(base_dir.resolve()), str(cand_dir.resolve())
    base_files = {p.relative_to(base_dir).as_posix(): p for p in base_dir.rglob("*.json")}
    cand_files = {p.relative_to(cand_dir).as_posix(): p for p in cand_dir.rglob("*.json")}
    for rel in sorted(base_files):
        if rel not in cand_files:
            report["missing_in_candidate"].append(rel)
            continue
        b = _substitute_root(json.loads(base_files[rel].read_text(encoding="utf-8")), base_root)
        c = _substitute_root(json.loads(cand_files[rel].read_text(encoding="utf-8")), cand_root)
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
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
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


def cmd_snapshot(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stats = run_snapshot(Path(args.fixtures), out, Path(args.product), analyzer_env(args.seed))
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


def scan_imports(root: Path) -> list[dict]:
    edges = []
    for p in _py_files(root):
        rel = p.relative_to(root).as_posix()
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
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


def scan_tags(root: Path) -> list[dict]:
    sites = []
    for p in _py_files(root):
        rel = p.relative_to(root).as_posix()
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
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


def _ratchet(current: list[dict], baseline_path: Path, update: bool, key_fields: tuple[str, ...], key_fn=None) -> int:
    def key(d): return key_fn(d) if key_fn else tuple(d[k] for k in key_fields)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else []
    base_keys = {key(d) for d in baseline}
    new = [d for d in current if key(d) not in base_keys]
    gone = len(base_keys - {key(d) for d in current})
    if new and update and not baseline_path.exists():
        new = []  # first generation of a baseline
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


def cmd_imports(args) -> int:
    rules = json.loads(LAYER_RULES.read_text(encoding="utf-8"))
    root = Path(args.product)
    v = classify_edges(scan_imports(root), rules, root)
    return _ratchet(v, IMPORT_BASELINE, args.update_baseline, (), key_fn=_import_key)


def cmd_tags(args) -> int:
    sites = scan_tags(Path(args.product))
    return _ratchet(sites, TAG_BASELINE, args.update_baseline, (), key_fn=_tag_key)


def install_smoke(product_root: Path, optional_skill: str | None, workdir: Path) -> list[str]:
    """Copy core skills (+ one optional skill) into workdir/plugin and run every CLI --help
    (and --schema for envelope CLIs) with cwd = an unrelated empty directory."""
    plugin = workdir / "plugin" / "skills"
    plugin.mkdir(parents=True)
    skills = ["kicad", "datasheets"] + ([optional_skill] if optional_skill else [])
    for sk in skills:
        shutil.copytree(product_root / "skills" / sk, plugin / sk,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    cwd = workdir / "elsewhere"
    cwd.mkdir()
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    failures = []
    clis = [c for sk in skills for c in SKILL_CLIS.get(sk, [])]
    for rel in clis:
        script = workdir / "plugin" / rel
        proc = subprocess.run([sys.executable, str(script), "--help"], cwd=cwd, env=env,
                              capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            failures.append(f"{rel} --help exit {proc.returncode}: {(proc.stderr or '').strip().splitlines()[-1:]}")
        if rel in SCHEMA_CLIS:
            proc = subprocess.run([sys.executable, str(script), "--schema"], cwd=cwd, env=env,
                                  capture_output=True, text=True, timeout=120)
            if proc.returncode != 0 or not proc.stdout.lstrip().startswith("{"):
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
    volatile = load_policy(Path(args.policy))
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        sa = run_snapshot(Path(args.fixtures), Path(a), Path(args.product), analyzer_env("random"))
        sb = run_snapshot(Path(args.fixtures), Path(b), Path(args.product), analyzer_env("random"))
        rep = compare_dirs(Path(a), Path(b), volatile)
    bad = rep["total_deltas"] or rep["missing_in_candidate"] or rep["extra_in_candidate"] or sa["failures"] != sb["failures"]
    print("determinism: " + ("FAIL" if bad else "OK") + f" ({rep['total_deltas']} delta(s))")
    for rel, ds in rep["files"].items():
        for d in ds[:10]:
            print(f"   {rel} {d[1]} {d[0]}")
    return 1 if bad else 0


def _git_sha(root: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    except OSError:
        return "unknown"


def _fixtures_digest(fixtures) -> str | None:
    if not fixtures:
        return None
    h = hashlib.sha256()
    for f in discover_fixtures(Path(fixtures)):
        st = f["path"].stat()
        h.update(f"{f['rel']}\0{st.st_size}\0{st.st_mtime_ns}\n".encode("utf-8"))
    return h.hexdigest()


def cmd_quick(args) -> int:
    checks = []

    def timed(name, fn):
        t0 = time.time()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = fn()
        checks.append({"name": name, "status": "ok" if rc == 0 else "fail",
                       "elapsed_s": round(time.time() - t0, 1), "detail": buf.getvalue()})
        return rc

    rc = 0
    ns = argparse.Namespace(product=args.product, update_baseline=False)
    rc |= timed("imports", lambda: cmd_imports(ns))
    rc |= timed("tags", lambda: cmd_tags(ns))
    rc |= timed("install-smoke", lambda: cmd_install_smoke(argparse.Namespace(product=args.product, skill=None)))
    if args.fixtures:
        rc |= timed("determinism", lambda: cmd_determinism(argparse.Namespace(
            fixtures=args.fixtures, product=args.product, policy=args.policy)))
        if args.baseline:
            def _cmp():
                with tempfile.TemporaryDirectory() as td:
                    run_snapshot(Path(args.fixtures), Path(td), Path(args.product), analyzer_env("0"))
                    rep = compare_dirs(Path(args.baseline), Path(td), load_policy(Path(args.policy)))
                bad = rep["total_deltas"] or rep["missing_in_candidate"] or rep["extra_in_candidate"]
                print("compare-vs-baseline: " + ("FAIL" if bad else "OK") + f" ({rep['total_deltas']} delta(s))")
                for rel, ds in rep["files"].items():
                    for d in ds[:10]:
                        print(f"   {rel} {d[1]} {d[0]}: {d[2]!r} -> {d[3]!r}")
                return 1 if bad else 0
            rc |= timed("compare-vs-baseline", _cmp)
    summary = {"product_sha": _git_sha(Path(args.product)), "fixtures_digest": _fixtures_digest(args.fixtures),
               "policy": Path(args.policy).name, "checks": checks, "status": "ok" if rc == 0 else "fail"}
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
    q = sub.add_parser("quick")
    q.add_argument("--fixtures")
    q.add_argument("--baseline")
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
