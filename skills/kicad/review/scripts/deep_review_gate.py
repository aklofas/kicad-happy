#!/usr/bin/env python3
"""Evidence gate for Deep Review findings (v2.0 spec §3.D).

One command, zero ceremony:

    python3 skills/kicad/review/scripts/deep_review_gate.py \
        analysis/deep_review.json --analysis-dir analysis/

1. Validates each finding against deep_review.schema.json
   (_mini_jsonschema; per-finding — invalid findings are quarantined,
   not fatal) plus the cross-field rule the mini validator can't
   express: >=1 design anchor AND >=1 evidence source.
2. Checks citations: components/nets/pins exist in the analyzer JSON
   (pins check the component ref only — a floating-pin finding
   legitimately cites a pin on no net); the cited datasheet page
   contains the quote (pdftotext when available; missing tool or PDF
   -> evidence_checked=partial, never quarantine); computation script
   paths resolve against --project-dir.
3. Stamps finding_ids (assign_deep_review_ids), mirrors evidence
   anchors to top-level components/nets/pins, canonical-sorts, writes
   back. Re-evaluates quarantined[] so corrected findings promote.
4. Failures land in quarantined[] with quarantine_reason — visible,
   never silently dropped.

Exit codes: 0 all verified; 1 >=1 quarantined; 2 I/O or top-level
shape error. Stdlib-only; pdftotext (poppler) optional.
"""
import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))   # skills/kicad/scripts

from _mini_jsonschema import iter_errors            # noqa: E402
from analysis_cache import get_run                  # noqa: E402
from finding_schema import assign_deep_review_ids   # noqa: E402

SCHEMA_PATH = (Path(__file__).resolve().parents[1] / "schemas"
               / "deep_review.schema.json")

ANCHOR_KEYS = ("components", "nets", "pins")


def resolve_run_dir(analysis_dir, run_id=None):
    """The run folder analysis/manifest.json names ('current' unless
    `run_id` is given), confined to a folder directly inside
    `analysis_dir`; `analysis_dir` itself for a flat layout or an
    unreadable manifest."""
    analysis_dir = Path(analysis_dir)
    manifest = analysis_dir / "manifest.json"
    if manifest.is_file():
        try:
            m = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            m = None
        if isinstance(m, dict) and isinstance(m.get("runs"), dict):
            run = get_run(str(analysis_dir), run_id or m.get("current"), m)
            if run and Path(run[0]).is_dir():
                return Path(run[0])
    return analysis_dir


def load_anchor_sets(analysis_dir, run_id=None):
    """Component refs + net identities from the analyzer JSON.

    Resolves the run dir via analysis/manifest.json ('current' unless
    --run given); falls back to a flat analysis dir (schematic.json /
    pcb.json directly inside it) for ad-hoc layouts.
    A physical net carries up to three identities (KH-347): schematic
    internal name, annotated display_name, PCB net name. All three are
    accepted as citations.
    Returns (components: set[str], nets: set[str]).
    """
    run_dir = resolve_run_dir(analysis_dir, run_id)
    comps, nets = set(), set()
    sch = run_dir / "schematic.json"
    if sch.is_file():
        data = json.loads(sch.read_text(encoding="utf-8"))
        for c in data.get("components") or []:
            if isinstance(c, dict) and c.get("reference"):
                comps.add(str(c["reference"]).upper())
        for name, info in (data.get("nets") or {}).items():
            nets.add(str(name).upper())
            if isinstance(info, dict) and info.get("display_name"):
                nets.add(str(info["display_name"]).upper())
    pcb = run_dir / "pcb.json"
    if pcb.is_file():
        data = json.loads(pcb.read_text(encoding="utf-8"))
        for fp in data.get("footprints") or []:
            if isinstance(fp, dict) and fp.get("reference"):
                comps.add(str(fp["reference"]).upper())
        net_map = data.get("nets")
        if isinstance(net_map, dict):
            nets.update(str(v).upper() for v in net_map.values() if v)
        name_map = data.get("net_name_to_id")
        if isinstance(name_map, dict):
            nets.update(str(k).upper() for k in name_map if k)
    return comps, nets


