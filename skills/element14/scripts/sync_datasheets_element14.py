#!/usr/bin/env python3
"""Sync a local datasheets directory for a KiCad project via element14 (Newark/Farnell).

Extracts components with MPNs or distributor PNs from a KiCad schematic (or
pre-computed analyzer JSON), searches the element14 Product Search API for
datasheet URLs, downloads missing PDFs, and maintains a manifest.json file
(legacy name index.json still read for backward compat).

The manifest.json format matches across distributor skills so they can
contribute to the same datasheets directory. The source field
distinguishes which distributor provided the datasheet.

Download strategy per part:
  1. Try the datasheet URL from the schematic itself
  2. Search element14 API → download from farnell.com CDN (direct PDF URL)
  3. Try manufacturer-specific alternative URL patterns

Usage:
    python3 sync_datasheets_element14.py <file.kicad_sch>
    python3 sync_datasheets_element14.py <analyzer_output.json> --output ./datasheets
    python3 sync_datasheets_element14.py <file.kicad_sch> --force     # retry failures
    python3 sync_datasheets_element14.py <file.kicad_sch> --dry-run   # preview only
    python3 sync_datasheets_element14.py <file.kicad_sch> --store uk.farnell.com
    python3 sync_datasheets_element14.py --mpn-list mpns.txt --dry-run
    python3 sync_datasheets_element14.py --mpn-list mpns.txt --output ./datasheets

Environment:
    ELEMENT14_API_KEY — required (free from partner.element14.com)

Dependencies:
    - requests (pip install requests) — strongly recommended
    - playwright (pip install playwright && playwright install chromium) — optional
"""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

# Import from sibling script (same skill)
sys.path.insert(0, str(Path(__file__).parent))
import _core_path  # noqa: F401
from fetch_datasheet_element14 import (
    download_pdf,
    try_alternative_sources,
    verify_datasheet,
    search_element14,
    _get_datasheet_url,
    _get_mpn,
    _get_sku,
    _get_manufacturer,
    _get_description,
    _DEFAULT_STORE,
)
from distributor_core.inputs import (
    _GENERIC_VALUE_RE,
    _SKIP_TYPES,
    is_real_mpn,
    get_analyzer_output,
    extract_parts as _extract_parts_core,
    load_mpn_list as _load_mpn_list_core,
)
from distributor_core.manifest import (
    sanitize_filename,
    friendly_filename,
    MANIFEST_FILENAME,
    LEGACY_MANIFEST_FILENAME,
    _manifest_path,
    load_index,
    save_index,
)

# Identifier keys projected from the BOM, in the order this provider's part dicts carry them.
ID_KEYS = ("element14", "digikey", "mouser", "lcsc")


def extract_parts(analyzer_output):
    return _extract_parts_core(analyzer_output, id_keys=ID_KEYS)


def load_mpn_list(path):
    return _load_mpn_list_core(path, id_keys=ID_KEYS)



# ---------------------------------------------------------------------------
# Core sync logic
# ---------------------------------------------------------------------------

