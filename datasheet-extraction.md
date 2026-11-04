# Datasheet Extraction Guide

Deep-dive into how kicad-happy turns component datasheet PDFs into structured JSON — what gets extracted, how quality is scored, and how analyzers consume the result.

The **datasheets** skill is the structured-spec layer that sits between the distributor skills (which download PDFs) and the analyzer skills (which consume verified per-part knowledge). If you've ever wanted an analyzer that knows the EN-pin threshold on a specific LDO, the USB peripheral speed on a specific MCU, or the thermal resistance of a specific QFN — this is how it gets there.

> **Two APIs coexist as of v1.4.**
> - **v1.4 typed API** (`from datasheet_types import DatasheetFacts, lookup, best, trusted`) — recommended for all new code. Schema-driven extractions, page-anchored evidence, per-value confidence labels, trust gating.
> - **v1.3 dict API** (`from datasheet_features import get_regulator_features`) — legacy compat layer, still supported. Dual-reads v1.4 caches and translates them back to the v1.3 dict shape so existing detector code keeps working. Sunset planned for v1.6 once the mcu schema lands in v1.5.

Each extraction is cached per-project, not globally — two projects with the same MPN can hold different extractions if they pin different datasheet revisions. There is no shared cross-project library.

## How It Works

```
Distributor skills download PDFs:
  digikey/mouser/lcsc/element14  → <project>/datasheets/<MPN>.pdf

v1.4 typed pipeline (current):
  <MPN>.pdf  → page selector  → target pages
             → plan_extraction.py + scout subagent
             → category extractor prompts (base, pinout, regulator, diode,
                                            transistor, opamp, mcu, crystal)
             → merge_results.py validates + merges
             → <project>/datasheets/extracted/<MPN>.json (typed schema v1.0+)
             → datasheet_verify_v14_extraction cross-checks invariants
             → quality scorer (3-dim rubric: pinout / base / category)

v1.3 legacy pipeline (read-only in v1.4):
  Existing v1.3 caches keep working via the compat wrapper. New
  extractions never write the v1.3 format.

Analyzer skills consume (v1.4 typed):
  kicad, emc, spice, thermal
    → lookup(mpn, cache_dir=Path("datasheets/extracted"))  → DatasheetFacts | None
    → best(facts.regulator.vin_range, min_confidence="medium")  → SpecValue | None
    → trusted(facts.base.absolute_max["VDD"], min_confidence="high")  → list[SpecValue]

Analyzer skills consume (v1.3 compat):
    → get_regulator_features(mpn)  → dict | None  (dual-reads v1.4, falls back to v1.3 cache)
    → get_mcu_features(mpn)        → dict | None  (v1.3 cache only — v1.4 MVP has no mcu schema)
    → get_pin_function(mpn, pin)   → str | None
```

## When to Extract

Run the extraction pipeline **before** your first design review on a project, and re-run when:

- `datasheets/extracted/` is missing or empty
- A new IC appears in the design without a cached extraction
- The cache manager reports a stale entry (PDF hash changed, extraction version outdated, age > 90 days)
- An analyzer reports `confidence: heuristic` on a claim you expected to be `datasheet-backed` — the extraction may be missing or below the quality threshold

For small designs (< 8 ICs), extract all ICs. For large designs, prioritize ICs that appear in power regulators, opamp circuits, MCU pin analysis, and high-speed interfaces — these are where datasheet-backed confidence has the highest value.

## v1.4 typed API (recommended)

The v1.4 access layer lives in `skills/datasheets/datasheet_types/`. All new detectors and consumers should use this surface — it's strictly more expressive than the v1.3 dict API: per-value `SpecValue` with `min/typ/max/unit/condition/notes/evidence`, evidence carrying `page/section/confidence/method`, pin `power_domain` references, `alt_functions[]`, structured trust gating, and tri-state nullability (missing vs present-below-gate vs trusted).

