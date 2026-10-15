#!/usr/bin/env python3
"""Download a datasheet PDF by searching Mouser for the URL.

Mouser's datasheet URLs (mouser.com/datasheet/...) sometimes block
automated downloads with bot protection. This script works around that
by trying multiple download methods and falling back to alternative
manufacturer URL patterns.

Download methods (tried in order):
  - requests library (HTTP/2, redirects, anti-bot headers)
  - Python urllib (HTTP/1.1 fallback)
  - Playwright headless browser (JS-rendered pages, last resort)

After download, the PDF is verified by extracting text and checking
for the MPN, manufacturer name, and description keywords.

Usage:
    python3 fetch_datasheet_mouser.py --search <MPN> [--output <path>]
    python3 fetch_datasheet_mouser.py <url> [--output <path>]

Environment:
    MOUSER_SEARCH_API_KEY — required for --search mode

Exit codes:
    0 = success (PDF downloaded)
    1 = download failed after all attempts
    2 = search failed (API error or part not found)

Dependencies:
    - requests (pip install requests) — preferred, handles all manufacturer sites
    - Falls back to urllib if requests is not installed (some sites may fail)
    - playwright (optional) — for JS-rendered datasheet pages
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"

# Try to import optional dependencies; graceful fallback if not installed
try:
    import requests as _requests
except ImportError:
    _requests = None

try:
    from playwright.sync_api import sync_playwright as _sync_playwright
except ImportError:
    _sync_playwright = None


# ---------------------------------------------------------------------------
# Mouser API
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    """Get the Mouser Search API key from environment."""
    key = os.environ.get("MOUSER_SEARCH_API_KEY", "")
    if not key:
        print(
            "Error: MOUSER_SEARCH_API_KEY environment variable not set.\n"
            "  Get a free key at mouser.com → My Account → APIs → Search API\n"
            "  Then: export MOUSER_SEARCH_API_KEY=your-key-here",
            file=sys.stderr,
        )
    return key


def search_mouser(mpn: str, api_key: str) -> dict | None:
    """Search Mouser API for a part by MPN. Returns first match."""
    url = f"https://api.mouser.com/api/v1/search/partnumber?apiKey={api_key}"
    body = json.dumps({
        "SearchByPartRequest": {
            "mouserPartNumber": mpn,
            "partSearchOptions": "Exact",
        }
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"[Mouser] Search failed: {e}", file=sys.stderr)
        return None

    errors = data.get("Errors", [])
    if errors:
        for err in errors:
            print(f"[Mouser] API error: {err.get('Message', err)}", file=sys.stderr)
        return None

    parts = (data.get("SearchResults") or {}).get("Parts", [])
    if not parts:
        return None

    # Prefer exact MPN match
    mpn_upper = mpn.upper()
    for p in parts:
        if p.get("ManufacturerPartNumber", "").upper() == mpn_upper:
            return p
    return parts[0]


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------

def normalize_url(url: str) -> str:
    """Convert manufacturer-specific redirect URLs to direct PDF URLs."""
    # Protocol-relative URLs
    if url.startswith("//"):
        url = "https:" + url

    # TI redirect: extract the gotoUrl parameter
    if "ti.com/general/docs/suppproductinfo" in url:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        goto = params.get("gotoUrl", [""])[0]
        if goto:
            return goto

    # Microchip redirect: extract the actual URL
    if "microchip.com/filehandler/redirect" in url.lower():
        idx = url.find("?")
        if idx >= 0:
            return url[idx + 1:]

    return url


# ---------------------------------------------------------------------------
# Download methods
# ---------------------------------------------------------------------------

def _download_requests(url: str, output_path: str) -> bool:
    """Download using the requests library (handles HTTP/2, all manufacturers)."""
    if _requests is None:
        return False
    resp = _requests.get(
        url,
        headers={"User-Agent": _USER_AGENT},
        timeout=20,
        allow_redirects=True,
    )
    resp.raise_for_status()
    if len(resp.content) == 0:
        return False
    with open(output_path, "wb") as f:
        f.write(resp.content)
    return True


def _download_urllib(url: str, output_path: str) -> bool:
    """Download using Python urllib (fallback, HTTP/1.1 only)."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        with open(output_path, "wb") as f:
            shutil.copyfileobj(resp, f)
    return os.path.exists(output_path) and os.path.getsize(output_path) > 0


