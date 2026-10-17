#!/usr/bin/env python3
"""Download a datasheet PDF by searching LCSC/jlcsearch for the URL.

Uses the jlcsearch community API (no auth required) to find parts by
MPN or LCSC code (Cxxxxx), then downloads the datasheet PDF directly
from LCSC's CDN (wmsc.lcsc.com). LCSC PDFs download without bot
protection — no special headers or browser fallback needed.

Usage:
    python3 fetch_datasheet_lcsc.py --search <MPN_or_LCSC_code> [--output <path>]
    python3 fetch_datasheet_lcsc.py <url> [--output <path>]

Exit codes:
    0 = success (PDF downloaded)
    1 = download failed after all attempts
    2 = search failed (part not found)

Dependencies:
    - requests (pip install requests) — preferred
    - Falls back to urllib if requests is not installed
    - playwright (optional) — for JS-rendered datasheet pages
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import _core_path  # noqa: F401
from distributor_core.download import (
    _USER_AGENT,
    _requests,
    _sync_playwright,
    normalize_url as _normalize_url,
    download_pdf as _download_pdf,
    _download_requests,
    _download_urllib,
    _download_playwright,
    try_alternative_sources,
)
from distributor_core.verify import _extract_pdf_text, verify_datasheet
from distributor_core.manifest import _friendly_filename


# This provider's datasheet URLs are used as given (no manufacturer redirect unwrapping).
def normalize_url(url):
    return _normalize_url(url, resolve_redirects=False)


def download_pdf(url, output_path):
    return _download_pdf(url, output_path, resolve_redirects=False)


# ---------------------------------------------------------------------------
# jlcsearch API
# ---------------------------------------------------------------------------

def _parse_extra(component: dict) -> dict:
    """Parse the 'extra' field, which may be a JSON string or a dict."""
    extra = component.get("extra")
    if extra is None:
        return {}
    if isinstance(extra, str):
        try:
            parsed = json.loads(extra)
            component["extra"] = parsed
            return parsed
        except (json.JSONDecodeError, TypeError):
            return {}
    return extra if isinstance(extra, dict) else {}


def search_lcsc(query: str) -> dict | None:
    """Search jlcsearch API for a part. Returns first match with datasheet URL.

    Accepts MPN, LCSC code (Cxxxxx), or keyword search terms.
    """
    url = f"https://jlcsearch.tscircuit.com/api/search?q={urllib.parse.quote(query)}&limit=5&full=true"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"[LCSC] Search failed: {e}", file=sys.stderr)
        return None

    components = data.get("components", [])
    if not components:
        return None

    query_upper = query.upper()

    # Parse extra for all components
    for c in components:
        _parse_extra(c)

    # Prefer exact MPN or LCSC code match
    for c in components:
        mpn = c.get("mfr", "")
        extra = c.get("extra") or {}
        lcsc_num = extra.get("number", "") if isinstance(extra, dict) else ""
        if not lcsc_num:
            lcsc_num = f"C{c.get('lcsc', '')}"
        if mpn.upper() == query_upper or lcsc_num.upper() == query_upper:
            return c

    # For short queries (< 6 chars), fuzzy results are unreliable —
    # "1012C" might match "SI1012CR" which is a completely different part.
    # Only return fuzzy matches for longer, more specific queries.
    if len(query.strip()) < 6:
        return None

    # Return first result as fuzzy match
    return components[0]


def search_lcsc_direct(lcsc_code: str) -> dict | None:
    """Query LCSC's wmsc API directly for a part by LCSC code (Cxxxxx).

    This is a fallback when jlcsearch returns no results. The wmsc API
    is unauthenticated and returns product details including datasheet URLs.
    """
    if not re.match(r"^C\d+$", lcsc_code, re.IGNORECASE):
        return None

    url = f"https://wmsc.lcsc.com/ftps/wm/product/detail?productCode={lcsc_code.upper()}"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"[LCSC] Direct lookup failed for {lcsc_code}: {e}", file=sys.stderr)
        return None

    result = data.get("result") or data
    if not result or isinstance(result, str):
        return None

    # Normalize to jlcsearch-compatible dict format
    pdf_url = ""
    pdf_list = result.get("pdfUrl") or result.get("dataSheetUrl") or ""
    if isinstance(pdf_list, str) and pdf_list:
        pdf_url = pdf_list
    elif isinstance(pdf_list, list) and pdf_list:
        pdf_url = pdf_list[0] if isinstance(pdf_list[0], str) else ""

    component = {
        "mfr": result.get("productModel") or result.get("modelName") or "",
        "description": result.get("productDescEn") or result.get("description") or "",
        "datasheet": pdf_url,
        "stock": result.get("stockNumber") or result.get("stockCount") or 0,
        "price": result.get("productPriceList"),
        "lcsc": lcsc_code.lstrip("Cc"),
        "extra": {
            "number": lcsc_code.upper(),
            "mpn": result.get("productModel") or result.get("modelName") or "",
            "description": result.get("productDescEn") or result.get("description") or "",
            "manufacturer": {
                "name": result.get("brandNameEn") or result.get("manufacturer") or "",
            },
            "datasheet": {
                "pdf": pdf_url,
            },
        },
    }

    return component


def enrich_with_wmsc(component: dict) -> dict:
    """Fill datasheet URL / MPN / manufacturer from LCSC's product-detail
    endpoint when a jlcsearch hit lacks them (jlcsearch dropped its `extra`
    block in 2026-09 — KH-405). Keeps jlcsearch's stock/price."""
    if not component or _get_datasheet_url(component):
        return component
    code = _get_lcsc_code(component)
    if not code:
        return component
    direct = search_lcsc_direct(code)
    if not direct:
        return component
    merged = dict(component)
    direct_extra = direct.get("extra") or {}
    component_extra = _parse_extra(component) or {}
    merged_extra = {**direct_extra, **component_extra}
    # The shallow merge above lets component_extra['datasheet'] clobber
    # wmsc's — including an empty {} block a stale jlcsearch hit carries
    # (KH-405). Fall through to wmsc's datasheet block when the
    # component's own has no pdf URL.
    component_ds = component_extra.get("datasheet")
    if not (isinstance(component_ds, dict) and component_ds.get("pdf")):
        direct_ds = direct_extra.get("datasheet")
        if isinstance(direct_ds, dict) and direct_ds.get("pdf"):
            merged_extra["datasheet"] = direct_ds
    merged["extra"] = merged_extra
    if not merged.get("datasheet") and direct.get("datasheet"):
        merged["datasheet"] = direct["datasheet"]
    return merged