def write_text_atomic(path, text):
    """Write UTF-8 text through a temp file beside `path`; an existing file
    keeps its mode, a new one gets the umask mode."""
    path = Path(path)
    try:
        mode = path.stat().st_mode & 0o7777
    except OSError:
        mode = None
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_BINARY", 0))
    while True:
        tmp = path.parent / f".{path.name}.{secrets.token_hex(6)}.tmp"
        try:
            # 0o666 lets the kernel apply the umask to a new file
            fd = os.open(tmp, flags, 0o666 if mode is None else 0o600)
            break
        except FileExistsError:
            continue
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def check_anchors(ev, comps, nets):
    fails = []
    for ref in ev.get("components") or []:
        if str(ref).upper() not in comps:
            fails.append(f"component {ref} not found in analyzer JSON")
    for net in ev.get("nets") or []:
        if str(net).upper() not in nets:
            fails.append(f"net {net} not found in analyzer JSON")
    for pin in ev.get("pins") or []:
        ref = str(pin).rsplit(".", 1)[0]
        if ref.upper() not in comps:
            fails.append(f"pin {pin}: component {ref} not found in analyzer JSON")
    return fails


def find_pdf(datasheets_dir, mpn):
    d = Path(datasheets_dir)
    if not d.is_dir():
        return None
    sanitized = re.sub(r"[^A-Za-z0-9_.-]", "_", mpn.strip())
    direct = d / f"{sanitized}.pdf"
    if direct.is_file():
        return direct
    lowered = sanitized.lower()
    for p in sorted(d.glob("*.pdf")):
        if p.stem.lower() == lowered:
            return p
    return None


_DASH_RE = re.compile("[\u2212\u2013\u2010\u2011]")
# One token per comparison operator or per run of letters/digits. A run
# keeps a decimal point or comma between digits ("5.5", "1,000") and a
# leading minus that starts a number outside a word ("-40", "(−40"; not
# "SOT-23" or "3.3-5.5"). Unit letters such as µ and ω are letters.
_TOKEN_RE = re.compile(
    r"<=|>=|±|<|>|="
    r"|(?:(?<![0-9a-z.])-(?=[0-9]))?"
    r"(?:[^\W_]|(?<=[0-9])[.,](?=[0-9]))+")


def _norm_text(s):
    # NFKC folds ligatures/fullwidth forms and µ into μ; other symbols and
    # punctuation (degree signs, dashes, curly quotes) are word breaks.
    s = unicodedata.normalize("NFKC", s).lower()
    s = s.replace("+/-", "±").replace("+-", "±").replace("≤", "<=").replace("≥", ">=")
    s = _DASH_RE.sub("-", s)
    return " ".join(_TOKEN_RE.findall(s))


def _squash(s):
    # Two numbers side by side stay apart: "0.9 1.0" is not "0.91.0".
    return re.sub(r"(?<=[0-9]) (?=[-0-9])", "|", _norm_text(s)).replace(" ", "")


_ELISION_RE = re.compile(r"\.\.\.|…")


def _quote_segments(quote):
    """Split a (possibly elided) quote into segments on '...' / '…'.
    Must run BEFORE normalization -- _norm_text collapses elision
    markers into a plain word break, destroying the split points."""
    return [s for s in _ELISION_RE.split(quote) if s.strip()]


def _segments_match(segments, norm_fn, text):
    """True if every segment appears in `text` (normalized via
    `norm_fn`), in order -- each search starts where the previous
    segment's match ended (KH-385). Normalized segments match whole
    tokens; squashed ones may not start or end inside a number."""
    t = norm_fn(text)
    if norm_fn is _norm_text:
        t = f" {t} "
    pos = 0
    for seg in segments:
        q = norm_fn(seg)
        if not q:
            continue
        if norm_fn is _norm_text:
            q = f" {q} "
            idx = t.find(q, pos)
        else:
            idx = _find_outside_numbers(t, q, pos)
        if idx == -1:
            return False
        pos = idx + len(q)
        if norm_fn is _norm_text:
            pos -= 1    # the closing space opens the next token
    return True