def _download_playwright(url: str, output_path: str) -> bool:
    """Download using Playwright headless browser.

    Last-resort fallback for sites that require JavaScript execution
    (Broadcom doc viewer, Espressif, etc.). Handles two patterns:
    1. Page triggers a file download (intercepted via expect_download)
    2. Page navigates directly to a PDF (read from response body)
    """
    with _sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            try:
                with page.expect_download(timeout=15000) as dl_info:
                    page.goto(url, timeout=15000, wait_until="domcontentloaded")
                download = dl_info.value
                download.save_as(output_path)
                return os.path.exists(output_path) and os.path.getsize(output_path) > 0
            except Exception:
                pass

            resp = page.goto(url, timeout=20000, wait_until="domcontentloaded")
            if resp is None:
                return False
            body = resp.body()
            if body and body[:4] == b"%PDF":
                with open(output_path, "wb") as f:
                    f.write(body)
                return True
            return False
        finally:
            page.close()
            browser.close()


def download_pdf(url: str, output_path: str) -> bool:
    """Download a PDF from a URL, trying multiple methods.

    Strategy:
    1. Try requests library (handles HTTP/2, redirects, all manufacturer sites)
    2. Fall back to Python urllib (HTTP/1.1 only — some sites may timeout)
    3. Fall back to Playwright headless browser (JS-rendered pages)

    Returns True if a valid PDF was downloaded.
    """
    url = normalize_url(url)

    methods = []
    if _requests is not None:
        methods.append(("requests", _download_requests))
    methods.append(("urllib", _download_urllib))
    if _sync_playwright is not None:
        methods.append(("playwright", _download_playwright))

    for name, fn in methods:
        try:
            if fn(url, output_path):
                with open(output_path, "rb") as f:
                    header = f.read(8)
                if header.startswith(b"%PDF"):
                    size = os.path.getsize(output_path)
                    print(f"Downloaded {size:,} bytes via {name}: {output_path}")
                    return True
                else:
                    os.remove(output_path)
        except Exception:
            if os.path.exists(output_path):
                os.remove(output_path)
            continue

    return False