def sync_one_part(
    part: dict,
    output_dir: Path,
    index: dict,
    delay: float,
    api_key: str,
    store: str,
) -> dict:
    """Download datasheet for one part. Returns updated manifest entry."""
    mpn = part["mpn"]
    element14_pn = part.get("element14", "")
    now = datetime.now(timezone.utc).isoformat()

    # Use MPN for display/filename if available, otherwise element14 PN
    display_pn = mpn or element14_pn

    desc = part.get("description", "")
    mfg = part.get("manufacturer", "")
    filename = friendly_filename(display_pn, desc, mfg) + ".pdf"
    output_path = output_dir / filename

    # Strategy 1: Try the datasheet URL from the schematic itself
    schematic_url = part.get("datasheet", "")
    if schematic_url and schematic_url != "~" and "://" in schematic_url:
        print(f"  Trying schematic URL...", file=sys.stderr)
        if download_pdf(schematic_url, str(output_path)):
            size = os.path.getsize(str(output_path))
            vr = verify_datasheet(str(output_path), display_pn, desc, mfg)
            if vr["confidence"] == "wrong":
                print(f"  WARNING: PDF may be wrong datasheet — {vr['details']}",
                      file=sys.stderr)
            result = {
                "file": filename,
                "manufacturer": mfg,
                "description": desc,
                "value": part["value"],
                "datasheet_url": schematic_url,
                "downloaded_date": now,
                "source": "schematic",
                "status": "ok",
                "references": part["references"],
                "size_bytes": size,
                "verification": vr["confidence"],
            }
            if vr["confidence"] == "wrong":
                result["verification_details"] = vr["details"]
            return result

    # Strategy 2: Search element14 API
    # Prefer MPN search (most reliable), fall back to element14 SKU
    search_term = mpn or element14_pn
    time.sleep(delay)
    print(f"  Searching element14 for '{search_term}'...", file=sys.stderr)
    product = search_element14(search_term, api_key, store)

    # If MPN search failed but we have an element14 PN, try that
    if product is None and mpn and element14_pn:
        time.sleep(delay)
        print(f"  MPN not found, trying SKU '{element14_pn}'...", file=sys.stderr)
        product = search_element14(element14_pn, api_key, store)

    if product is not None:
        ds_url = _get_datasheet_url(product)
        e14_mpn = _get_mpn(product)
        e14_mfg = _get_manufacturer(product) or mfg
        e14_desc = _get_description(product) or desc
        e14_sku = _get_sku(product)

        # Use the richer element14 data for filename
        effective_pn = e14_mpn or display_pn
        if e14_desc:
            filename = friendly_filename(effective_pn, e14_desc, e14_mfg) + ".pdf"
            output_path = output_dir / filename

        if ds_url:
            print(f"  Downloading from element14...", file=sys.stderr)
            if download_pdf(ds_url, str(output_path)):
                size = os.path.getsize(str(output_path))
                vr = verify_datasheet(str(output_path), effective_pn, e14_desc, e14_mfg)
                if vr["confidence"] == "wrong":
                    print(f"  WARNING: PDF may be wrong datasheet — {vr['details']}",
                          file=sys.stderr)
                result = {
                    "file": filename,
                    "manufacturer": e14_mfg,
                    "description": e14_desc,
                    "value": part["value"],
                    "datasheet_url": ds_url,
                    "downloaded_date": now,
                    "source": "element14",
                    "element14": e14_sku,
                    "status": "ok",
                    "references": part["references"],
                    "size_bytes": size,
                    "verification": vr["confidence"],
                }
                if vr["confidence"] == "wrong":
                    result["verification_details"] = vr["details"]
                return result

    # Strategy 3: Try alternative manufacturer sources
    if mpn:
        print(f"  Trying alternative sources...", file=sys.stderr)
        if try_alternative_sources(mpn, str(output_path)):
            size = os.path.getsize(str(output_path))
            vr = verify_datasheet(str(output_path), mpn, desc, mfg)
            result = {
                "file": filename,
                "manufacturer": mfg,
                "description": desc,
                "value": part["value"],
                "datasheet_url": "",
                "downloaded_date": now,
                "source": "alternative",
                "status": "ok",
                "references": part["references"],
                "size_bytes": size,
                "verification": vr["confidence"],
            }
            if vr["confidence"] == "wrong":
                result["verification_details"] = vr["details"]
            return result

    if product is None:
        return {
            "manufacturer": mfg,
            "description": desc,
            "value": part["value"],
            "references": part["references"],
            "status": "not_found",
            "error": f"No element14 results for '{search_term}'"
                     + (f" or '{element14_pn}'" if mpn and element14_pn else ""),
            "last_attempt": now,
        }

    return {
        "manufacturer": mfg,
        "description": desc,
        "value": part["value"],
        "references": part["references"],
        "status": "failed",
        "error": "No datasheet URL or all download methods failed",
        "last_attempt": now,
    }