```python
from pathlib import Path
from datasheet_types import DatasheetFacts, SpecValue, lookup, best, trusted, has_data

cache_dir = Path("datasheets/extracted")
facts: DatasheetFacts | None = lookup("LM2596-ADJ", cache_dir=cache_dir)

if facts is None:
    # Cache miss / malformed / wrong shape. Fall back to heuristic.
    ...
elif facts.stale:
    # PDF hash changed or PDF missing. Re-extract before trusting.
    ...
else:
    # Pinout: typed lookup helpers
    en_pin = facts.base.pinout.find(name="EN")
    if en_pin:
        print(f"EN on pin {en_pin.numbers[0]}, domain={en_pin.power_domain}")

    # Per-value trust gating
    vin_max = best(facts.base.absolute_max.get("VIN"), min_confidence="medium")
    if vin_max:
        print(f"VIN abs max: {vin_max.typ or vin_max.max} {vin_max.unit} "
              f"(page {vin_max.evidence.page}, confidence {vin_max.evidence.confidence})")

    # Tri-state: distinguish "not extracted" from "present-but-below-gate"
    theta = facts.base.thermal.get("theta_ja")
    if not has_data(theta):
        # Datasheet didn't specify
        ...
    elif not trusted(theta, min_confidence="medium"):
        # Extracted but evidence below trust gate — surface to user
        ...
    else:
        # Use the best trusted value
        ...

    # Category extensions
    if facts.regulator:
        topology = facts.regulator.topology  # "ldo" | "buck" | "boost" | ...
        en_pin_num = facts.regulator.enable_pin
        pg_pin_num = facts.regulator.power_good_pin
```

**Categories shipped in v1.4 (six):** `regulator`, `diode`, `transistor`, `opamp`, `mcu` (catalog tier), `crystal`. Each category extension is optional on `DatasheetFacts` — absent when the part doesn't fit the category. `mcu` Tier 2 (per-instance pin-mux detail) is deferred to v1.5.

**Trust gates take an explicit `min_confidence`** (`"low" | "medium" | "high"`, keyword-only, required). Each detector declares the trust level it needs. `best()` and `trusted()` preserve extractor-intended ordering — no library-side re-ranking.

**Staleness detection:** `lookup()` hashes the source PDF and compares to `source.sha256`. Three outcomes surface on `DatasheetFacts._cache_context`: fresh, `pdf_hash_mismatch`, `pdf_missing`. Read via `facts.stale` and `facts._cache_context.stale_reason`.

**Quality scoring (v1.4):** three dimensions — pinout completeness, base completeness, category-extension completeness. Reserved v1.5 dimensions left empty. Score lives at `facts.extraction.quality_score` (0–100, not the v1.3 0.0–10.0 scale).

For the canonical schemas, see `skills/datasheets/schemas/{base,pinout,spec_value,regulator,extraction,manifest}.schema.json`. For the cache directory convention, see `skills/datasheets/references/cache-layout.md`.

## v1.3 compat layer (legacy)

> **Status:** still supported in v1.4 — sunset planned for v1.6.
>
> Existing v1.3 caches keep working. The four public helpers (`get_regulator_features`, `get_mcu_features`, `get_pin_function`, `is_extraction_available`) preserve their v1.3 signatures and dict shapes byte-for-byte. Internally, they dual-read: v1.4 typed cache first, then fall back to v1.3 cache if no v1.4 extraction exists. When both caches exist for the same MPN (mid-migration state), v1.4 wins.
>
> **Why it's still here:** v1.4 MVP has no `mcu` category extension, so `get_mcu_features` on a v1.4 cache always returns None and falls through to v1.3 — the v1.3 cache is the only path to MCU peripheral data until v1.5. Some fields (`has_soft_start`, `iss_time_us`, `en_v_ih_max`, `en_v_il_min`) also have no v1.4 schema equivalent yet.
>
> **Why it's going away:** ~150 LOC of compat wrappers + dual-cache-read precedence is real complexity. Once v1.5 closes the mcu gap, the compat layer will be deprecated for one version and removed in v1.6. **All new detector code should use the v1.4 typed API above** — anything written against the v1.3 dict API today will need to be rewritten when the layer sunsets.

The rest of this section describes the v1.3 cache format and dict API as they exist today. Everything below this point is accurate for existing v1.3 caches but should not be the starting point for new code.

## Example v1.3 extraction output

A per-MPN JSON file in the legacy v1.3 format looks like this (simplified):

```json
{
  "mpn": "TPS61023DRLR",
  "manufacturer": "Texas Instruments",
  "description": "1A, 5V, 1.2MHz boost converter with 0.5V input",
  "extraction_version": 2,
  "pins": [
    {"number": "1", "name": "SW", "function": "Switch node", "type": "power", "direction": "output"},
    {"number": "2", "name": "GND", "function": "Ground", "type": "ground", "direction": "input"},
    {"number": "3", "name": "FB", "function": "Feedback", "type": "analog", "direction": "input",
     "voltage_operating_max": 6.0, "voltage_abs_max": 7.0},
    {"number": "4", "name": "EN", "function": "Enable", "type": "digital", "direction": "input",
     "required_external": null}
  ],
  "voltage_ratings": {
    "vin_min": 0.5, "vin_max": 5.5, "vin_abs_max": 6.0,
    "vout_max": 5.5
  },
  "features": {
    "topology": "boost",
    "switching_freq_hz": 1200000,
    "en_threshold_v": 0.4,
    "soft_start": true,
    "pg_present": false,
    "internal_compensation": false
  },
  "application_circuits": {
    "input_cap_recommended": "10uF ceramic, X5R or X7R",
    "output_cap_recommended": "22uF ceramic",
    "inductor_recommended": "2.2uH, 1.5A sat current"
  },
  "thermal": {
    "rtheta_ja_cw": 175.0,
    "tj_max_c": 150
  }
}
```