def scrape_product_page(product_url: str) -> str:
    """Try to extract a datasheet PDF URL from a Mouser product page.

    Mouser product pages contain datasheet links in the HTML. This tries
    to fetch the page and extract the link without requiring JS rendering.
    Returns the datasheet URL or empty string on failure.
    """
    if not product_url:
        return ""

    # Normalize URL
    if not product_url.startswith("http"):
        product_url = "https://www.mouser.com" + product_url

    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }

    html = ""

    # Try requests first
    if _requests is not None:
        try:
            resp = _requests.get(product_url, headers=headers, timeout=20,
                                 allow_redirects=True)
            if resp.status_code == 200:
                html = resp.text
        except Exception:
            pass

    # Fallback to urllib
    if not html:
        try:
            req = urllib.request.Request(product_url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
        except Exception:
            pass

    if not html:
        return ""

    # Look for datasheet PDF links in the HTML
    # Mouser uses patterns like href="/datasheet/..." or data-href with PDF URLs
    patterns = [
        r'href="(https?://www\.mouser\.com/datasheet/[^"]+\.pdf[^"]*)"',
        r'href="(/datasheet/[^"]+\.pdf[^"]*)"',
        r'href="(https?://[^"]+\.pdf)"[^>]*>[^<]*[Dd]ata\s*[Ss]heet',
        r'"(https?://www\.mouser\.com/pdfDocs/[^"]+\.pdf)"',
    ]

    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            url = match.group(1)
            if url.startswith("/"):
                url = "https://www.mouser.com" + url
            return url

    return ""


def try_alternative_sources(mpn: str, output_path: str) -> bool:
    """Try downloading from known alternative datasheet sources.

    When the primary URL fails, try manufacturer-specific patterns.
    """
    alternatives = []
    mpn_upper = mpn.upper()

    # Microchip
    if any(x in mpn_upper for x in ("ATMEGA", "ATTINY", "PIC", "SAMD", "SAM")):
        alternatives.append(
            f"https://ww1.microchip.com/downloads/aemDocuments/documents/MCU08/ProductDocuments/DataSheets/{mpn}-DataSheet.pdf"
        )

    for alt_url in alternatives:
        if download_pdf(alt_url, output_path):
            return True

    return False


# ---------------------------------------------------------------------------
# PDF verification
# ---------------------------------------------------------------------------

def _extract_pdf_text(pdf_path: str, max_pages: int = 3) -> str:
    """Extract text from the first few pages of a PDF.

    Tries pdftotext (poppler-utils) first for best quality, then falls
    back to scanning raw PDF bytes for ASCII strings.
    """
    try:
        result = subprocess.run(
            ["pdftotext", "-l", str(max_pages), pdf_path, "-"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        with open(pdf_path, "rb") as f:
            raw = f.read(200_000)
        strings = re.findall(rb"[\x20-\x7e]{4,}", raw)
        return " ".join(s.decode("ascii", errors="ignore") for s in strings)
    except Exception:
        return ""


def verify_datasheet(
    pdf_path: str,
    mpn: str,
    description: str = "",
    manufacturer: str = "",
) -> dict:
    """Verify a downloaded PDF is actually the correct datasheet.

    Extracts text from the first few pages and checks for the MPN,
    manufacturer, and description keywords. Returns a dict with:
      - verified: bool (True if MPN found in text)
      - confidence: "verified" | "likely" | "unverified" | "wrong"
      - mpn_found: bool
      - manufacturer_found: bool
      - keyword_hits: int
      - keyword_total: int
      - details: str
    """
    text = _extract_pdf_text(pdf_path)
    if not text or len(text) < 50:
        return {
            "verified": False,
            "confidence": "unverified",
            "mpn_found": False,
            "manufacturer_found": False,
            "keyword_hits": 0,
            "keyword_total": 0,
            "details": "Could not extract text from PDF",
        }

    text_upper = text.upper()

    # Check for MPN
    mpn_upper = mpn.upper()
    mpn_found = mpn_upper in text_upper

    if not mpn_found:
        # Strip common ordering suffixes and try again
        base_mpn = re.sub(
            r"(DRLR|DRL|DGKR|DGK|DCKR|DCK|DBVR|DBV|PWPR|PWP|RGER|RGE|"
            r"RGTR|RGT|NRND|TR|CT|ND|LT1G|LT3G|BK|PBF|-ND)$",
            "", mpn_upper,
        )
        if base_mpn and len(base_mpn) >= 4 and base_mpn != mpn_upper:
            mpn_found = base_mpn in text_upper

    # Check manufacturer name
    mfg_found = False
    if manufacturer:
        mfg_upper = manufacturer.upper()
        mfg_found = mfg_upper in text_upper
        if not mfg_found:
            first_word = mfg_upper.split()[0] if " " in mfg_upper else ""
            if first_word and len(first_word) >= 4:
                mfg_found = first_word in text_upper

    # Check description keywords
    keywords = []
    if description:
        skip = {"the", "a", "an", "for", "and", "or", "with", "in", "to",
                "of", "at", "by", "on", "no", "w", "smd", "smt"}
        for word in re.split(r"[\s/,_-]+", description):
            w = word.strip().upper()
            if len(w) >= 3 and w not in skip and not re.match(r"^\d+$", w):
                keywords.append(w)

    keyword_hits = sum(1 for kw in keywords if kw in text_upper) if keywords else 0
    keyword_total = len(keywords)

    # Determine confidence level
    if mpn_found:
        confidence = "verified"
        details = f"MPN '{mpn}' found in PDF text"
    elif mfg_found and keyword_hits >= max(1, keyword_total // 2):
        confidence = "likely"
        details = (f"MPN not found but manufacturer '{manufacturer}' present "
                   f"with {keyword_hits}/{keyword_total} description keywords")
    elif keyword_hits >= max(2, keyword_total * 2 // 3):
        confidence = "likely"
        details = f"{keyword_hits}/{keyword_total} description keywords found"
    elif keyword_hits == 0 and keyword_total >= 3 and not mfg_found:
        confidence = "wrong"
        details = (f"No MPN, manufacturer, or description keywords found in PDF "
                   f"(0/{keyword_total} keywords)")
    else:
        confidence = "unverified"
        details = (f"MPN not found; {keyword_hits}/{keyword_total} keywords, "
                   f"manufacturer {'found' if mfg_found else 'not found'}")

    return {
        "verified": mpn_found,
        "confidence": confidence,
        "mpn_found": mpn_found,
        "manufacturer_found": mfg_found,
        "keyword_hits": keyword_hits,
        "keyword_total": keyword_total,
        "details": details,
    }


# ---------------------------------------------------------------------------
# Filename helpers
# ---------------------------------------------------------------------------

def _friendly_filename(mpn: str, description: str = "") -> str:
    """Build a safe filename from MPN + description."""
    def _sanitize(s):
        s = re.sub(r'[/\\:*?"<>|,;]', "_", s)
        s = re.sub(r"\s+", "_", s)
        return re.sub(r"_+", "_", s).strip("_")

    base = _sanitize(mpn)
    if not description:
        return base
    desc = description.strip()
    if len(desc) > 80:
        desc = desc[:77].rsplit(" ", 1)[0]
    desc = _sanitize(desc)
    return f"{base}_{desc}" if desc else base


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Download a datasheet via Mouser search",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("url", nargs="?", help="Direct URL to a PDF")
    group.add_argument("--search", metavar="MPN", help="Search Mouser by MPN")
    parser.add_argument("--output", "-o", help="Output file path")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    if args.url:
        # Direct URL mode
        output_path = args.output or "datasheet.pdf"
        if download_pdf(args.url, output_path):
            if args.json:
                json.dump({"success": True, "output": output_path, "source": "direct"}, sys.stdout)
            sys.exit(0)
        else:
            print(f"Failed to download PDF from {args.url}", file=sys.stderr)
            if args.json:
                json.dump({"success": False, "url": args.url, "error": "Download failed"}, sys.stdout)
            sys.exit(1)

    # --search mode
    mpn = args.search
    result = {"mpn": mpn} if args.json else None

    # Search Mouser for the datasheet URL
    api_key = _get_api_key()
    if not api_key:
        if result:
            result.update({"success": False, "error": "MOUSER_SEARCH_API_KEY not set"})
            json.dump(result, sys.stdout)
        sys.exit(2)

    print(f"[Mouser] Searching for {mpn}...", file=sys.stderr)
    mouser_part = search_mouser(mpn, api_key)

    if not mouser_part:
        print(f"[Mouser] No results for '{mpn}'", file=sys.stderr)
        if result:
            result.update({"success": False, "error": f"No Mouser results for '{mpn}'"})
            json.dump(result, sys.stdout)
        sys.exit(2)

    ds_url = mouser_part.get("DataSheetUrl", "")
    desc = mouser_part.get("Description", "")
    mfg = mouser_part.get("Manufacturer", "")

    if result:
        result["manufacturer"] = mfg
        result["description"] = desc
        result["datasheet_url"] = ds_url

    output_path = args.output or (_friendly_filename(mpn, desc) + ".pdf")

    def _finish_success(output_path: str, source: str):
        """Verify the downloaded PDF and output results."""
        vr = verify_datasheet(output_path, mpn, desc, mfg)
        if vr["confidence"] == "wrong":
            print(f"[Mouser] WARNING: Downloaded PDF may be wrong datasheet for {mpn}",
                  file=sys.stderr)
            print(f"  {vr['details']}", file=sys.stderr)
        elif vr["confidence"] == "unverified":
            print(f"[Mouser] Verification inconclusive for {mpn}: {vr['details']}",
                  file=sys.stderr)

        print(f"[Mouser] Success: {output_path}", file=sys.stderr)
        if result:
            result.update({
                "success": True, "output": output_path,
                "source": source, "verification": vr,
            })
            json.dump(result, sys.stdout)
        sys.exit(0)

    # Strategy 1: Try Mouser's datasheet URL
    if ds_url:
        print(f"[Mouser] Trying Mouser datasheet URL...", file=sys.stderr)
        if download_pdf(ds_url, output_path):
            _finish_success(output_path, "mouser")
        else:
            print(f"[Mouser] Mouser URL blocked or failed", file=sys.stderr)

    # Strategy 2: Scrape Mouser product page for datasheet link
    product_url = mouser_part.get("ProductDetailUrl", "")
    if product_url:
        print(f"[Mouser] Scraping product page for datasheet link...", file=sys.stderr)
        scraped_url = scrape_product_page(product_url)
        if scraped_url:
            print(f"[Mouser] Found datasheet link on product page", file=sys.stderr)
            if download_pdf(scraped_url, output_path):
                _finish_success(output_path, "mouser_scrape")

    # Strategy 3: Try alternative manufacturer sources
    print(f"[Mouser] Trying alternative sources...", file=sys.stderr)
    if try_alternative_sources(mpn, output_path):
        _finish_success(output_path, "alternative")

    # All methods failed — provide manual URL
    print(f"[Mouser] Failed to download datasheet for {mpn}", file=sys.stderr)
    if product_url:
        print(f"[Mouser] Manual download: {product_url}", file=sys.stderr)
    if result:
        result.update({"success": False, "error": "All download methods failed"})
        if product_url:
            result["manual_url"] = product_url
        json.dump(result, sys.stdout)
    sys.exit(1)


if __name__ == "__main__":
    main()
