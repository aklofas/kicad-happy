#!/usr/bin/env python3
"""Offline oracle for the four distributor skills' sync/fetch scripts (v3 round 6).

Runs each provider's ``sync_datasheets`` and ``fetch_datasheet_<p>.main`` in
process over one shared BOM scenario, with the clock frozen, sleeps no-oped
and the network/PDF seams replaced by recorded fixtures
(``tools/tests/fixtures/distributor/responses/<provider>.json``). Each run
yields five artefacts (manifest.json, stdout.txt, stderr.txt, summary.json,
files.txt) that are compared byte-for-byte with the expected set frozen at
the pre-round tip.

Usage:
  distributor_offline.py --provider P --run R --out DIR      run one, write its artefacts
  distributor_offline.py --all --expected DIR                run everything, compare (exit 0/1)
  distributor_offline.py --all --write-expected DIR          run everything, (over)write the expected set

``--product`` selects the tree under test (default: this repo). The DigiKey
``sync-sch-dry`` run needs the harness fixtures (``--fixtures``, or
``$KH_FIXTURES``, default ``/tmp/harness-pin/tests/fixtures``) and is
skipped when ``simple-project/simple.kicad_sch`` is absent there.

Stdlib only.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as _dt
import importlib
import io
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from unittest import mock

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
FIXTURE_DIR = TOOLS_DIR / "tests" / "fixtures" / "distributor"
SCENARIO = FIXTURE_DIR / "scenario"
RESPONSES = FIXTURE_DIR / "responses"
DEFAULT_EXPECTED = FIXTURE_DIR / "expected"
DEFAULT_FX = "/tmp/harness-pin/tests/fixtures"
PROVIDERS = ("digikey", "mouser", "lcsc", "element14")
ARTEFACTS = ("manifest.json", "stdout.txt", "stderr.txt", "summary.json", "files.txt")
PDF_HEAD = b"%PDF-1.4\n"
PDF_TAIL = b"\n%%EOF\n"


class FrozenDatetime(_dt.datetime):
    """``datetime`` whose ``now()`` is 2026-10-16T00:00:00 (UTC when tz is given)."""

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls(2026, 10, 16)
        return cls(2026, 10, 16, tzinfo=_dt.timezone.utc).astimezone(tz)


class FakeTransport:
    """The provider's recorded responses: search listings, direct lookups, scrapes, downloads."""

    def __init__(self, responses: dict):
        self.responses = responses

    def _get(self, kind, key):
        hit = self.responses.get(kind, {}).get(key)
        return copy.deepcopy(hit)

    def search(self, query) -> dict | None:
        return self._get("search", query)

    def direct(self, code) -> dict | None:
        return self._get("direct", code)

    def scrape(self, url) -> str:
        return self.responses.get("scrape", {}).get(url, "")

    def download(self, url, output_path) -> bool:
        text = self.responses.get("downloads", {}).get(url)
        if not isinstance(text, str):
            return False
        with open(output_path, "wb") as f:
            f.write(PDF_HEAD + text.encode("utf-8") + PDF_TAIL)
        return True

    def extract_text(self, pdf_path, max_pages=3) -> str:
        try:
            with open(pdf_path, "rb") as f:
                raw = f.read()
        except OSError:
            return ""
        if not (raw.startswith(PDF_HEAD) and raw.endswith(PDF_TAIL)) or len(raw) < len(PDF_HEAD) + len(PDF_TAIL):
            return ""
        return raw[len(PDF_HEAD):-len(PDF_TAIL)].decode("utf-8")