Fields the datasheet doesn't specify are `null`. Downstream analyzers gate on "known vs unknown," not "present vs missing."

## Cache Layout

```
<project>/
  design.kicad_sch
  design.kicad_pcb
  datasheets/
    TPS61023DRLR.pdf          # downloaded by distributor skills
    MP1484EN-LF-Z.pdf
    extracted/
      manifest.json           # extraction manifest (legacy name: index.json)
      TPS61023DRLR.json       # structured extraction
      MP1484EN-LF-Z.json
```

The cache manager (`datasheet_extract_cache.py`) owns the manifest and enforces staleness. An extraction is considered stale if:

- The source PDF's hash has changed
- The extraction's `EXTRACTION_VERSION` is older than the current skill version
- The extraction is older than `DEFAULT_MAX_AGE_DAYS` (90 days)
- The quality score is below `MIN_SCORE` (6.0)

Stale entries are transparently re-extracted on the next sync pass.

## Page Selection

Datasheets can be 10–200+ pages. The page selector (`datasheet_page_selector.py`) identifies 8–15 pages most likely to contain the information an analyzer needs, using a three-strategy cascade:

1. **TOC present** — scans the first 1–3 pages for section headings with page numbers. TOC references to "Pin Configuration", "Absolute Maximum Ratings", "Electrical Characteristics", and "Typical Application" resolve to target pages.
2. **No TOC** — scores every page by keyword density. Pages containing "absolute maximum", "pin configuration", "electrical characteristics", and "application circuit" score highest.
3. **No pdftotext** — falls back to pages 1–5 plus evenly distributed samples.

Default page budget: 10 pages, or 15 for multi-protocol parts (microcontrollers, FPGAs, SoCs). Always includes page 1 and the last page so cover-art and ordering information aren't lost.

## What Gets Extracted

Per-MPN JSON files follow a canonical schema (`EXTRACTION_VERSION` versioned). Major blocks:

| Block | Content |
|-------|---------|
| `identity` | manufacturer, MPN, family, description |
| `pins` | Pin number → {name, function, type, voltage_range, is_power, is_ground} |
| `voltage_ratings` | Absolute max, recommended operating, typical supply |
| `electrical_characteristics` | Per-parameter table (quiescent current, VIH/VIL, GBW, slew rate, etc.) |
| `peripherals` | (MCUs) GPIO count, USB/UART/SPI/I2C counts, ADC bits, protocol speeds |
| `features` | Regulator topology, EN pin behavior, power-good output, thermal pad presence |
| `application_circuits` | Typical external components + values (LDO output cap, MCU decoupling) |
| `spice_specs` | SPICE model coefficients where the datasheet provides them |
| `thermal` | Junction-to-ambient / junction-to-case resistance, max junction temp |

Null is valid — if the datasheet doesn't specify a field, the extraction records `null`. Analyzers gate on "known vs unknown," not "present vs missing."

## Quality Scoring

Every extraction gets a score from 0.0 to 10.0 via a weighted five-dimension rubric (`datasheet_score.py`):

| Dimension | Weight | What it measures |
|-----------|--------|------------------|
| Pin coverage | 35% | Fraction of pins with name, function, and type populated |
| Voltage ratings | 25% | Presence of absolute max and recommended operating ranges |
| Application info | 20% | Typical external components and recommended values present |
| Electrical characteristics | 10% | Parameter count vs expected count for the part category |
| SPICE specs | 10% | Model coefficients present where applicable |

Total = Σ(dimension_score × weight), rounded to one decimal place.

**Thresholds:**
- `MIN_SCORE = 6.0` — below this, analyzers ignore the extraction as insufficient
- `MAX_RETRIES = 3` — an extraction below MIN_SCORE gets retried up to 3 times, keeping the highest-scoring result
- Extractions above 6.0 but below 8.0 are used with reduced confidence weighting