def _find_outside_numbers(t, q, pos):
    idx = t.find(q, pos)
    while idx != -1:
        before = t[idx - 1] if idx else ""
        after = t[idx + len(q):idx + len(q) + 1]
        inside = ((q[0].isdigit() and before and (before.isdigit() or before in ".-"))
                  or (q[0] == "." and before.isdigit())
                  or (q[-1].isdigit() and after and (after.isdigit() or after == ".")))
        if not inside:
            return idx
        idx = t.find(q, idx + 1)
    return -1


def _quote_in_text(quote, text):
    """Containment tolerant of case, whitespace, punctuation, Unicode
    variants, PDF line-wrap hyphenation (KH-347), and mid-quote elision
    ("..."/"…", KH-385) -- each segment between elision markers
    must appear in the text in order. The squashed fallback absorbs
    boundary shifts ("5.5V" vs "5.5 V", "over-\\nvoltage" vs
    "overvoltage"). Numbers, signs, decimal points, comparison
    operators and unit letters must match; a quote with no letter or
    digit matches nothing."""
    segments = _quote_segments(quote) or [quote]
    if not any(re.search(r"\w", _norm_text(s)) for s in segments):
        return False
    return (_segments_match(segments, _norm_text, text)
            or _segments_match(segments, _squash, text))


def _nearest_match(quote, text, window=80, stride=40):
    """Deterministic nearest-match hint for a quarantined datasheet
    quote (KH-385): locates the earliest elision segment that fails to
    match (by the same in-order rule as `_quote_in_text`), then scores
    `window`-char slices of the normalized text at a fixed `stride`
    against it via difflib.SequenceMatcher.ratio(). First-best wins on
    ties (replacement requires a strictly higher ratio)."""
    segments = _quote_segments(quote) or [quote]
    t = _norm_text(text)
    pos = 0
    missing = None
    for seg in segments:
        q = _norm_text(seg)
        if not q:
            continue
        idx = t.find(q, pos)
        if idx == -1:
            missing = q
            break
        pos = idx + len(q)
    if missing is None:
        missing = _norm_text(segments[0])
    if len(t) <= window:
        return t
    best_ratio, best = -1.0, t[:window]
    for i in range(0, len(t) - window + 1, stride):
        candidate = t[i:i + window]
        ratio = SequenceMatcher(None, missing, candidate).ratio()
        if ratio > best_ratio:
            best_ratio, best = ratio, candidate
    return best


def check_datasheet(cites, datasheets_dir):
    """Returns (failures, partial). Missing tool/PDF -> partial, not failure."""
    fails, partial = [], False
    have_tool = shutil.which("pdftotext") is not None
    for cite in cites or []:
        quote = cite.get("quote", "")
        page = cite.get("page")
        if not re.search(r"\w", _norm_text(quote)):
            fails.append(f'quote "{quote[:80]}" has no letter or digit to check')
            continue
        if page is not None and page < 1:
            fails.append(f"page {page} is not a page number (1 or more)")
            continue
        pdf = find_pdf(datasheets_dir, cite.get("mpn", "")) if have_tool else None
        if pdf is None:
            partial = True
            continue
        cmd = ["pdftotext"]
        if page is not None:
            cmd += ["-f", str(page), "-l", str(page)]
        cmd += [str(pdf), "-"]
        try:
            proc = subprocess.run(cmd, capture_output=True, encoding="utf-8",
                                  errors="replace")
        except OSError:
            partial = True
            continue
        # pdftotext exits 99 with "Wrong page range given" past the last page
        if page is not None and proc.returncode == 99 and "page" in proc.stderr.lower():
            fails.append(f"page {page} is past the end of {pdf.name}")
            continue
        if proc.returncode != 0:
            partial = True
            continue
        text = proc.stdout
        if not _quote_in_text(quote, text):
            where = f"page {page} of" if page else "anywhere in"
            reason = f'quote not found {where} {pdf.name}: "{quote[:80]}"'
            nearest = _nearest_match(quote, text)
            if nearest:
                reason += f'; nearest match: "...{nearest}..."'
            fails.append(reason)
    return fails, partial


def check_computation(comp, project_dir):
    fails = []
    script = (comp or {}).get("script")
    if script and not (Path(project_dir) / script).is_file():
        fails.append(f"computation script not found: {script}")
    return fails