# Where each seam is bound at this tip. A value is one "module.attr" target or a
# tuple of them (the same seam reached through more than one module).
# "alternatives" is documentation only: it is NOT stubbed (it calls download_pdf, which is).
PATCH_TARGETS: dict[str, dict[str, str | tuple[str, ...]]] = {
    "digikey": {
        "auth": "sync_datasheets_digikey.get_oauth_token",
        "search": "sync_datasheets_digikey.search_digikey_with_token",
        "download": ("sync_datasheets_digikey.download_pdf", "fetch_datasheet_digikey.download_pdf"),
        "alternatives": "sync_datasheets_digikey.try_alternative_sources",
        "extract_text": "fetch_datasheet_digikey._extract_pdf_text",
        "clock": "sync_datasheets_digikey.datetime",
        "sleep": "time.sleep",
        "fetch_search": "fetch_datasheet_digikey.search_digikey",
        "fetch_token": "fetch_datasheet_digikey._get_digikey_token",
    },
    "mouser": {
        "auth": ("sync_datasheets_mouser._get_api_key", "fetch_datasheet_mouser._get_api_key"),
        "search": "sync_datasheets_mouser.search_mouser",
        "scrape": ("sync_datasheets_mouser.scrape_product_page", "fetch_datasheet_mouser.scrape_product_page"),
        "download": ("sync_datasheets_mouser.download_pdf", "fetch_datasheet_mouser.download_pdf"),
        "alternatives": "sync_datasheets_mouser.try_alternative_sources",
        "extract_text": "fetch_datasheet_mouser._extract_pdf_text",
        "clock": "sync_datasheets_mouser.datetime",
        "sleep": "time.sleep",
        "fetch_search": "fetch_datasheet_mouser.search_mouser",
    },
    "lcsc": {
        "search": "sync_datasheets_lcsc.search_lcsc",
        "search_direct": "fetch_datasheet_lcsc.search_lcsc_direct",
        "download": ("sync_datasheets_lcsc.download_pdf", "fetch_datasheet_lcsc.download_pdf"),
        "alternatives": "sync_datasheets_lcsc.try_alternative_sources",
        "extract_text": "fetch_datasheet_lcsc._extract_pdf_text",
        "clock": "sync_datasheets_lcsc.datetime",
        "sleep": "time.sleep",
        "fetch_search": "fetch_datasheet_lcsc.search_lcsc",
    },
    "element14": {
        "search": "sync_datasheets_element14.search_element14",
        "download": ("sync_datasheets_element14.download_pdf", "fetch_datasheet_element14.download_pdf"),
        "alternatives": "sync_datasheets_element14.try_alternative_sources",
        "extract_text": "fetch_datasheet_element14._extract_pdf_text",
        "clock": "sync_datasheets_element14.datetime",
        "sleep": "time.sleep",
        "fetch_search": "fetch_datasheet_element14.search_element14",
    },
}
UNSTUBBED_ROLES = {"alternatives"}
# Environment the fetch CLIs read directly (element14's main() checks the key itself).
FETCH_ENV = {"element14": {"ELEMENT14_API_KEY": "KEY"}}
SYNC_KWARGS = {"element14": {"api_key": "KEY"}}

# run name -> spec. kind: sync | fetch. A key ending in " (digikey)" runs for DigiKey only and
# stores its artefacts under the name without that suffix.
RUNS: dict[str, dict] = {
    "sync-default": {"kind": "sync", "seed": "seed", "input": "bom"},
    "sync-dry-json": {"kind": "sync", "seed": "seed", "input": "bom", "kwargs": {"dry_run": True, "as_json": True}},
    "sync-force": {"kind": "sync", "seed": "seed", "input": "bom", "pre_run": True, "kwargs": {"force": True}},
    "sync-mpn-list": {"kind": "sync", "seed": None, "input": "mpns", "out": "ds"},
    "sync-legacy-index": {"kind": "sync", "seed": "seed-legacy", "input": "bom"},
    "sync-sch-dry (digikey)": {"kind": "sync", "seed": None, "input": "fx-sch", "kwargs": {"dry_run": True, "as_json": True}},
    "fetch-search-ok": {"kind": "fetch", "argv": ["--search", "LM358DR", "--json", "--output", "{work}/out.pdf"]},
    "fetch-search-nourl": {"kind": "fetch", "argv": ["--search", "NODATA1234", "--json"]},
    "fetch-search-miss": {"kind": "fetch", "argv": ["--search", "MISSING9999", "--json"]},
    "fetch-url-ok": {"kind": "fetch", "argv": ["https://www.ti.com/lit/ds/symlink/tps61023.pdf", "--json"]},
    "fetch-url-fail": {"kind": "fetch", "argv": ["https://example.com/nope.pdf", "--json"]},
}