def _get_datasheet_url(component: dict) -> str:
    """Extract the best datasheet URL from a jlcsearch component.

    Prefers the direct PDF URL from extra.datasheet.pdf (wmsc.lcsc.com CDN),
    falls back to the top-level datasheet URL (lcsc.com redirect).
    """
    extra = component.get("extra") or {}
    ds = extra.get("datasheet") or {}
    if isinstance(ds, dict):
        pdf_url = ds.get("pdf", "")
        if pdf_url:
            return pdf_url
    # Fallback to top-level
    return component.get("datasheet", "")


def _get_mpn(component: dict) -> str:
    """Extract MPN from component."""
    extra = component.get("extra") or {}
    return extra.get("mpn", "") or component.get("mfr", "")


def _get_lcsc_code(component: dict) -> str:
    """Extract LCSC code (Cxxxxx) from component."""
    extra = component.get("extra") or {}
    num = extra.get("number", "")
    if num:
        return num
    lcsc_id = component.get("lcsc", "")
    return f"C{lcsc_id}" if lcsc_id else ""


def _get_manufacturer(component: dict) -> str:
    """Extract manufacturer name from component."""
    extra = component.get("extra") or {}
    mfg = extra.get("manufacturer") or {}
    if isinstance(mfg, dict):
        return mfg.get("name", "")
    return ""


