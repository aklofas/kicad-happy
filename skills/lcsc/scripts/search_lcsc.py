#!/usr/bin/env python3
"""Search LCSC Electronics / JLCPCB parts catalog.

Uses the free, unauthenticated jlcsearch community API (with direct wmsc.lcsc.com
fallback for exact Cxxxxx part numbers) to search components by MPN, LCSC code,
or parametric keywords.

Usage:
    python3 search_lcsc.py <query> [options]
    python3 search_lcsc.py "tactile switch" --basic
    python3 search_lcsc.py "0805 100R" --basic --in-stock
    python3 search_lcsc.py "C318884" --details
    python3 search_lcsc.py "ME2108" --json

Exit codes:
    0 = results found
    1 = no results found
    2 = API / network error
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request

_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
_JLCSEARCH_BASE = "https://jlcsearch.tscircuit.com"


def _parse_extra(component: dict) -> dict:
    """Parse component 'extra' field safely whether it is a JSON string or dict."""
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


def search_jlcsearch(query: str, limit: int = 20, package: str = "", category: str = "") -> list[dict]:
    """Query the jlcsearch community API."""
    if category:
        endpoint = f"/{category.strip('/')}/list.json?search={urllib.parse.quote(query)}"
        url = f"{_JLCSEARCH_BASE}{endpoint}"
    else:
        params = [f"q={urllib.parse.quote(query)}", f"limit={max(limit, 20)}", "full=true"]
        if package:
            params.append(f"package={urllib.parse.quote(package)}")
        url = f"{_JLCSEARCH_BASE}/api/search?{'&'.join(params)}"

    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        comps = data.get("components", [])
        for c in comps:
            _parse_extra(c)
        return comps


def lookup_wmsc_direct(lcsc_code: str) -> dict | None:
    """Query LCSC direct wmsc API for exact Cxxxxx code fallback."""
    if not re.match(r"^C\d+$", lcsc_code, re.IGNORECASE):
        return None

    url = f"https://wmsc.lcsc.com/ftps/wm/product/detail?productCode={lcsc_code.upper()}"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            result = data.get("result") or data
            if not result or isinstance(result, str):
                return None
            num_code = int(re.sub(r"\D", "", lcsc_code))
            return {
                "lcsc": num_code,
                "mfr": result.get("productModel", ""),
                "package": result.get("encapStandard", "-"),
                "description": result.get("productIntroEn", "") or result.get("productDescEn", ""),
                "datasheet": result.get("pdfUrl", ""),
                "stock": result.get("stockNumber", 0),
                "price": result.get("productPriceList", [{}])[0].get("productPrice", 0) if result.get("productPriceList") else 0,
                "is_basic": False,
                "extra": {
                    "number": lcsc_code.upper(),
                    "mpn": result.get("productModel", ""),
                    "manufacturer": {"name": result.get("brandNameEn", "")},
                    "package": result.get("encapStandard", "-"),
                    "description": result.get("productIntroEn", "") or result.get("productDescEn", ""),
                    "quantity": result.get("stockNumber", 0),
                    "datasheet": {"pdf": result.get("pdfUrl", "")},
                }
            }
    except Exception:
        return None


def normalize_component(c: dict) -> dict:
    """Normalize fields across different API response formats."""
    extra = _parse_extra(c)
    lcsc_id = c.get("lcsc")
    number = extra.get("number") or (f"C{lcsc_id}" if lcsc_id else "")

    mpn = extra.get("mpn") or c.get("mfr") or ""
    mfr_info = extra.get("manufacturer")
    if isinstance(mfr_info, dict):
        mfr_name = mfr_info.get("name", "")
    elif isinstance(mfr_info, str):
        mfr_name = mfr_info
    else:
        mfr_name = c.get("manufacturer", "")

    pkg = extra.get("package") or c.get("package") or "-"
    desc = extra.get("description") or c.get("description") or ""

    # Stock
    stock = extra.get("quantity")
    if stock is None:
        stock = c.get("stock", 0)

    # Basic part check
    is_basic = c.get("is_basic")
    if is_basic is None:
        is_basic = bool(c.get("basic", 0))

    # Price
    price = c.get("price")
    if price is None or isinstance(price, list):
        prices = extra.get("prices") or (price if isinstance(price, list) else [])
        if prices and isinstance(prices[0], dict):
            price = prices[0].get("price", 0)
        else:
            price = 0.0

    # Datasheet
    ds = extra.get("datasheet")
    if isinstance(ds, dict):
        datasheet_url = ds.get("pdf", "")
    else:
        datasheet_url = c.get("datasheet") or (ds if isinstance(ds, str) else "")

    return {
        "lcsc_code": number,
        "lcsc_id": lcsc_id,
        "mpn": mpn,
        "manufacturer": mfr_name,
        "package": pkg,
        "description": desc.strip(),
        "is_basic": bool(is_basic),
        "stock": int(stock) if stock is not None else 0,
        "price_usd": float(price) if price else 0.0,
        "datasheet_url": datasheet_url,
        "attributes": extra.get("attributes", {}),
        "prices": extra.get("prices", []),
        "warehouses": {
            "js": extra.get("whs-js", 0),
            "zh": extra.get("whs-zh", 0),
            "hk": extra.get("whs-hk", 0),
        }
    }


def format_table(results: list[dict]) -> str:
    """Format component results as a readable ASCII/Unicode table."""
    if not results:
        return "No components found."

    lines = []
    header = f"{'LCSC #':<9} {'MPN':<24} {'Package':<14} {'Type':<7} {'Stock':>9} {'Price($)':>9} {'Description'}"
    separator = "-" * 110
    lines.append(header)
    lines.append(separator)

    for item in results:
        part_type = "Basic" if item["is_basic"] else "Ext"
        mpn = item["mpn"][:23]
        pkg = item["package"][:13]
        stock_str = f"{item['stock']:,}"
        price_str = f"${item['price_usd']:.4f}" if item["price_usd"] > 0 else "-"
        desc = item["description"].replace("\n", " ")
        if len(desc) > 36:
            desc = desc[:33] + "..."
        lines.append(
            f"{item['lcsc_code']:<9} {mpn:<24} {pkg:<14} {part_type:<7} {stock_str:>9} {price_str:>9} {desc}"
        )

    return "\n".join(lines)


def format_details(item: dict) -> str:
    """Format single component with in-depth parametric details."""
    part_type = "Basic (No feeder fee on JLCPCB)" if item["is_basic"] else "Extended ($3 feeder fee on JLCPCB)"
    lines = [
        f"LCSC Code:      {item['lcsc_code']}",
        f"MPN:            {item['mpn']}",
        f"Manufacturer:   {item['manufacturer'] or '-'}",
        f"Package:        {item['package']}",
        f"JLCPCB Type:    {part_type}",
        f"Total Stock:    {item['stock']:,} (JS: {item['warehouses']['js']:,}, ZH: {item['warehouses']['zh']:,}, HK: {item['warehouses']['hk']:,})",
        f"Unit Price:     ${item['price_usd']:.4f} USD",
        f"Datasheet:      {item['datasheet_url'] or '-'}",
        f"Description:    {item['description']}",
    ]

    attrs = item.get("attributes", {})
    if attrs:
        lines.append("Attributes:")
        for k, v in attrs.items():
            lines.append(f"  • {k}: {v}")

    prices = item.get("prices", [])
    if prices:
        lines.append("Price Breaks:")
        for p in prices:
            q_min = p.get("min_qty", p.get("qFrom", 1))
            q_max = p.get("max_qty", p.get("qTo", "+"))
            price_val = p.get("price", 0)
            lines.append(f"  • {q_min}-{q_max}: ${price_val:.4f} USD")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Search LCSC Electronics and JLCPCB parts catalog.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python3 search_lcsc.py "tactile switch"
  python3 search_lcsc.py "0805 resistor 100R" --basic
  python3 search_lcsc.py "C318884" --details
  python3 search_lcsc.py "ME2108" --limit 5 --json
"""
    )
    parser.add_argument("query", help="Search query: MPN, LCSC code (Cxxxxx), or keywords")
    parser.add_argument("-n", "--limit", type=int, default=10, help="Max results to display (default: 10)")
    parser.add_argument("-p", "--package", default="", help="Filter by footprint / package (e.g. 0805, SOT-23)")
    parser.add_argument("--basic", action="store_true", help="Only show JLCPCB Basic parts")
    parser.add_argument("--in-stock", action="store_true", help="Only show parts with stock > 0")
    parser.add_argument("--min-stock", type=int, default=0, help="Minimum stock count required")
    parser.add_argument("--category", default="", help="Category search (resistors, capacitors, microcontrollers, voltage_regulators)")
    parser.add_argument("--sort", choices=["relevance", "price", "stock"], default="relevance", help="Sort results")
    parser.add_argument("-v", "--details", action="store_true", help="Show detailed view of results")
    parser.add_argument("--json", action="store_true", help="Output raw JSON format")

    args = parser.parse_args()

    query = args.query.strip()
    try:
        raw_components = search_jlcsearch(
            query=query,
            limit=args.limit,
            package=args.package,
            category=args.category
        )
    except Exception as e:
        # Fallback to direct lookup if query is an LCSC code
        if re.match(r"^C\d+$", query, re.IGNORECASE):
            direct = lookup_wmsc_direct(query)
            raw_components = [direct] if direct else []
        else:
            print(f"Error connecting to jlcsearch API: {e}", file=sys.stderr)
            sys.exit(2)

    # Fallback to wmsc direct if jlcsearch returned nothing for Cxxxxx code
    if not raw_components and re.match(r"^C\d+$", query, re.IGNORECASE):
        direct = lookup_wmsc_direct(query)
        if direct:
            raw_components = [direct]

    # Normalize components
    normalized = [normalize_component(c) for c in raw_components]

    # Apply filters
    filtered = []
    for item in normalized:
        if args.basic and not item["is_basic"]:
            continue
        if args.in_stock and item["stock"] <= 0:
            continue
        if args.min_stock > 0 and item["stock"] < args.min_stock:
            continue
        if args.package and args.package.lower() not in item["package"].lower():
            continue
        filtered.append(item)

    # Sort
    if args.sort == "price":
        filtered.sort(key=lambda x: x["price_usd"])
    elif args.sort == "stock":
        filtered.sort(key=lambda x: x["stock"], reverse=True)

    # Limit
    results = filtered[:args.limit]

    if args.json:
        print(json.dumps({
            "query": query,
            "count": len(results),
            "total_matches": len(filtered),
            "components": results
        }, indent=2))
        sys.exit(0 if results else 1)

    if not results:
        print(f"No parts found matching '{query}'" + (" with specified filters." if (args.basic or args.in_stock or args.package) else "."))
        sys.exit(1)

    print(f"\nLCSC Search Results for '{query}' ({len(results)} shown of {len(filtered)} matches):\n")

    if args.details:
        for idx, item in enumerate(results, 1):
            print(f"--- Result [{idx}/{len(results)}] ---")
            print(format_details(item))
            print()
    else:
        print(format_table(results))
        basic_count = sum(1 for r in results if r["is_basic"])
        print(f"\nTip: Found {basic_count} Basic parts (no feeder setup fee on JLCPCB). Use --details for full specs.\n")

    sys.exit(0)


if __name__ == "__main__":
    main()