@dataclass
class RunResult:
    manifest: bytes | None = None
    stdout: str = ""
    stderr: str = ""
    summary: dict | None = None
    files: list[str] = field(default_factory=list)
    exit_code: int | None = None


def run_dir_name(run: str) -> str:
    return run[:-len(" (digikey)")] if run.endswith(" (digikey)") else run


def runs_for(provider: str) -> list[str]:
    return [r for r in RUNS if not r.endswith(" (digikey)") or provider == "digikey"]


def _fx_root(fixtures: str | None) -> Path:
    return Path(fixtures or os.environ.get("KH_FIXTURES") or DEFAULT_FX)


def _fx_sch(fixtures: str | None) -> Path:
    return _fx_root(fixtures) / "simple-project" / "simple.kicad_sch"


def run_available(run: str, fixtures: str | None = None) -> bool:
    return RUNS[run].get("input") != "fx-sch" or _fx_sch(fixtures).is_file()


def _stub(role: str, transport: FakeTransport, provider: str):
    if role == "auth":
        return (lambda: ("TOKEN", "CID")) if provider == "digikey" else (lambda: "KEY")
    if role in ("search", "fetch_search"):
        return lambda query, *a, **k: transport.search(query)
    if role == "search_direct":
        return lambda code, *a, **k: transport.direct(code)
    if role == "scrape":
        return lambda url, *a, **k: transport.scrape(url)
    if role == "download":
        return lambda url, output_path, *a, **k: transport.download(url, output_path)
    if role == "extract_text":
        return transport.extract_text
    if role == "clock":
        return FrozenDatetime
    if role == "sleep":
        return lambda *a, **k: None
    if role == "fetch_token":
        return lambda *a, **k: "TOKEN"
    raise KeyError(role)


def _drop_provider_modules(product: Path) -> None:
    roots = [str((product / "skills" / p).resolve()) for p in PROVIDERS]
    roots.append(str((product / "skills" / "datasheets").resolve()))
    for name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None)
        if f and any(str(Path(f).resolve()).startswith(r + os.sep) for r in roots):
            del sys.modules[name]


@contextlib.contextmanager
def _provider_env(provider: str, product: Path, workdir: Path):
    """Import the provider's modules fresh, apply every seam patch, chdir into the work dir."""
    scripts = product / "skills" / provider / "scripts"
    saved_path, saved_cwd, saved_argv = list(sys.path), os.getcwd(), list(sys.argv)
    _drop_provider_modules(product)
    sys.path.insert(0, str(product / "skills" / "datasheets"))
    sys.path.insert(0, str(scripts))
    try:
        sync_mod = importlib.import_module(f"sync_datasheets_{provider}")
        fetch_mod = importlib.import_module(f"fetch_datasheet_{provider}")
        transport = FakeTransport(json.loads((RESPONSES / f"{provider}.json").read_text(encoding="utf-8")))
        with contextlib.ExitStack() as stack:
            for role, targets in PATCH_TARGETS[provider].items():
                if role in UNSTUBBED_ROLES:
                    continue
                for target in (targets,) if isinstance(targets, str) else targets:
                    stack.enter_context(mock.patch(target, _stub(role, transport, provider)))
            stack.enter_context(mock.patch.dict(os.environ, FETCH_ENV.get(provider, {})))
            os.chdir(workdir)
            yield sync_mod, fetch_mod
    finally:
        os.chdir(saved_cwd)
        sys.path[:] = saved_path
        sys.argv[:] = saved_argv
        _drop_provider_modules(product)


