"""One datasheet-sync driver over the provider adapters.

``sync_datasheets(provider, ...)`` takes a provider module (``provider_<p>.py``) that supplies
the identifier sets (``ID_KEYS``, ``KEY_PRIORITY``, ``SKIPPED_COUNTS_IDS``), the console
``LABELS``, ``DEFAULT_DELAY``, ``RENAME_PRESENT``, ``FAILED_DETAIL_WITH_URL`` and the hooks
``preflight``, ``authenticate``, ``sync_one_part`` and ``report_tail``. The driver reads the
parts (analyzer BOM or MPN list), decides which need a download, fetches them serially or on a
thread pool, records each outcome in ``manifest.json`` and prints the summary.

A ``not_found`` whose search failed in transport (``distributor_core.download`` records it) is
stored as ``error`` so the next run retries it, and an ``ok`` entry whose file is still on disk
is kept.

Imports ``distributor_core.inputs``/``manifest``/``download`` and the stdlib only; never a provider.
"""

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from distributor_core.download import take_transport_failure
from distributor_core.inputs import (
    _SKIP_TYPES,
    is_real_mpn,
    get_analyzer_output,
    extract_parts,
    load_mpn_list,
)
from distributor_core.manifest import (
    friendly_filename,
    MANIFEST_FILENAME,
    load_index,
    manifest_file_path,
    save_index,
)


def _outage_entry(result: dict, previous: dict, out_dir: Path) -> tuple[dict, dict]:
    """(entry to store, result to report) for one part. A ``not_found`` caused by a network
    failure, a rate limit or refused access is not an answer: report it as ``error`` (not a
    skipped previous failure, so the next run retries) and keep a previous ``ok`` entry whose
    file is still on disk."""
    outage = take_transport_failure()
    if outage is None or result.get("status") != "not_found":
        return result, result
    result = {**result, "status": "error", "error": outage}
    prev_file = manifest_file_path(out_dir, previous.get("file", ""))
    if previous.get("status") == "ok" and prev_file is not None and prev_file.is_file():
        return previous, result
    return result, result


class _Run:
    """State shared by the fetch workers: the manifest, its path and the outcome tallies."""

    def __init__(self, *, out_dir, index, index_path, source, total):
        self.out_dir = out_dir
        self.index = index
        self.index_path = index_path
        self.source = source
        self.total = total
        self.lock = threading.Lock()
        self.counter = 0
        self.downloaded = []
        self.failed = []
        self.kept_errors = {}  # part key -> error, for an outage that kept the previous ok entry
        self.warnings = []  # parts whose verification says the datasheet is probably wrong


def _record(ctx, part, outcome) -> None:
    """Store one part's outcome in the manifest, count it, print its progress line and save the
    index. Callers hold ``ctx.lock`` when several workers run."""
    part_key = part["_key"]
    stored, result = _outage_entry(outcome, ctx.index.get("parts", {}).get(part_key, {}), ctx.out_dir)
    ctx.index.setdefault("parts", {})[part_key] = stored
    if stored is not result:
        ctx.kept_errors[part_key] = result["error"]

    if result["status"] == "ok":
        ctx.downloaded.append(part_key)
        vconf = result.get("verification", "")
        vmark = ""
        if vconf == "wrong":
            vmark = " ⚠ WRONG DATASHEET?"
            ctx.warnings.append(part_key)
        elif vconf == "unverified":
            vmark = " (unverified)"
        print(f"  OK: {result['file']} ({result['size_bytes']:,} bytes){vmark}", file=sys.stderr)
    else:
        ctx.failed.append(part_key)
        print(f"  {result['status'].upper()}: {result.get('error', '')}", file=sys.stderr)

    ctx.index["schematic"] = ctx.source
    ctx.index["last_sync"] = datetime.now(timezone.utc).isoformat()
    save_index(ctx.index_path, ctx.index)