def sync_datasheets(
    input_path: str | None = None,
    output_dir: str | None = None,
    force: bool = False,
    force_all: bool = False,
    delay: float = 0.5,
    parallel: int = 1,
    dry_run: bool = False,
    as_json: bool = False,
    api_key: str = "",
    store: str = _DEFAULT_STORE,
    mpn_list: str | None = None,
) -> dict:
    """Main sync function. Returns summary dict."""
    if input_path is None and mpn_list is None:
        return {"error": "Must provide either input_path or mpn_list"}
    if input_path is not None and mpn_list is not None:
        return {"error": "Cannot provide both input_path and mpn_list"}

    if not api_key:
        api_key = os.environ.get("ELEMENT14_API_KEY", "")
    if not api_key:
        print("Error: ELEMENT14_API_KEY not set", file=sys.stderr)
        return {"error": "ELEMENT14_API_KEY not set"}

    if output_dir:
        out_dir = Path(output_dir)
    elif input_path:
        out_dir = Path(input_path).resolve().parent / "datasheets"
    else:
        out_dir = Path.cwd() / "datasheets"
    out_dir.mkdir(parents=True, exist_ok=True)

    index_path = out_dir / MANIFEST_FILENAME
    index = load_index(index_path)

    if mpn_list:
        mpn_list_path = Path(mpn_list).resolve()
        print(f"Loading MPNs from {mpn_list_path.name}...", file=sys.stderr)
        parts = load_mpn_list(mpn_list_path)
        print(f"Loaded {len(parts)} unique MPNs", file=sys.stderr)
        skipped_no_id = 0
    else:
        resolved_input = Path(input_path).resolve()
        print(f"Analyzing {resolved_input.name}...", file=sys.stderr)
        analyzer_output = get_analyzer_output(resolved_input)
        if analyzer_output is None:
            return {"error": "Failed to analyze schematic"}

        parts = extract_parts(analyzer_output)
        all_bom = analyzer_output.get("bom", [])
        skipped_no_id = sum(
            1 for e in all_bom
            if not e.get("dnp") and e.get("type", "") not in _SKIP_TYPES
            and not is_real_mpn(e.get("mpn", ""))
            and not e.get("element14", "").strip()
            and not e.get("digikey", "").strip()
            and not e.get("mouser", "").strip()
            and not e.get("lcsc", "").strip()
        )

        print(f"Found {len(parts)} unique parts with identifiers "
              f"({skipped_no_id} skipped without any identifier)", file=sys.stderr)

    to_download = []
    already_present = []
    skipped_failed = []

    for part in parts:
        part_key = (part["mpn"] or part.get("element14", "")
                    or part.get("digikey", "") or part.get("mouser", "")
                    or part.get("lcsc", ""))
        part["_key"] = part_key
        existing = index.get("parts", {}).get(part_key, {})
        status = existing.get("status", "")

        if status == "ok":
            old_file = existing.get("file", "")
            if (out_dir / old_file).exists():
                if not force_all:
                    already_present.append(part_key)
                    existing["references"] = part["references"]
                    continue

        if status in ("failed", "not_found", "no_datasheet") and not (force or force_all):
            skipped_failed.append(part_key)
            continue

        to_download.append(part)

    if dry_run:
        summary = {
            "would_download": [p["_key"] for p in to_download],
            "already_present": already_present,
            "skipped_previous_failures": skipped_failed,
            "skipped_no_identifier": skipped_no_id,
        }
        if as_json:
            json.dump(summary, sys.stdout, indent=2)
        else:
            print(f"\nDry run — would download {len(to_download)} datasheets:")
            for p in to_download:
                print(f"  {p['_key']} ({p['manufacturer'] or 'unknown mfg'})")
            print(f"Already present: {len(already_present)}")
            print(f"Skipped (previous failures): {len(skipped_failed)}")
            print(f"Skipped (no identifier): {skipped_no_id}")
        return summary

    if not to_download:
        msg = f"All {len(already_present)} datasheets up to date."
        if skipped_failed:
            msg += f" {len(skipped_failed)} previous failures (use --force to retry)."
        print(msg, file=sys.stderr)
        index["schematic"] = str(mpn_list or input_path)
        index["last_sync"] = datetime.now(timezone.utc).isoformat()
        save_index(index_path, index)
        return {"downloaded": 0, "already_present": len(already_present),
                "failed": len(skipped_failed)}

    downloaded = []
    failed = []
    warnings = []

    if parallel > 1:
        lock = threading.Lock()
        counter = [0]

        def _process_part(part):
            part_key = part["_key"]
            with lock:
                counter[0] += 1
                n = counter[0]
            print(f"[{n}/{len(to_download)}] {part_key}", file=sys.stderr)

            result = sync_one_part(part, out_dir, index, delay, api_key, store)

            with lock:
                index.setdefault("parts", {})[part_key] = result

                if result["status"] == "ok":
                    downloaded.append(part_key)
                    vconf = result.get("verification", "")
                    vmark = ""
                    if vconf == "wrong":
                        vmark = " ⚠ WRONG DATASHEET?"
                        warnings.append(part_key)
                    elif vconf == "unverified":
                        vmark = " (unverified)"
                    print(f"  OK: {result['file']} ({result['size_bytes']:,} bytes){vmark}",
                          file=sys.stderr)
                else:
                    failed.append(part_key)
                    print(f"  {result['status'].upper()}: {result.get('error', '')}",
                          file=sys.stderr)

                index["schematic"] = str(mpn_list or input_path)
                index["last_sync"] = datetime.now(timezone.utc).isoformat()
                save_index(index_path, index)

        with ThreadPoolExecutor(max_workers=parallel) as executor:
            executor.map(_process_part, to_download)
    else:
        for i, part in enumerate(to_download):
            part_key = part["_key"]
            print(f"[{i+1}/{len(to_download)}] {part_key}", file=sys.stderr)

            result = sync_one_part(part, out_dir, index, delay, api_key, store)

            index.setdefault("parts", {})[part_key] = result

            if result["status"] == "ok":
                downloaded.append(part_key)
                vconf = result.get("verification", "")
                vmark = ""
                if vconf == "wrong":
                    vmark = " ⚠ WRONG DATASHEET?"
                    warnings.append(part_key)
                elif vconf == "unverified":
                    vmark = " (unverified)"
                print(f"  OK: {result['file']} ({result['size_bytes']:,} bytes){vmark}",
                      file=sys.stderr)
            else:
                failed.append(part_key)
                print(f"  {result['status'].upper()}: {result.get('error', '')}",
                      file=sys.stderr)

            index["schematic"] = str(mpn_list or input_path)
            index["last_sync"] = datetime.now(timezone.utc).isoformat()
            save_index(index_path, index)

    summary = {
        "downloaded": len(downloaded),
        "already_present": len(already_present),
        "failed": len(failed),
        "verification_warnings": len(warnings),
        "skipped_previous_failures": len(skipped_failed),
        "skipped_no_identifier": skipped_no_id,
        "total_identified_parts": len(parts),
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
                err = entry.get("error", "")
                print(f"    {m} — {err}", file=sys.stderr)
        if skipped_failed:
            print(f"  Skipped (previous failures, use --force): "
                  f"{len(skipped_failed)}", file=sys.stderr)
        print(f"  Skipped (no identifier): {skipped_no_id}", file=sys.stderr)
        print(f"  Output: {out_dir}/", file=sys.stderr)

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Sync datasheets for a KiCad project via element14 (Newark/Farnell)",
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "input",
        nargs="?",
        help="Path to .kicad_sch file or pre-computed analyzer JSON",
    )
    input_group.add_argument(
        "--mpn-list",
        metavar="FILE",
        help=("Path to a text file with one MPN per line (KH-312 batch mode). "
              "Skips blank lines and '#' comments. Output defaults to "
              "./datasheets/ in cwd when --output is not given."),
    )
    parser.add_argument(
        "--output", "-o",
        help=("Output directory (default: datasheets/ next to input, "
              "or ./datasheets/ in cwd when --mpn-list is used)"),
    )
    parser.add_argument(
        "--store", default=_DEFAULT_STORE,
        help=f"element14 store ID (default: {_DEFAULT_STORE})",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Retry previously failed downloads",
    )
    parser.add_argument(
        "--force-all", action="store_true",
        help="Re-download everything, including already-present files",
    )
    parser.add_argument(
        "--delay", type=float, default=0.5,
        help="Seconds between API calls (default: 0.5)",
    )
    parser.add_argument(
        "--parallel", type=int, default=1,
        help="Number of parallel download workers (default: 1)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be downloaded without doing it",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output summary as JSON",
    )
    args = parser.parse_args()

    result = sync_datasheets(
        input_path=args.input,
        output_dir=args.output,
        force=args.force,
        force_all=args.force_all,
        delay=args.delay,
        parallel=args.parallel,
        dry_run=args.dry_run,
        as_json=args.json,
        store=args.store,
        mpn_list=args.mpn_list,
    )

    if "error" in result:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