def _sync_call(sync_mod, provider: str, spec: dict, workdir: Path, fixtures: str | None) -> dict:
    out_dir = workdir / spec.get("out", "datasheets")
    kwargs = dict(SYNC_KWARGS.get(provider, {}))
    kwargs.update(spec.get("kwargs", {}))
    if spec["input"] == "mpns":
        kwargs["mpn_list"] = str(workdir / "mpns.txt")
    elif spec["input"] == "fx-sch":
        kwargs["input_path"] = str(_fx_sch(fixtures))
    else:
        kwargs["input_path"] = str(workdir / "bom.schematic.json")
    return sync_mod.sync_datasheets(output_dir=str(out_dir), **kwargs)


def _list_files(workdir: Path) -> list[str]:
    return sorted(f"{p.relative_to(workdir).as_posix()}:{p.stat().st_size}"
                  for p in workdir.rglob("*") if p.is_file())


def _prepare(spec: dict, workdir: Path) -> None:
    if spec.get("input") in ("bom", "mpns"):
        for name in ("bom.schematic.json", "mpns.txt"):
            shutil.copyfile(SCENARIO / name, workdir / name)
    if spec.get("seed"):
        shutil.copytree(SCENARIO / spec["seed"], workdir / spec.get("out", "datasheets"))


def run_sync(provider: str, run: str, workdir: Path, product: Path = REPO_ROOT, fixtures: str | None = None) -> RunResult:
    spec = RUNS[run]
    workdir = Path(workdir)
    _prepare(spec, workdir)
    res = RunResult()
    with _provider_env(provider, Path(product), workdir) as (sync_mod, _fetch):
        if spec.get("pre_run"):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                _sync_call(sync_mod, provider, {**spec, "kwargs": {}}, workdir, fixtures)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            res.summary = _sync_call(sync_mod, provider, spec, workdir, fixtures)
    res.stdout, res.stderr = out.getvalue(), err.getvalue()
    manifest = workdir / spec.get("out", "datasheets") / "manifest.json"
    res.manifest = manifest.read_bytes() if manifest.is_file() else None
    res.files = _list_files(workdir)
    return res


def run_fetch(provider: str, run: str, workdir: Path, product: Path = REPO_ROOT, fixtures: str | None = None) -> RunResult:
    spec = RUNS[run]
    workdir = Path(workdir)
    res = RunResult()
    argv = [a.replace("{work}", str(workdir)) for a in spec["argv"]]
    with _provider_env(provider, Path(product), workdir) as (_sync, fetch_mod):
        sys.argv[:] = [f"fetch_datasheet_{provider}.py"] + argv
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                fetch_mod.main()
                res.exit_code = 0
            except SystemExit as exc:
                res.exit_code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    res.stdout, res.stderr = out.getvalue(), err.getvalue()
    res.summary = {"exit_code": res.exit_code}
    res.files = _list_files(workdir)
    return res


def _scrub(text: str, roots: list[tuple[str, str]]) -> str:
    for root, label in roots:
        text = text.replace(json.dumps(root)[1:-1], label).replace(root, label)
    return text


def render(res: RunResult, workdir: Path, fixtures: str | None = None) -> dict[str, bytes]:
    """The five artefacts as bytes, with absolute work-dir / fixture paths replaced."""
    roots = []
    for p in {str(workdir), str(Path(workdir).resolve())}:
        roots.append((p, "<WORK>"))
    fx = _fx_root(fixtures)
    for p in {str(fx), str(fx.resolve())}:
        roots.append((p, "<FX>"))
    roots.sort(key=lambda r: -len(r[0]))
    arts = {
        "stdout.txt": _scrub(res.stdout, roots).encode("utf-8"),
        "stderr.txt": _scrub(res.stderr, roots).encode("utf-8"),
        "files.txt": ("\n".join(res.files) + "\n").encode("utf-8"),
    }
    if res.summary is not None:
        arts["summary.json"] = (_scrub(json.dumps(res.summary, indent=2, sort_keys=True), roots) + "\n").encode("utf-8")
    if res.manifest is not None:
        arts["manifest.json"] = _scrub(res.manifest.decode("utf-8"), roots).encode("utf-8")
    return arts


