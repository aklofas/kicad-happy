# Datasheet Extraction Guide

Deep-dive into how kicad-happy turns component datasheet PDFs into structured JSON — what gets extracted, how quality is scored, and how analyzers consume the result.

The **datasheets** skill is the structured-spec layer that sits between the distributor skills (which download PDFs) and the analyzer skills (which consume verified per-part knowledge). If you've ever wanted an analyzer that knows the EN-pin threshold on a specific LDO, the USB peripheral speed on a specific MCU, or the thermal resistance of a specific QFN — this is how it gets there.

> **Two APIs coexist as of v1.4.**
> - **v1.4 typed API** (`from datasheet_types import DatasheetFacts, lookup, best, trusted`) — recommended for all new code. Schema-driven extractions, page-anchored evidence, per-value confidence labels, trust gating.
> - **v1.3 dict API** (`from datasheet_features import get_regulator_features`) — legacy compat layer, still supported. Dual-reads v1.4 caches and translates them back to the v1.3 dict shape so existing detector code keeps working. It serves legacy caches; new code should use the typed API.

Each extraction is cached per-project, not globally — two projects with the same MPN can hold different extractions if they pin different datasheet revisions. There is no shared cross-project library.

## How It Works

```
Distributor skills download PDFs:
  digikey/mouser/lcsc/element14  → <project>/datasheets/<MPN>.pdf

v1.4 typed pipeline (current):
  <MPN>.pdf  → scout subagent (reads the PDF's contents and headings; saved as <sanitized_mpn>.scout.json,
               where sanitized_mpn is the MPN with every character outside [A-Za-z0-9_.-] replaced by _)
             → plan_extraction.py --use-cached-scout (task pages from the scout)
             → category extractor prompts (base, pinout, regulator, diode,
                                            transistor, opamp, mcu, crystal)
             → merge_results.py validates, merges and scores (0–100)
             → <project>/datasheets/extracted/<sanitized_mpn>.json (typed schema v1.0+)
             → optional: datasheet_verify.py --self-consistency checks invariants

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
    → get_mcu_features(mpn)        → dict | None  (legacy caches only — a v1.4 mcu extraction is not translated)
    → get_pin_function(mpn, pin)   → str | None
```

## When to Extract

Run the extraction pipeline **before** your first design review on a project, and re-run when:

- `datasheets/extracted/` is missing or empty
- A new IC appears in the design without a cached extraction
- The cache manager reports a stale entry (PDF hash changed, extraction version outdated, or, for legacy caches, age > 90 days)
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

**JSON categories shipped in v1.4 (six):** `regulator`, `diode`, `transistor`, `opamp`, `mcu` (catalog tier), `crystal`. The Python `DatasheetFacts` type exposes only `regulator` as a category attribute; its `base` block is available for every category, and the other category payloads are not kept as typed attributes. The legacy `get_mcu_features()` reads MCU peripheral data from legacy caches only.

**Trust gates take an explicit `min_confidence`** (`"low" | "medium" | "high"`, keyword-only, required). Each detector declares the trust level it needs. `best()` and `trusted()` preserve extractor-intended ordering — no library-side re-ranking.

**Staleness detection:** `lookup()` hashes the source PDF and compares to `source.sha256`. Three outcomes surface on `DatasheetFacts._cache_context`: fresh, `pdf_hash_mismatch`, `pdf_missing`. Read via `facts.stale` and `facts._cache_context.stale_reason`.

**Quality scoring (v1.4):** three dimensions — pinout completeness, base completeness, category-extension completeness. A reserved 30 % is awarded in full until further dimensions exist. Score lives at `facts.extraction.quality_score` (0–100, not the v1.3 0.0–10.0 scale).

For the canonical schemas, see `skills/datasheets/schemas/{base,pinout,spec_value,regulator,extraction,manifest}.schema.json`. For the cache directory convention, see `skills/datasheets/references/cache-layout.md`.

## v1.3 compat layer (legacy)