def _get_description(component: dict) -> str:
    """Extract description from component."""
    extra = component.get("extra") or {}
    return extra.get("description", "") or component.get("description", "")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Download a datasheet PDF via LCSC/jlcsearch")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("url", nargs="?", help="Direct URL to the PDF")
    group.add_argument("--search", metavar="QUERY",
                       help="Search by MPN or LCSC code (e.g., GRM155R71C104KA88D or C14663)")
    parser.add_argument("--output", "-o", help="Output file path (default: <MPN>.pdf)")
    parser.add_argument("--json", action="store_true", help="Output result as JSON")
    args = parser.parse_args()

    if args.search:
        component = search_lcsc(args.search)
        component = enrich_with_wmsc(component)
        if not component and re.match(r"^C\d+$", args.search, re.IGNORECASE):
            print(f"jlcsearch returned no results for {args.search}, trying wmsc API...",
                  file=sys.stderr)
            component = search_lcsc_direct(args.search)
        if not component:
            if args.json:
                json.dump({"success": False, "error": "Part not found on LCSC"}, sys.stdout)
            else:
                print(f"No LCSC results for '{args.search}'", file=sys.stderr)
            sys.exit(2)

        mpn = _get_mpn(component)
        lcsc_code = _get_lcsc_code(component)
        desc = _get_description(component)
        mfg = _get_manufacturer(component)
        ds_url = _get_datasheet_url(component)

        display_pn = mpn or lcsc_code or args.search
        output_path = args.output or (_friendly_filename(display_pn, desc) + ".pdf")

        if args.json:
            result = {
                "mpn": mpn,
                "lcsc": lcsc_code,
                "manufacturer": mfg,
                "description": desc,
                "datasheet_url": ds_url,
                "in_stock": component.get("stock", 0),
                "price": component.get("price"),
            }

        if not ds_url:
            print(f"No datasheet URL for {display_pn}", file=sys.stderr)
            if args.json:
                result["success"] = False
                result["error"] = "No datasheet URL in LCSC listing"
                json.dump(result, sys.stdout)
            sys.exit(2)

        print(f"Downloading datasheet for {display_pn} ({lcsc_code})...", file=sys.stderr)
        if download_pdf(ds_url, output_path):
            vr = verify_datasheet(output_path, mpn or lcsc_code, desc, mfg)
            if vr["confidence"] == "wrong":
                print(f"WARNING: Downloaded PDF may be wrong datasheet for {display_pn}",
                      file=sys.stderr)
                print(f"  {vr['details']}", file=sys.stderr)
            if args.json:
                result["success"] = True
                result["output"] = output_path
                result["verification"] = vr
                json.dump(result, sys.stdout)
            sys.exit(0)

        # Try alternative sources
        if mpn:
            print(f"LCSC URL failed, trying alternatives for {mpn}...", file=sys.stderr)
            if try_alternative_sources(mpn, output_path):
                vr = verify_datasheet(output_path, mpn, desc, mfg)
                if args.json:
                    result["success"] = True
                    result["output"] = output_path
                    result["source"] = "alternative"
                    result["verification"] = vr
                    json.dump(result, sys.stdout)
                sys.exit(0)

        print(f"Failed to download datasheet for {display_pn}", file=sys.stderr)
        if args.json:
            result["success"] = False
            result["error"] = "All download methods failed"
            json.dump(result, sys.stdout)
        sys.exit(1)

    else:
        # Direct URL mode
        url = args.url
        output_path = args.output or "datasheet.pdf"

        if download_pdf(url, output_path):
            if args.json:
                json.dump({"success": True, "output": output_path, "url": url}, sys.stdout)
            sys.exit(0)
        else:
            print(f"Failed to download PDF from {url}", file=sys.stderr)
            if args.json:
                json.dump({"success": False, "url": url, "error": "Download failed"}, sys.stdout)
            sys.exit(1)


if __name__ == "__main__":
    main()