def execute(provider: str, run: str, product: Path = REPO_ROOT, fixtures: str | None = None) -> dict[str, bytes]:
    with tempfile.TemporaryDirectory(prefix="kh-distributor-") as td:
        work = Path(td).resolve()
        fn = run_sync if RUNS[run]["kind"] == "sync" else run_fetch
        res = fn(provider, run, work, product, fixtures)
        return render(res, work, fixtures)


def _first_diff(a: bytes, b: bytes) -> str:
    al, bl = a.decode("utf-8", "replace").splitlines(), b.decode("utf-8", "replace").splitlines()
    for i, (x, y) in enumerate(zip(al, bl)):
        if x != y:
            return f"line {i + 1}: expected {x!r} got {y!r}"
    if len(al) != len(bl):
        return f"line count: expected {len(al)} got {len(bl)}"
    return "bytes differ (line endings / trailing newline)"


def compare_run(provider: str, run: str, expected_dir, product: Path = REPO_ROOT, fixtures: str | None = None) -> list[str]:
    if not run_available(run, fixtures):
        return []
    exp = Path(expected_dir) / provider / run_dir_name(run)
    got = execute(provider, run, product, fixtures)
    diffs = []
    for name in ARTEFACTS:
        p = exp / name
        want = p.read_bytes() if p.is_file() else None
        have = got.get(name)
        if want is None and have is None:
            continue
        if want is None:
            diffs.append(f"{name}: unexpected artefact")
        elif have is None:
            diffs.append(f"{name}: missing artefact")
        elif want != have:
            diffs.append(f"{name}: {_first_diff(want, have)}")
    return diffs


def write_artefacts(arts: dict[str, bytes], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name in ARTEFACTS:
        p = out / name
        if name in arts:
            p.write_bytes(arts[name])
        elif p.exists():
            p.unlink()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="distributor_offline.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--product", default=str(REPO_ROOT))
    ap.add_argument("--fixtures", help="harness fixtures root (for the DigiKey sync-sch-dry run)")
    ap.add_argument("--provider", choices=PROVIDERS)
    ap.add_argument("--run", choices=list(RUNS))
    ap.add_argument("--out")
    ap.add_argument("--all", action="store_true")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--expected")
    g.add_argument("--write-expected")
    args = ap.parse_args(argv)
    product = Path(args.product)
    if args.all:
        if not (args.expected or args.write_expected):
            ap.error("--all needs --expected DIR or --write-expected DIR")
        n, bad = 0, 0
        for provider in PROVIDERS:
            for run in runs_for(provider):
                if not run_available(run, args.fixtures):
                    print(f"  skipped {provider}/{run}: fixtures absent")
                    continue
                n += 1
                if args.write_expected:
                    write_artefacts(execute(provider, run, product, args.fixtures),
                                    Path(args.write_expected) / provider / run_dir_name(run))
                    continue
                diffs = compare_run(provider, run, args.expected, product, args.fixtures)
                if diffs:
                    bad += 1
                    print(f"  {provider}/{run}: {diffs[0]}")
        if args.write_expected:
            print(f"wrote {n} runs to {args.write_expected}")
            return 0
        print(f"sync-offline: {'FAIL' if bad else 'OK'} ({n} runs" + (f", {bad} differ)" if bad else ")"))
        return 1 if bad else 0
    if not (args.provider and args.run and args.out):
        ap.error("give --provider P --run R --out DIR, or --all")
    if args.run.endswith(" (digikey)") and args.provider != "digikey":
        ap.error(f"{args.run} runs for digikey only")
    if not run_available(args.run, args.fixtures):
        print(f"{args.run}: fixtures absent", file=sys.stderr)
        return 2
    write_artefacts(execute(args.provider, args.run, product, args.fixtures), Path(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
