#!/usr/bin/env python3
"""Download a datasheet PDF from a manufacturer URL.

Handles manufacturer-specific quirks:
- TI: DigiKey returns JS-redirect URLs; this script extracts the direct PDF URL
- Protocol-relative URLs (//mm.digikey.com/...): adds https: prefix
- Microchip: Redirects to login; uses alternative URL patterns as fallback
- Various manufacturers that block bare urllib: uses requests library with
  proper User-Agent (handles HTTP/2, redirects, and anti-bot checks)

Usage:
    python3 fetch_datasheet_digikey.py <url> [--output <path>]
    python3 fetch_datasheet_digikey.py --search <MPN> [--output <path>]

The --search mode requires DIGIKEY_CLIENT_ID and DIGIKEY_CLIENT_SECRET
environment variables.

Dependencies:
    - requests (pip install requests) — preferred, handles all manufacturer sites
    - Falls back to urllib if requests is not installed (some sites may fail)

Exit codes:
    0 = success (PDF downloaded)
    1 = download failed after all attempts
    2 = search failed (API error or part not found)
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
    normalize_url,
    download_pdf,
    _download_requests,
    _download_urllib,
    _download_playwright,
    try_alternative_sources,
)
from distributor_core.verify import _extract_pdf_text, verify_datasheet
from distributor_core.manifest import _friendly_filename


def _get_digikey_token() -> str | None:
    """Get a DigiKey OAuth token, using a cached version if still valid.

    Caches the token to a temp file with a 9-minute TTL (tokens last 10 minutes).
    """
    import tempfile
    import time

    client_id = os.environ.get("DIGIKEY_CLIENT_ID", "")
    client_secret = os.environ.get("DIGIKEY_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print("Error: DIGIKEY_CLIENT_ID and DIGIKEY_CLIENT_SECRET required", file=sys.stderr)
        return None

    cache_path = os.path.join(tempfile.gettempdir(), "digikey_token_cache.json")

    # Check cache
    try:
        if os.path.exists(cache_path):
            with open(cache_path) as f:
                cached = json.load(f)
            if (cached.get("client_id") == client_id
                    and cached.get("expires_at", 0) > time.time()):
                return cached["token"]
    except (json.JSONDecodeError, OSError):
        pass

    # Fetch new token
    try:
        token_data = urllib.parse.urlencode({
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
        }).encode()
        req = urllib.request.Request(
            "https://api.digikey.com/v1/oauth2/token",
            data=token_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            token_resp = json.loads(resp.read())
        token = token_resp.get("access_token", "")
        if not token:
            print("Error: Failed to get OAuth token", file=sys.stderr)
            return None

        # Cache with 9-minute TTL (token lasts 10 min, 1 min safety margin)
        try:
            with open(cache_path, "w") as f:
                json.dump({
                    "token": token,
                    "client_id": client_id,
                    "expires_at": time.time() + 540,
                }, f)
            os.chmod(cache_path, 0o600)
        except OSError:
            pass  # caching is best-effort

        return token
    except Exception as e:
        print(f"Error: OAuth failed: {e}", file=sys.stderr)
        return None


def search_digikey(mpn: str) -> dict | None:
    """Search DigiKey API for a part, return first match with datasheet URL."""
    client_id = os.environ.get("DIGIKEY_CLIENT_ID", "")
    token = _get_digikey_token()
    if not token:
        return None

    # Search for the part
    try:
        search_body = json.dumps({"Keywords": mpn, "Limit": 3}).encode()
        req = urllib.request.Request(
            "https://api.digikey.com/products/v4/search/keyword",
            data=search_body,
            headers={
                "Content-Type": "application/json",
                "X-DIGIKEY-Client-Id": client_id,
                "Authorization": f"Bearer {token}",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"Error: Search failed: {e}", file=sys.stderr)
        return None

    products = data.get("Products", [])
    if not products:
        print(f"No results for '{mpn}'", file=sys.stderr)
        return None

    # Prefer exact MPN match
    for p in products:
        if p.get("ManufacturerProductNumber", "").upper().startswith(mpn.upper()):
            return p
    return products[0]


def main():
    parser = argparse.ArgumentParser(description="Download a datasheet PDF")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("url", nargs="?", help="Direct URL to the PDF")
    group.add_argument("--search", metavar="MPN", help="Search DigiKey by MPN and download the datasheet")
    parser.add_argument("--output", "-o", help="Output file path (default: <MPN>.pdf in current directory)")
    parser.add_argument("--json", action="store_true", help="Output result as JSON (for script integration)")
    args = parser.parse_args()

    if args.search:
        product = search_digikey(args.search)
        if not product:
            if args.json:
                json.dump({"success": False, "error": "Part not found"}, sys.stdout)
            sys.exit(2)

        mpn = product.get("ManufacturerProductNumber", args.search)
        desc = product.get("Description", {}).get("ProductDescription", "")
        ds_url = product.get("DatasheetUrl", "")
        output_path = args.output or (_friendly_filename(mpn, desc) + ".pdf")

        if args.json:
            result = {
                "mpn": mpn,
                "manufacturer": product.get("Manufacturer", {}).get("Name", ""),
                "description": product.get("Description", {}).get("ProductDescription", ""),
                "datasheet_url": ds_url,
            }

        if not ds_url:
            print(f"No datasheet URL for {mpn}", file=sys.stderr)
            if args.json:
                result["success"] = False
                result["error"] = "No datasheet URL in DigiKey listing"
                json.dump(result, sys.stdout)
            sys.exit(2)

        if download_pdf(ds_url, output_path):
            vr = verify_datasheet(output_path, mpn, desc,
                                  product.get("Manufacturer", {}).get("Name", ""))
            if vr["confidence"] == "wrong":
                print(f"WARNING: Downloaded PDF may be wrong datasheet for {mpn}",
                      file=sys.stderr)
                print(f"  {vr['details']}", file=sys.stderr)
            elif vr["confidence"] == "unverified":
                print(f"  Verification inconclusive for {mpn}: {vr['details']}",
                      file=sys.stderr)
            if args.json:
                result["success"] = True
                result["output"] = output_path
                result["verification"] = vr
                json.dump(result, sys.stdout)
            sys.exit(0)

        # Try alternative sources
        print(f"Primary URL failed, trying alternatives for {mpn}...", file=sys.stderr)
        if try_alternative_sources(mpn, output_path):
            vr = verify_datasheet(output_path, mpn, desc,
                                  product.get("Manufacturer", {}).get("Name", ""))
            if vr["confidence"] == "wrong":
                print(f"WARNING: Downloaded PDF may be wrong datasheet for {mpn}",
                      file=sys.stderr)
                print(f"  {vr['details']}", file=sys.stderr)
            if args.json:
                result["success"] = True
                result["output"] = output_path
                result["source"] = "alternative"
                result["verification"] = vr
                json.dump(result, sys.stdout)
            sys.exit(0)

        print(f"Failed to download datasheet for {mpn}", file=sys.stderr)
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