The scorer is conservative — it's easier to refuse an extraction than to mislead an analyzer downstream. A 5.8/10 extraction does not get used; the analyzer falls back to heuristics and reports a confidence drop.

## Consumer API

Analyzer skills don't read `extracted/*.json` directly. They go through helpers in `datasheet_features.py`:

```python
from datasheet_features import (
    get_regulator_features,    # → {topology, en_threshold_v, pg_present, vout_range, ...}
    get_mcu_features,          # → {cores, flash_kb, usb, ethernet, adc_bits, ...}
    get_pin_function,          # → "EN" / "VIN" / "SW" / ...
    get_thermal_params,        # → {rja_cw, rjc_cw, tj_max_c}
)

feat = get_regulator_features("TPS61023DRLR")
if feat:
    # Known IC — use verified per-part facts
    threshold = feat.get("en_threshold_v")
else:
    # Miss, stale, or low-score — fall back to heuristic
    threshold = None
```

Every helper returns `None` for cache miss, stale cache, or low quality score. The analyzer is responsible for a heuristic fallback — trust is explicit, not implicit.

## Trust Gates

The extraction pipeline bakes trust into every downstream call:

- **Cache miss** — no extraction exists for the MPN. Helpers return None. Analyzer drops to heuristic with `confidence: "heuristic"`.
- **Stale extraction** — source PDF changed or cache is too old. Same as miss.
- **Low score (< 6.0)** — extraction exists but failed the rubric. Same as miss.
- **Sufficient score (≥ 6.0)** — helpers return the feature dict. Analyzer can emit findings with `confidence: "datasheet-backed"` and `evidence_source: "datasheet_extraction"`.

This is why findings from the schematic analyzer carry a confidence label: you can tell at a glance whether a claim is grounded in the datasheet, inferred heuristically, or cross-checked against both. When a finding says `confidence: datasheet-backed`, it means a scored extraction produced the underlying fact — not a keyword match on the part number.

## Verification

`datasheet_verify.py` cross-checks the extraction against actual usage in the design:

- Extracted pin names vs the nets connected to each pin in the schematic — flags mismatches (e.g., GND pin wired to VCC)
- Extracted voltage ranges vs the power rails feeding the part — flags overvoltage
- Extracted peripherals vs the protocol usage inferred by the analyzer — flags impossible claims (USB 3.0 on a USB 2.0-only MCU)

The verifier runs as part of the normal schematic analyzer pass; findings it raises carry rule-id `XV-DS-*` (cross-verify, datasheet). See the EMC and schematic analyzer output for examples.

## What It Can't Do

- **It doesn't download anything.** PDFs are owned by the distributor skills (`digikey`, `mouser`, `lcsc`, `element14`). If a PDF isn't in `<project>/datasheets/`, the datasheets skill has nothing to work with.
- **It isn't a universal spec library.** Extractions live per-project; there is no shared cross-project cache. Two projects using the same part maintain two extractions. This is intentional — datasheet revisions matter, and a verified extraction for revision A should not quietly get used for revision B.
- **It doesn't interpret marketing claims.** Application notes, reference designs, and "recommended for X" prose are skipped. Only structured tables, pin lists, and electrical characteristics are extracted. A part being marketed for automotive doesn't appear in the extraction; a part with AEC-Q100 grade 1 in the ordering information does.
- **It doesn't guess.** If the datasheet omits a parameter, the extraction records `null` rather than interpolating from the family or copying from a sister part. Downstream analyzers see the gap and fall back.

## Consumers Today

| Analyzer | What it uses |
|----------|--------------|
| `kicad` | Pin functions, regulator topology, MCU peripheral capability, voltage ratings |
| `emc` | SRF data for caps, saturation current for inductors, thermal pad presence |
| `spice` | Behavioral model parameters (GBW, slew rate, input offset) for opamps |
| `thermal` | Junction-to-ambient resistance, max junction temp |

Trust flows outward: the datasheets skill doesn't consume from other skills, only produces for them. This keeps the extraction layer simple and auditable — one skill owns the PDF-to-JSON contract, all other skills read it.

## Promoted from kicad in v1.3

Earlier versions kept extraction scripts under `skills/kicad/scripts/`. In v1.3 the extraction infrastructure became its own top-level skill (`skills/datasheets/`) with its own reference docs (`extraction-schema.md`, `quality-scoring.md`, `field-extraction-guide.md`, `consumer-api.md`). The promotion reflects the expanding consumer surface — once EMC, SPICE, and thermal all started depending on verified per-part knowledge, treating it as a `kicad` internal was no longer accurate.