> **Status:** supported for legacy caches.
>
> Existing v1.3 caches keep working. The four public helpers (`get_regulator_features`, `get_mcu_features`, `get_pin_function`, `is_extraction_available`) preserve their v1.3 signatures and dict shapes, plus a `quality` key. Internally, they dual-read: v1.4 typed cache first, then fall back to v1.3 cache if no v1.4 extraction exists. When both caches exist for the same MPN (mid-migration state), v1.4 wins.
>
> **Why it's still here:** the v1.4 `mcu` category has a schema and a prompt, but nothing translates it for `get_mcu_features`: on a v1.4 cache it falls through to the v1.3 cache, which is the only source of MCU peripheral data for these helpers. Some fields (`has_soft_start`, `iss_time_us`, `en_v_ih_max`, `en_v_il_min`) also have no v1.4 schema equivalent yet.
>
> **For new code:** use the v1.4 typed API above. The dict helpers and the dual-cache-read precedence exist for legacy caches, and the typed API does not yet cover every field they return.

The rest of this section describes the v1.3 cache format and dict API as they exist today. Everything below this point is accurate for existing v1.3 caches but should not be the starting point for new code.

## Example v1.3 extraction output

A per-MPN JSON file in the legacy v1.3 format looks like this (simplified):

```json
{
  "mpn": "TPS61023DRLR",
  "manufacturer": "Texas Instruments",
  "description": "1A, 5V, 1.2MHz boost converter with 0.5V input",
  "topology": "boost",
  "pins": [
    {"number": "1", "name": "SW", "function": "SW", "type": "power", "direction": "output"},
    {"number": "2", "name": "GND", "function": "GND", "type": "ground", "direction": "input"},
    {"number": "3", "name": "FB", "function": "FB", "type": "analog", "direction": "input",
     "voltage_operating_max": 6.0, "voltage_abs_max": 7.0},
    {"number": "4", "name": "EN", "function": "EN", "type": "digital", "direction": "input",
     "threshold_high_v": 1.2, "threshold_low_v": 0.4, "required_external": null}
  ],
  "absolute_maximum_ratings": {
    "vin_max_v": 6.0, "vout_max_v": 7.0, "junction_temp_max_c": 150
  },
  "recommended_operating_conditions": {
    "vin_min_v": 0.5, "vin_max_v": 5.5, "vout_max_v": 5.5
  },
  "features": {
    "has_pg": false,
    "has_soft_start": true,
    "iss_time_us": null
  },
  "application_circuit": {
    "input_cap_recommended": "10uF ceramic, X5R or X7R",
    "output_cap_recommended": "22uF ceramic",
    "inductor_recommended": "2.2uH, 1.5A sat current"
  },
  "extraction_metadata": {"extraction_version": 2, "extraction_score": 6.8}
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

For legacy v1.3 caches, the cache manager (`datasheet_extract_cache.py`) owns the manifest and `is_extraction_stale()` reports an extraction stale if:

- The source PDF's hash has changed
- The extraction's `EXTRACTION_VERSION` is older than the current skill version
- The extraction is older than `DEFAULT_MAX_AGE_DAYS` (90 days)
- The quality score is below `MIN_SCORE` (6.0)

Nothing re-extracts a stale entry automatically. v1.4 caches are stale only when the PDF changed or is missing (`facts.stale`); see `skills/datasheets/references/cache-layout.md`.

## Page Selection

Datasheets can be 10–200+ pages. The page selector (`datasheet_page_selector.py`) identifies 8–15 pages most likely to contain the information an analyzer needs, using a three-strategy cascade:

1. **TOC present** — scans the first 1–3 pages for section headings with page numbers. TOC references to "Pin Configuration", "Absolute Maximum Ratings", "Electrical Characteristics", and "Typical Application" resolve to target pages.
2. **No TOC** — scores every page by keyword density. Pages containing "absolute maximum", "pin configuration", "electrical characteristics", and "application circuit" score highest.
3. **No pdftotext** — falls back to pages 1–5 plus evenly distributed samples.

Default page budget: 10 pages, or 15 for multi-protocol parts (microcontrollers, FPGAs, SoCs). Always includes page 1 and the last page so cover-art and ordering information aren't lost.

## What Gets Extracted

Legacy v1.3 per-MPN files (`EXTRACTION_VERSION` 2) have these blocks; v1.4 files follow the JSON schemas named above:

| Block | Content |
|-------|---------|
| `mpn`, `manufacturer`, `category`, `package`, `description` | Top-level identity fields |
| `pins` | Array of pin entries: number, name, function, type, direction, voltage limits, logic thresholds, `required_external` |
| `absolute_maximum_ratings` | Absolute limits (`*_max_v`, `junction_temp_max_c`) |
| `recommended_operating_conditions` | Operating ranges (`vin_min_v`, `vin_max_v`, temperature range) |
| `electrical_characteristics` | Per-parameter table (quiescent current, VIH/VIL, GBW, slew rate, etc.) |
| `peripherals` | (MCUs) GPIO count, USB/UART/SPI/I2C counts, ADC bits, protocol speeds |
| `features` | Regulator topology, EN pin behavior, power-good output, thermal pad presence |
| `application_circuit` | Typical external components + values (LDO output cap, MCU decoupling) |
| `spice_specs` | SPICE model coefficients where the datasheet provides them |
| `extraction_metadata` | Extraction version and score |

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
- `MIN_SCORE = 6.0` — below this a legacy extraction is returned with `quality.trusted: false`; each consumer decides what to do with it
- `MAX_RETRIES = 3` — an extraction below MIN_SCORE gets retried up to 3 times, keeping the highest-scoring result

A 5.8/10 legacy extraction is marked untrusted (`quality.reasons` names the low score). Each consumer decides whether to fall back to a heuristic or to report the low-quality facts.

## Consumer API

Analyzer skills don't read `extracted/*.json` directly. They go through helpers in `datasheet_features.py`:

```python
from datasheet_features import (
    get_regulator_features,    # → {topology, has_pg, en_v_ih_max, en_v_il_min, en_pin, ..., quality}
    get_mcu_features,          # → {usb_speed, has_native_usb_phy, usb_series_r_required, quality}
    get_pin_function,          # → "EN" / "VIN" / "SW" / ...
    is_extraction_available,   # → bool
)

feat = get_regulator_features("TPS61023DRLR", project_dir=".")
if feat and feat["quality"]["trusted"]:
    # Trusted extraction — use the per-part facts (any field may be None)
    threshold = feat.get("en_v_ih_max")
else:
    # Cache miss, wrong category, stale, or low score — use a fallback
    threshold = None
```

`get_regulator_features()` and `get_mcu_features()` return the facts they find with `quality = {score, scale, trusted, reasons}`, including untrusted ones (stale PDF, old extraction version, low score); check `quality["trusted"]` before treating them as verified. They return `None` on a cache miss, for a part of another kind, or when no project is named (pass `project_dir=` or `extract_dir=`). `get_pin_function()` and `is_extraction_available()` gate only legacy caches, so neither truthiness nor `is_extraction_available()` is a general quality gate.

## Trust Gates

Each consumer decides how much to trust an extraction:

- **Cache miss, unsupported category, or no project named** — the helper returns None; use a fallback.
- **Stale or low-score extraction** — the helpers return the facts with `quality["trusted"] == False` and `reasons`. A consumer that needs trusted facts falls back or reports the limitation.
- **Trusted extraction** — use the available fields, still handling None values. Datasheet-derived findings use `evidence_source: "datasheet"` and `confidence: "datasheet-backed"`.

This is why findings from the schematic analyzer carry a confidence label: you can tell at a glance whether a claim is grounded in the datasheet, inferred heuristically, or cross-checked against both. When a finding says `confidence: datasheet-backed`, it means a scored extraction produced the underlying fact — not a keyword match on the part number.

## Verification

`datasheet_verify.py` cross-checks the extraction against actual usage in the design:

- Extracted pin names vs the nets connected to each pin in the schematic — flags mismatches (e.g., GND pin wired to VCC)
- Extracted voltage ranges vs the power rails feeding the part — flags overvoltage
- Extracted peripherals vs the protocol usage inferred by the analyzer — flags impossible claims (USB 3.0 on a USB 2.0-only MCU)

The verifier runs as part of the normal schematic analyzer pass. Its findings carry a `type` (e.g. `pin_voltage_abs_max_exceeded`) and no rule id yet.

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
| `spice` | Legacy `spice_specs` fields (op-amp GBW, slew rate, offset) only; v1.4 typed facts are not read |
| `thermal` | Junction-to-ambient resistance, max junction temp |

Trust flows outward: the datasheets skill doesn't consume from other skills, only produces for them. This keeps the extraction layer simple and auditable — one skill owns the PDF-to-JSON contract, all other skills read it.

## Promoted from kicad in v1.3

Earlier versions kept extraction scripts under `skills/kicad/scripts/`. In v1.3 the extraction infrastructure became its own top-level skill (`skills/datasheets/`) with its own reference docs (`extraction-schema.md`, `quality-scoring.md`, `field-extraction-guide.md`, `consumer-api.md`). The promotion reflects the expanding consumer surface — once EMC, SPICE, and thermal all started depending on verified per-part knowledge, treating it as a `kicad` internal was no longer accurate.