def gate_finding(finding, item_schema, comps, nets, datasheets_dir, project_dir):
    """Returns (kept_finding | None, quarantined_finding | None)."""
    # Strip all gate-stamped output fields so re-runs produce identical key order.
    _GATE_FIELDS = frozenset(
        ("quarantine_reason", "evidence_checked", "finding_id",
         "components", "nets", "pins"))
    f = {k: v for k, v in finding.items() if k not in _GATE_FIELDS}
    fails = [e.message for e in iter_errors(f, item_schema)]
    ev = f.get("evidence") or {}
    if not isinstance(ev, dict):
        ev = {}     # the schema error above already names it
    has_anchor = any(ev.get(k) for k in ANCHOR_KEYS)
    has_source = bool(ev.get("datasheet")) or bool(ev.get("computation"))
    if not has_anchor:
        fails.append("no design anchor: evidence must cite >=1 component/net/pin")
    if not has_source:
        fails.append("no evidence source: evidence must carry a datasheet "
                     "quote and/or a computation")
    partial = False
    if not fails:
        fails += check_anchors(ev, comps, nets)
        ds_fails, partial = check_datasheet(ev.get("datasheet"), datasheets_dir)
        fails += ds_fails
        fails += check_computation(ev.get("computation"), project_dir)
    if fails:
        q = dict(finding)
        q["quarantine_reason"] = "; ".join(fails)
        return None, q
    f["evidence_checked"] = "partial" if partial else "full"
    for key in ANCHOR_KEYS:
        if ev.get(key):
            f[key] = list(ev[key])
    return f, None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("deep_review_json")
    ap.add_argument("--analysis-dir", required=True)
    ap.add_argument("--run", default=None, help="run id (default: manifest current)")
    ap.add_argument("--datasheets-dir", default="datasheets")
    ap.add_argument("--project-dir", default=None,
                     help="project root for resolving computation script "
                          "paths (default: --analysis-dir's parent)")
    args = ap.parse_args()
    project_dir = args.project_dir
    if project_dir is None:
        # analysis/ conventionally lives directly inside the project
        # root (KH-384) -- anchor to it, not the invoking cwd, so the
        # gate works when run from elsewhere.
        project_dir = str(Path(args.analysis_dir).resolve().parent)

    path = Path(args.deep_review_json)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"deep_review_gate: cannot load inputs: {e}", file=sys.stderr)
        return 2
    top_required = ("schema_version", "produced_for_run_id", "produced_at",
                    "findings", "quarantined")
    if not isinstance(doc, dict) or not all(k in doc for k in top_required):
        print("deep_review_gate: top-level shape invalid "
              f"(required keys: {', '.join(top_required)})", file=sys.stderr)
        return 2
    for key in ("findings", "quarantined"):
        if doc[key] is not None and not isinstance(doc[key], list):
            print(f"deep_review_gate: top-level shape invalid ({key} must be an array)",
                  file=sys.stderr)
            return 2

    comps, nets = load_anchor_sets(args.analysis_dir, args.run)
    item_schema = schema["properties"]["findings"]["items"]

    kept, quarantined = [], []
    candidates = list(doc.get("findings") or []) + list(doc.get("quarantined") or [])
    for finding in candidates:
        if not isinstance(finding, dict):
            quarantined.append({"quarantine_reason": "not a JSON object",
                                "value": finding})
            continue
        ok, bad = gate_finding(finding, item_schema, comps, nets,
                               args.datasheets_dir, project_dir)
        if ok is not None:
            kept.append(ok)
        else:
            quarantined.append(bad)

    assign_deep_review_ids(kept)
    kept.sort(key=lambda f: (f.get("category", ""), f.get("finding_id", "")))
    quarantined.sort(key=lambda f: (str(f.get("category", "")),
                                    str(f.get("summary", ""))))
    doc["findings"] = kept
    doc["quarantined"] = quarantined
    write_text_atomic(path, json.dumps(doc, indent=2) + "\n")

    n_partial = sum(1 for f in kept if f.get("evidence_checked") == "partial")
    print(f"deep_review gate: {len(kept)} verified "
          f"({n_partial} partial), {len(quarantined)} quarantined")
    return 1 if quarantined else 0


if __name__ == "__main__":
    sys.exit(main())