def sync_datasheets(
    provider,
    *,
    input_path: str | None = None,
    output_dir: str | None = None,
    force: bool = False,
    force_all: bool = False,
    delay: float | None = None,
    parallel: int = 1,
    dry_run: bool = False,
    as_json: bool = False,
    mpn_list: str | None = None,
    **provider_kwargs,
) -> dict:
    """Main sync function. Returns summary dict."""
    delay = provider.DEFAULT_DELAY if delay is None else delay
    if input_path is None and mpn_list is None:
        return {"error": "Must provide either input_path or mpn_list"}
    if input_path is not None and mpn_list is not None:
        return {"error": "Cannot provide both input_path and mpn_list"}

    pre = provider.preflight(**provider_kwargs)
    if "error" in pre:
        return {"error": pre["error"]}
    ctx = pre.get("ctx")

    # Determine output directory
    if output_dir:
        out_dir = Path(output_dir)
    elif input_path:
        out_dir = Path(input_path).resolve().parent / "datasheets"
    else:
        # MPN-list mode without explicit --output: use cwd/datasheets
        out_dir = Path.cwd() / "datasheets"
    # A datasheets/ link found in the project would send every write to its target;
    # only an explicit --output may point elsewhere.
    if not output_dir and out_dir.is_symlink():
        return {"error": f"{out_dir} is a symlink; pass --output to write datasheets there"}
    out_dir.mkdir(parents=True, exist_ok=True)

    index_path = out_dir / MANIFEST_FILENAME
    index = load_index(index_path)

    # Source parts: either analyzer BOM or plain MPN list
    if mpn_list:
        mpn_list_path = Path(mpn_list).resolve()
        print(f"Loading MPNs from {mpn_list_path.name}...", file=sys.stderr)
        parts = load_mpn_list(mpn_list_path, id_keys=provider.ID_KEYS)
        print(f"Loaded {len(parts)} unique MPNs", file=sys.stderr)
        skipped_no_id = 0
    else:
        resolved_input = Path(input_path).resolve()
        print(f"Analyzing {resolved_input.name}...", file=sys.stderr)
        analyzer_output = get_analyzer_output(resolved_input)
        if analyzer_output is None:
            return {"error": "Failed to analyze schematic"}

        # Extract parts with real MPNs
        parts = extract_parts(analyzer_output, id_keys=provider.ID_KEYS)
        all_bom = analyzer_output.get("bom", [])
        skipped_no_id = sum(
            1 for e in all_bom
            if not e.get("dnp") and e.get("type", "") not in _SKIP_TYPES
            and not is_real_mpn(e.get("mpn", ""))
            and not any(e.get(k, "").strip() for k in provider.SKIPPED_COUNTS_IDS)
        )

        print(provider.LABELS["found"].format(n=len(parts), k=skipped_no_id), file=sys.stderr)

    # Determine what needs processing
    to_download = []
    already_present = []
    skipped_failed = []

    for part in parts:
        # Use MPN as index key if available, otherwise distributor PN
        part_key = part["mpn"] or next((part.get(k, "") for k in provider.KEY_PRIORITY if part.get(k, "")), "")
        part["_key"] = part_key
        existing = index.get("parts", {}).get(part_key, {})
        status = existing.get("status", "")

        if status == "ok":
            old_file = existing.get("file", "")
            old_path = manifest_file_path(out_dir, old_file)
            if old_path is None and old_file:
                print(f"Warning: manifest entry {part_key} names a file outside {out_dir}; ignored",
                      file=sys.stderr)
            # Verify file still exists
            if old_path is not None and old_path.exists():
                if not force_all:
                    # Rename to friendly filename if the old name was plain MPN
                    if provider.RENAME_PRESENT and not dry_run:
                        desc = existing.get("description", "") or part.get("description", "")
                        mfg = existing.get("manufacturer", "") or part.get("manufacturer", "")
                        new_file = friendly_filename(part_key, desc, mfg) + ".pdf"
                        if new_file != old_file and not (out_dir / new_file).exists():
                            old_path.rename(out_dir / new_file)
                            existing["file"] = new_file
                            print(f"  Renamed: {old_file} -> {new_file}", file=sys.stderr)
                    already_present.append(part_key)
                    existing["references"] = part["references"]
                    continue
            # File missing — re-download

        if status in ("failed", "not_found", "no_datasheet") and not (force or force_all):
            skipped_failed.append(part_key)
            continue

        to_download.append(part)

    if dry_run:
        summary = {
            "would_download": [p["_key"] for p in to_download],
            "already_present": already_present,
            "skipped_previous_failures": skipped_failed,
            provider.LABELS["skipped_key"]: skipped_no_id,
        }
        if as_json:
            json.dump(summary, sys.stdout, indent=2)
        else:
            print(f"\nDry run — would download {len(to_download)} datasheets:")
            for p in to_download:
                print(f"  {p['_key']} ({p['manufacturer'] or 'unknown mfg'})")
            print(f"Already present: {len(already_present)}")
            print(f"Skipped (previous failures): {len(skipped_failed)}")
            print(provider.LABELS["dry_skipped"].format(k=skipped_no_id))
        return summary

    if not to_download:
        msg = f"All {len(already_present)} datasheets up to date."
        if skipped_failed:
            msg += f" {len(skipped_failed)} previous failures (use --force to retry)."
        print(msg, file=sys.stderr)
        # Still update the manifest (references may have changed)
        index["schematic"] = str(mpn_list or input_path)
        index["last_sync"] = datetime.now(timezone.utc).isoformat()
        save_index(index_path, index)
        return {"downloaded": 0, "already_present": len(already_present),
                "failed": len(skipped_failed)}

    # Get OAuth token
    auth = provider.authenticate()
    if "error" in auth:
        return {"error": auth["error"]}
    if auth.get("ctx") is not None:
        ctx = auth["ctx"]

    # Process each part
    run = _Run(out_dir=out_dir, index=index, index_path=index_path,
               source=str(mpn_list or input_path), total=len(to_download))

    def _fetch(part):
        take_transport_failure()
        return provider.sync_one_part(part, out_dir, index, delay, ctx)

    if parallel > 1:
        def _process_part(part):
            with run.lock:
                run.counter += 1
                n = run.counter
            print(f"[{n}/{run.total}] {part['_key']}", file=sys.stderr)
            outcome = _fetch(part)
            with run.lock:
                _record(run, part, outcome)

        with ThreadPoolExecutor(max_workers=parallel) as executor:
            for _ in executor.map(_process_part, to_download):
                pass
    else:
        for i, part in enumerate(to_download):
            print(f"[{i+1}/{run.total}] {part['_key']}", file=sys.stderr)
            _record(run, part, _fetch(part))

    downloaded, failed = run.downloaded, run.failed
    kept_errors, warnings = run.kept_errors, run.warnings

    # Summary
    summary = {
        "downloaded": len(downloaded),
        "already_present": len(already_present),
        "failed": len(failed),
        "verification_warnings": len(warnings),
        "skipped_previous_failures": len(skipped_failed),
        provider.LABELS["skipped_key"]: skipped_no_id,
        provider.LABELS["total_key"]: len(parts),
        "output_dir": str(out_dir),
        "index_path": str(index_path),
    }

    if as_json:
        json.dump(summary, sys.stdout, indent=2)
    else:
        print(f"\nDatasheet sync complete:", file=sys.stderr)
        print(f"  Downloaded: {len(downloaded)}", file=sys.stderr)
        if downloaded:
            for m in downloaded:
                print(f"    {m}", file=sys.stderr)
        if warnings:
            print(f"  Verification warnings: {len(warnings)}", file=sys.stderr)
            for m in warnings:
                entry = index["parts"].get(m, {})
                detail = entry.get("verification_details", "")
                print(f"    {m}: {detail}", file=sys.stderr)
        print(f"  Already present: {len(already_present)}", file=sys.stderr)
        print(f"  Failed: {len(failed)}", file=sys.stderr)
        if failed:
            for m in failed:
                entry = index["parts"].get(m, {})
                if m in kept_errors:
                    print(f"    {m} — {kept_errors[m]}", file=sys.stderr)
                    continue
                if provider.FAILED_DETAIL_WITH_URL:
                    url = entry.get("datasheet_url", "")
                    err = entry.get("error", "")
                    detail = f" — {url}" if url else f" — {err}"
                    print(f"    {m}{detail}", file=sys.stderr)
                else:
                    err = entry.get("error", "")
                    print(f"    {m} — {err}", file=sys.stderr)
        if skipped_failed:
            print(f"  Skipped (previous failures, use --force): "
                  f"{len(skipped_failed)}", file=sys.stderr)
        print(provider.LABELS["summary_skipped"].format(k=skipped_no_id), file=sys.stderr)
        print(f"  Output: {out_dir}/", file=sys.stderr)
        provider.report_tail(out_dir, downloaded, already_present, failed)

    return summary
