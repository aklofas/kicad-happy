#!/usr/bin/env python3
"""Download a datasheet PDF by searching element14 (Newark/Farnell) for the URL.

Uses the element14 Product Search API to find parts by MPN or distributor PN,
then downloads the datasheet PDF from farnell.com's CDN. PDFs download directly
without bot protection — no browser fallback needed in most cases.

Usage:
    python3 fetch_datasheet_element14.py --search <MPN_or_SKU> [--output <path>]
    python3 fetch_datasheet_element14.py <url> [--output <path>]

Exit codes:
    0 = success (PDF downloaded)
    1 = download failed after all attempts
    2 = search failed (part not found or no API key)

Environment:
    ELEMENT14_API_KEY — required for search (free from partner.element14.com)

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
# element14 Product Search API
# ---------------------------------------------------------------------------

_DEFAULT_STORE = "www.newark.com"


def search_element14(query: str, api_key: str, store: str = _DEFAULT_STORE) -> dict | None:
    """Search element14 API for a part. Returns first match with datasheet URL.

    Accepts MPN, Newark/Farnell SKU, or keyword search terms.
    Detects the query type automatically:
      - If it looks like a numeric/alphanumeric SKU (e.g., "94AK6874"), uses id: search
      - Otherwise uses manuPartNum: search, falling back to any: keyword search
    """
    # Determine search mode
    # Newark/Farnell SKUs are typically alphanumeric codes like "94AK6874"
    # MPNs usually have dashes, longer alphanumeric strings
    query = query.strip()

    # Try MPN search first (most common case)
    result = _search_element14_raw(f"manuPartNum:{query}", api_key, store)
    if result:
        return result

    # Try as distributor SKU
    result = _search_element14_raw(f"id:{query}", api_key, store)
    if result:
        return result

    # Fall back to keyword search
    result = _search_element14_raw(f"any:{query}", api_key, store)
    return result


def _search_element14_raw(term: str, api_key: str, store: str) -> dict | None:
    """Execute a single element14 API search."""
    params = {
        "term": term,
        "storeInfo.id": store,
        "resultsSettings.offset": "0",
        "resultsSettings.numberOfResults": "5",
        "resultsSettings.responseGroup": "medium",
        "callInfo.responseDataFormat": "JSON",
        "callInfo.apiKey": api_key,
    }
    url = f"https://api.element14.com/catalog/products?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"[element14] Search failed: {e}", file=sys.stderr)
        return None

    # The response key depends on the search type
    for key in ("manufacturerPartNumberSearchReturn", "keywordSearchReturn",
                "skuSearchReturn", "premierFarnellPartNumberReturn"):
        result_block = data.get(key)
        if result_block:
            break
    else:
        return None

    products = result_block.get("products", [])
    if not products:
        return None

    # Prefer exact MPN match
    query_part = term.split(":", 1)[-1].upper() if ":" in term else term.upper()
    for p in products:
        mpn = (p.get("translatedManufacturerPartNumber") or "").upper()
        sku = (p.get("sku") or "").upper()
        if mpn == query_part or sku == query_part:
            return p

    # Return first result
    return products[0]


def _get_datasheet_url(product: dict) -> str:
    """Extract the best datasheet URL from an element14 product."""
    datasheets = product.get("datasheets", [])
    for ds in datasheets:
        url = ds.get("url", "")
        if url:
            return url
    return ""


def _get_mpn(product: dict) -> str:
    """Extract MPN from product."""
    return product.get("translatedManufacturerPartNumber", "")


def _get_sku(product: dict) -> str:
    """Extract Newark/Farnell SKU from product."""
    return product.get("sku", "")


def _get_manufacturer(product: dict) -> str:
    """Extract manufacturer name from product."""
    return product.get("brandName", "")


def _get_description(product: dict) -> str:
    """Extract description from product."""
    return product.get("displayName", "")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Download a datasheet PDF via element14 (Newark/Farnell)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("url", nargs="?", help="Direct URL to the PDF")
    group.add_argument("--search", metavar="QUERY",
                       help="Search by MPN or Newark/Farnell part number")
    parser.add_argument("--output", "-o", help="Output file path (default: <MPN>.pdf)")
    parser.add_argument("--store", default=_DEFAULT_STORE,
                        help=f"element14 store ID (default: {_DEFAULT_STORE})")
    parser.add_argument("--json", action="store_true", help="Output result as JSON")
    args = parser.parse_args()

    if args.search:
        api_key = os.environ.get("ELEMENT14_API_KEY", "")
        if not api_key:
            if args.json:
                json.dump({"success": False, "error": "ELEMENT14_API_KEY not set"}, sys.stdout)
            else:
                print("Error: ELEMENT14_API_KEY environment variable not set", file=sys.stderr)
                print("Get a free key at https://partner.element14.com/member/register",
                      file=sys.stderr)
            sys.exit(2)

        product = search_element14(args.search, api_key, args.store)
        if not product:
            if args.json:
                json.dump({"success": False, "error": "Part not found on element14"},
                          sys.stdout)
            else:
                print(f"No element14 results for '{args.search}'", file=sys.stderr)
            sys.exit(2)

        mpn = _get_mpn(product)
        sku = _get_sku(product)
        desc = _get_description(product)
        mfg = _get_manufacturer(product)
        ds_url = _get_datasheet_url(product)

        display_pn = mpn or sku or args.search
        output_path = args.output or (_friendly_filename(display_pn, desc) + ".pdf")

        if args.json:
            result = {
                "mpn": mpn,
                "sku": sku,
                "manufacturer": mfg,
                "description": desc,
                "datasheet_url": ds_url,
            }

        if not ds_url:
            print(f"No datasheet URL for {display_pn}", file=sys.stderr)
            if args.json:
                result["success"] = False
                result["error"] = "No datasheet URL in element14 listing"
                json.dump(result, sys.stdout)
            sys.exit(2)

        print(f"Downloading datasheet for {display_pn} ({sku})...", file=sys.stderr)
        if download_pdf(ds_url, output_path):
            vr = verify_datasheet(output_path, mpn or sku, desc, mfg)
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
            print(f"element14 URL failed, trying alternatives for {mpn}...",
                  file=sys.stderr)
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
                json.dump({"success": False, "url": url, "error": "Download failed"},
                          sys.stdout)
            sys.exit(1)


if __name__ == "__main__":
    main()
