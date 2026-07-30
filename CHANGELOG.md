## Unreleased — workflow intelligence skills

### Added
- Methodology skills for architecture, layout review, power/clock trees, constraint/SoT management, DFM/SI signoff, design-review charters, verification planning, schematic presentation, product docs, and agent ops (prompting, multi-agent, knowledge management)
- `kidoc` engineering documentation skill
- Cross-links from core `kicad` Related Skills table

### Changed
- `llms.txt` / README discoverability for methodology skills
- Default remotes on TeinkBR fork: `origin` → TeinkBR, `upstream` → aklofas

# Changelog

All notable changes to kicad-happy are documented here.

This project follows [Semantic Versioning](https://semver.org/). Each release is validated against a [corpus of 5,800+ real-world KiCad projects](VALIDATION.md) before tagging.

---

## v2.1.0 — 2026-07-17

**Theme: correctness batch — 17 analyzer fixes from field reports, external reviews, and a fork sweep.**

### Fixed

- **#24** — Inner-layer plane connectivity: through/blind vias now expand across the physical stackup order, so inner-only planes (e.g. an In2.Cu power plane) no longer explode into one island per load. Kills spurious PS-002 / GP-001 / RP-002 findings on 4+ layer boards. (Reported by jo95017.)
- **#28** — VP-001 no longer flags vias in copper-less pads (module pads "disabled" by clearing all copper layers). (Reported by ademuri.)
- **#29** — Courtyard overlap chains CrtYd primitives into true polygons and measures real overlap; QFP corner-notch phantom overlaps are gone. New additive `courtyard_poly` field on footprints. (Reported by ademuri.)
- Three fixes ported from **Anya Sabo's fork** (found in a fork sweep, authorship preserved): a stray no-connect marker on a multi-pin net no longer flips every pin to NO_CONNECT; XV-002 skips never-synced boards whose PCB value is the footprint library name; RS-001 recognizes PWR_FLAG as a rail-source declaration (new additive `has_pwr_flag` field on nets).
- USB compliance check failures now surface as findings — new rule ids **UC-001** (no VBUS decoupling), **UC-002** (no VBUS ESD/TVS), **UC-003** (missing CC pull-down), **UC-004** (undersized VBUS capacitance). ESD arrays (USBLC6-class) now credit VBUS protection even when the VBUS net is unnamed.
- CP-003 touch-pad clearance measures to filled copper instead of the zone outline; the outline fallback is confidence-downgraded and labeled via a new `measurement_basis` field.
- VP-001 via-in-pad uses shape- and rotation-aware hit tests (circle/oval exact) instead of the axis-aligned bounding box.
- DC-003 (decoupling cap far from via) is suppressed on 2-layer boards and for caps tied into a same-layer pour of their own net.
- Sleep-current audit scores divider legs as one V/(R1+R2) path and series-R + shunt-C networks as ~0 instead of worst-case V/R.
- Rail-voltage inference no longer maps USB data lines (USB_DP/USB_DM/D+/D-) to 5.0V.
- PM-002 describes negative clearances as courtyard overhangs instead of advising "move further from board edge".
- `simulate_subcircuits.py` gains `--text`; the lifecycle `--temp-range` docs show the working `=` form.
- Per-pin absolute-max verification reads the first voltage SpecValue instead of `[0]`, preventing false CRITICALs from mixed voltage/current rating lists.
- LCSC-only lifecycle audits state up front that LCSC exposes no lifecycle data instead of emitting per-part "unknown" findings.
- `pwr_flag_warnings` respects PWR_FLAG (the warning's own remedy now silences it) and is byte-stable across runs (ordering was hash-randomized).

### Validation

- Full-corpus regression gate clean over the whole release range (5,829 repos / 170,014 comparison units, budgeted and adjudicated; evidence retained harness-side). Contract suite: 706 passed / 8 skipped / 4 xfailed.

### Upgrade notes

- Expect finding churn vs v2.0.0 — overwhelmingly false positives disappearing: PS-002/GP-001/RP-002 on inner-plane boards, VP-001, courtyard overlaps, DC-003 on 2-layer boards, PWR_FLAG-related rail-source and ERC warnings. New UC-* findings appear on boards with failing USB checks.
- Additive JSON fields (no breaking schema changes): `nets[].has_pwr_flag`, `footprints[].courtyard_poly`, CP-003 `measurement_basis`, lifecycle `capability_note`.

---

## v2.0.0 — 2026-07-12

**Theme: Deep Review — judgment moves to the model, facts stay deterministic.**

First stable release since v1.3.2. Absorbs the v1.4 release-candidate line,
which closes without a standalone final: everything the RCs introduced ships
here except the Layer-2 review pipeline, which is replaced (see below).

### Deep Review (new)

A per-IC review pass that compares how each part is actually wired in the
schematic against its datasheet, producing durable findings in
`analysis/deep_review.json`. Findings only count after passing an evidence
gate (`skills/kicad/review/scripts/deep_review_gate.py`):

- **Schema validation** per finding — invalid findings are quarantined, not fatal.
- **Design anchors** — every cited component/net/pin must exist in the analyzer
  output. Nets can be cited by any of their three identities: schematic
  internal name, the analyzer's `display_name` annotation, or the PCB net name.
- **Evidence sources** — every finding needs a verbatim datasheet quote
  (verified against the PDF text via `pdftotext`; tolerant of case, whitespace,
  punctuation, Unicode variants, and line-wrap hyphenation — but a quote that
  isn't in the PDF fails) and/or a computation script that exists on disk.
- **Visible quarantine** — failures land in `quarantined[]` with a reason,
  never silently dropped. Re-running the gate promotes corrected findings.

Deep Review findings carry no rule IDs — they are free-form, evidence-bound
observations, deliberately outside the deterministic rule registry. The gate
bounds what a review can claim; like any agent-driven pass, what it finds
still varies run to run.

### Fixed: mirrored+rotated symbol pin transform

Pin positions of schematic symbols that are both mirrored and rotated were
computed with the wrong transform order, producing wrong pin-to-net maps.
The fix derives the matrix composition from KiCad's eeschema source and is
validated against a 48-case oracle fixture. It corrected the pin-net mapping
in **1,074 of 5,857 corpus repos (18%)**.

> **Upgrade note:** designs using mirrored+rotated symbols will see finding
> churn coming from v1.3.x — unnamed-net names may change, and pull-up
> (PU-001), LED-resistor (LR-001), power-pin, voltage-mismatch, feedback,
> protocol, and crystal findings may appear or disappear. The previous
> versions of those findings were computed from incorrect pin-net maps.

### Changed: datasheet facts gating

- Feature lookups (`datasheet_features.py`) return facts with a `quality`
  flag instead of returning nothing below a score threshold; the deterministic
  detectors that need a floor re-apply it explicitly (their output is
  byte-identical to before).
- Low-quality extractions surface as `extraction_quality_low` info findings;
  extractions that exist but can't be cross-checked surface as
  `extraction_not_verifiable` — replacing silent no-ops in both cases.

### Removed

- **The v1.4 Layer-2 review pipeline** (severity tuning, merge step, reviewer
  prompt, `analysis/merged/`). Deep Review replaces it. Analyzer JSON remains
  byte-identical with or without any LLM involvement.
- **kidoc skill** (removed in rc.2 — see the v1.4.0-rc.2 entry below for
  salvage notes; source in git history at `v1.3.1`).

### Changed: leaner skill instructions

The main `kicad` skill text was rebuilt from the v1.3 version under a hard
instruction budget. The v1.4 instruction growth measurably degraded model
compliance in side-by-side testing; the rebuild keeps the v1.4-era factual
corrections without the sprawl.

### Carried from the v1.4 RC line (new to stable users)

Schema-driven datasheet extraction with page-anchored evidence and quality
scoring; 11 detectors with datasheet authority (5 upgraded + 6 new);
provenance (`inputs`) and compatibility (`compat`) blocks on every analyzer
envelope; opencode platform support; JLCPCB pick-and-place translator
(`translate_pnp`) in the bom skill; rule IDs LA-004, RS-003, LC-007; the
rc.3-era datasheet-verify crash fixes. See the rc.1/rc.2 entries below.

### Validation

Full-corpus regression gate strict-clean at the release tip (5,857 repos /
170,014 assertion units; zero deltas outside the budgeted mirror correction),
659-test schema contract suite, and an A/B design review of a real board
against the v1.3 baseline before tagging.

---

## v1.4.0-rc.2 — 2026-05-19

**Theme: Removed kidoc skill + cumulative polish over rc.1.**

> Replaces `v1.4.0-rc.1` for opt-in testing:
> ```
> /plugin marketplace add aklofas/kicad-happy#v1.4.0-rc.2
> /plugin install kicad-happy@kicad-happy
> ```

### Removed: kidoc skill

The `kidoc` skill — engineering documentation generation, introduced in
v1.2 as beta — has been removed. Its scope (generate PDF/DOCX/ODT/HTML
reports with custom SVG rendering and LLM-authored prose) conflicted
with the `kicad` skill's focus on structured-JSON analysis output, and
the two created user-facing confusion about which entry point to use
for a given task.

Source remains accessible in git history at the `v1.3.1` tag and earlier.
Three modules were flagged at removal time as candidates for future
resurrection if relevant features return:

- **`kicad_cli.py`** — cross-platform `kicad-cli` detection across 9 install
  methods (PATH, Flatpak, Snap, macOS app bundles, Homebrew, Nix, Windows
  Program Files, Chocolatey, MSYS2) with Flatpak sandbox temp-dir handling.
  Non-trivial to rediscover.
- **`kidoc_tables.py`** — unit formatters (`format_voltage`, `format_frequency`,
  `format_current`, `format_capacitance`, `format_resistance`) and markdown
  table builder. Zero-dep, cleanly liftable.
- **Custom KiCad schematic + PCB SVG renderers** (`figures/renderers/`
  plus `figures/lib/`) — with crop, focus-dim, highlight-nets, and
  pin-net annotation. Reference implementation if "visualize this finding"
  ever returns as a feature; the cheaper rebuild path is
  `kicad-cli sch export svg` plus a small overlay layer (~300 LOC).

### Other polish since rc.1

(Cumulative — see `git log v1.4.0-rc.1..HEAD` on `v1.4-dev` for the full
commit list.)

- opencode platform support via `.opencode/opencode.json`
- MattStarfield JLCPCB translator port: `translate_pnp` (KiCad CPL →
  JLCPCB Pick-and-Place format) + `--bom` filter for orphan-designator
  avoidance, integrated into the bom skill
- Detector-behavior batch: 3 new rule_ids (LA-004, RS-003, LC-007)
- TH-043 schema-vs-emit drift fix across 4 analyzers
- KH-327: `bom/SKILL.md` description trimmed to Codex 1024-char cap + CI
  hardening (SKILL.md char-limit check)
- Track 4 polish + assorted doc and CI fixes

---

## v1.4.0-rc.1 — 2026-05-15

**Theme: Datasheet Extraction v2 + Layer 2 Review** — release candidate;
final `v1.4.0` follows extended manual validation.

> **Installing the RC:** stable users on `/plugin install kicad-happy@kicad-happy`
> stay on v1.3.1 — the rc lives on the `v1.4-dev` branch and won't reach `main`
> until v1.4.0 final. To opt in for testing:
> ```
> /plugin marketplace add aklofas/kicad-happy#v1.4.0-rc.1
> /plugin install kicad-happy@kicad-happy
> ```

v1.3 harmonized analyzer output. v1.4 builds the **datasheet knowledge
layer** detectors consume from. Schema-driven structured extraction
replaces ad-hoc PDF scraping; every value carries page-anchored evidence
and a confidence label; per-detector trust gating lets analyzers
downgrade or suppress findings based on source quality. A separate
Layer 2 LLM review overlay sits on top of Layer 1 analyzer findings —
optional, additive, and provably non-destructive (strip the overlay and
the byte-identical Layer 1 baseline returns).

Validated by **Layer 1 regression gate clean corpus-wide** (5,857 repos
× 6 analyzers, v1.3.1 vs `--only-deterministic` v1.4: 0 disappeared / 0
downgrades / 0 fail / 0 new_unknown) and **462/462 contract tests
green**.

The Track-by-Track sections below cover the foundation (Tracks 1.1–1.5)
and the consumer API (Tracks 2.1–2.6). The full v1.4 story — including
Phase 3 (extraction pipeline thin slice + 5 category extensions) and
Phase 4 (foundation infra, Layer 2 review architecture, 5 upgraded
detectors, 6 new detectors, end-to-end exercise) — is in the
[release-notes.md v1.4 section](release-notes.md#-v14--datasheet-extraction-rc-line--closed-into-v20).

### Other changes

- **`group_findings_legacy` → `group_findings_by_detection_type` rename**
  (was: "compat shim pending v1.4 Priority 0 modernization" in v1.3.0).
  The helper is in fact a legitimate flat-findings → grouped-dict
  adapter — not removable debt. Renamed to reflect its real role and
  kept as first-party API in `finding_schema.py`. Internal consumers
  (`what_if.py`, `diff_analysis.py`) updated to the new name. Old name
  remains importable as a one-line alias for external callers.
- **`voltage_derating` → rich findings (VD-001..004)** — the schematic
  analyzer's `voltage_derating` results dict (legacy pre-v1.3 shape)
  migrated to the rich finding envelope with four rule IDs: VD-001
  (ceramic cap voltage derating), VD-002 (electrolytic cap voltage
  derating), VD-003 (resistor power derating), VD-004 (IC absolute-max
  exceeded). Consumers that previously read the dict shape now read
  `findings[]` filtered by rule_id. `group_findings()` adapter
  preserves the legacy access pattern.
- **`capability_mode.json` atomic-write fix (KH-325)** — first-writer
  race on the canonical `capability_mode.json` record fixed via
  `os.rename` atomic rename pattern. Eliminates a rare TOCTOU window
  observed under parallel analyzer execution.
- **opencode platform support** — ship `.opencode/opencode.json`
  pointing opencode's skill loader at the existing `skills/` tree. All
  12 skills auto-discover; no `AGENTS.md`, no file duplication, no
  symlinks. Mirrors the `.claude-plugin/` / `.codex-plugin/`
  namespacing pattern. Docs added to `install-guidance.md` (project-
  config, global-config, and manual-symlink install paths),
  `README.md` ("Works with" line + Install block + Release candidates
  section), `CONTRIBUTING.md` (skill-author checklist), and
  `github-action.md` (CI integration via `anomalyco/opencode/github`).
- **JLCPCB BOM/CPL translator + PCBA workflow** — new
  `skills/bom/scripts/translate_bom_pnp.py` (stdlib-only, ~280 LOC,
  two subcommands: `bom` and `pnp`) handles KiCad and Altium-format
  BOM/CPL inputs, with header autodetect, DNP/PCB-marker filtering,
  multi-row alt-MPN merging, mil/inch→mm coord normalization, and
  TopLayer/BottomLayer → T/B layer mapping. The `pnp --bom <path>`
  filter mode drops CPL designators absent from the BOM, avoiding
  JLCPCB's silent orphan-designator upload rejection. Documented as
  a 3-step PCBA workflow in `skills/jlcpcb/SKILL.md`. Inspired by
  [MattStarfield/kicad-happy](https://github.com/MattStarfield/kicad-happy)
  fork commits `fe440c8` (translator + workflow) and `8d8d06c`
  (`--bom` filter + consigned-parts step). Clean reimplementation
  under upstream MIT; Matt credited as `Co-Authored-By` on each
  commit. The JLCPCB Open Platform API integration in Matt's fork
  is intentionally deferred — depends on an out-of-tree HMAC signing
  client and a reference SDK without a clear license; revisit in
  v1.5+.

### Known limitations (v1.5 candidates)

- **Layer 2 ships active but uncalibrated** (per spec Q2-B). The
  reviewer subagent produces schema-valid annotations; precision/recall
  calibration against a labeled corpus is deferred to v1.5. Layer 1
  findings remain authoritative; Layer 2 annotations are overlay-only
  and never modify the baseline.
- **`finding_id` partial coverage** — Phase 4a's HI-5 stable-finding-id
  invariant ships for `make_finding`-produced findings only. Many
  raw-dict findings (most schematic detectors + all pcb/thermal/emc)
  gain `finding_id` when migrated to `make_finding` in v1.5.
- **Opamp + MCU datasheet schema deferrals** — opamp
  `noise_voltage_density` / `noise_current_density` / `phase_margin`
  (V/√Hz and degrees unit sprawl), MCU peripheral inventory Tier 2
  (per-instance pin-mux detail), and MCU `core_speed_max` /
  opamp+mcu `TOPR` shape harmonization are all deferred to v1.5.
- **Datasheet field population is uneven across the 6 v1.4 reference
  MPNs.** Per harness data-presence audit (2026-05-03): AM-001 fires
  on 6/6 (block presence) with rail-mapping on 3/6; TJ-001 4/6;
  FT-001/PM-001 fire on STM32-class parts only (alt_functions and
  is_5v_tolerant populated only there); EX-001 fires on LM2596-ADJ
  only. Remaining MPNs ship probe-only — detectors auto-activate as
  extractor prompts populate the missing fields.
- **Hierarchical-project gate parity** — the Layer 1 regression gate
  intentionally passes `--no-hierarchy` to both v1.3.1 and v1.4 to
  isolate the datasheet-layer changes from independent hierarchy work.
  A curated hierarchical-project regression gate is deferred to the
  next harness cycle.
- **`_families/` cache subdirectory reserved but unused** — Tier 2
  family extraction lands in v1.5. The directory layout and
  `lookup()` ignore-rule are documented + locked by test
  (`test_lookup_ignores_families_subdirectory_coexisting_with_cache_files`).

---

### Track 2.6 — Cache Layout Documentation (2026-04-19)

**Theme: Consolidate cache convention knowledge and reserve `_families/` for v1.5.**

New reference doc `skills/datasheets/references/cache-layout.md` describes the v1.4 datasheet cache directory structure in one place:

- Per-MPN cache file naming via `sanitize_mpn` (Track 2.3)
- `datasheets/manifest.json` Tier 1 SHA dedup layout (Track 2.1 schema)
- `_families/` subdirectory reserved for v1.5 Tier 2 family extraction (spec §14)
- Phase 3 orchestration audit files (`<MPN>.plan.json`, `<MPN>.scout.json`) — documented but not yet written by v1.4 code
- Cache invalidation rules (PDF sha256 mismatch, schema major bump, quality threshold, manual `--force`) and which of them `lookup()` v1.4 enforces at read time

No runtime code changes. One new defensive regression test (`test_lookup_ignores_families_subdirectory_coexisting_with_cache_files`) locks the invariant that `lookup()` handles a `_families/` subdirectory co-existing with per-MPN cache files — `lookup()`'s existing `is_file()` check already treats the directory as invisible, and the test ensures a future refactor (e.g. a directory-iteration-based lookup) cannot silently regress the behavior.

Tests: `tests/contract/test_datasheet_lookup.py` — 20 tests total (19 prior + 1 new). Full contract suite: **222 passing**.

#### Breaking changes
None. Pure documentation + one additive test.

#### Unblocks
- **Phase 3 extraction pipeline** — the `datasheets sync` command has a single-source reference for the cache directory convention it must write to.
- **v1.5 Tier 2 planning** — the `_families/` reservation is documented + locked by test, so v1.5 implementers can safely begin writing into that subdirectory without coordinating with existing v1.4 consumers.

---

**Phase 2 — Consumer API — is now fully closed.** All six sub-tracks (2.1 JSON schemas, 2.2 typed Python layer, 2.3 `lookup()` facade, 2.4 trust-gating helpers, 2.5 v1.3 compat wrappers, 2.6 cache-layout docs) shipped. Harness A3 + A4 fully unblocked. Next main-repo milestone: Phase 3 extraction pipeline (scout subagent prompts, `plan_extraction.py` orchestration, 6 category extractor prompts + schemas).

### Track 2.5 — v1.3 Compat Wrappers (2026-04-19)

**Theme: Preserve v1.3 detector API during the v1.3 → v1.4 cache-format transition.**

`skills/datasheets/scripts/datasheet_features.py` — public functions `get_regulator_features`, `get_mcu_features`, `get_pin_function`, `is_extraction_available` keep their exact v1.3 signatures but gain a dual-cache-read path:

1. **v1.4 path first** — try `lookup(mpn, cache_dir=...)` (Track 2.3). If it returns a `DatasheetFacts`, pass through a new `_derive_*_v14` helper to translate v1.4 typed facts into the v1.3-shaped dict.
2. **v1.3 fallback** — if the v1.4 path returns `None` (no v1.4 cache) or returns a non-applicable result (e.g. no regulator category, or mcu category not in v1.4 MVP), fall through to the existing `_load()` + `extraction_version=2` read path.

When both caches exist for the same MPN (mid-migration corpus state), v1.4 wins.

Derivation mapping (v1.4 facts → v1.3 regulator dict):

| v1.3 field | v1.4 source | Notes |
|---|---|---|
| `topology` | `facts.regulator.topology` | Passes through verbatim; v1.4 topology enum is a superset of v1.3 (`ldo` / `buck` / `boost` match). v1.3 detector check `topology in ('boost','buck','ldo')` still gates correctly. |
| `has_pg` | `facts.regulator.power_good_pin is not None` | |
| `en_pin` | `facts.regulator.enable_pin` | |
| `pg_pin` | `facts.regulator.power_good_pin` | |
| `vin_pin` | `facts.base.pinout.find(name="VIN" or "VIN+")?.numbers[0]` | |
| `vout_pin` | `facts.base.pinout.find(name="OUT" or "VOUT" or "VOUT+")?.numbers[0]` | |
| `has_soft_start`, `iss_time_us`, `en_v_ih_max`, `en_v_il_min` | — | Always `None` on v1.4 path (no schema v1.0 equivalent). v1.3 contract explicitly allows `None` for "datasheet didn't specify." |

`get_mcu_features` on a v1.4 cache **always returns None** because v1.4 MVP has no `mcu` category extension (v1.5 adds MCU + opamp + diode + transistor + crystal). Wrapper falls through to v1.3 cache so legacy MCU data keeps working. `_derive_mcu_features_v14` will gain real logic in the v1.5 track that adds the mcu schema.

`get_pin_function` maps pin identifiers → v1.3 function strings by checking regulator pin refs (enable_pin → `"EN"`, power_good_pin → `"PG"`, feedback_pin → `"FB"`) first, then falls back to a name-based map on `base.pinout` (Pin.name `"VIN"` / `"VIN+"` → `"VIN"`; `"OUT"` / `"VOUT"` / `"VOUT+"` → `"VOUT"`; `"GND"` / `"VSS"` / `"AGND"` / `"DGND"` → `"GND"`).

Consumer call-sites in `skills/kicad/scripts/validation_detectors.py` and `skills/emc/scripts/emc_rules.py` use `.get('vin_pin')`, `.get('en_pin')`, `.get('has_pg')`, `.get('has_native_usb_phy')`, `.get('usb_series_r_required')`, `.get('usb_speed')`. All six fields continue to work — derived from v1.4 facts when available, or read from the v1.3 cache when not.

Tests: `tests/contract/test_datasheet_features.py` — 17 contract tests (8 for the `_derive_*_v14` helpers, 9 for the public-wrapper integration with both cache formats). Self-contained via `pytest.tmp_path`.

#### Breaking changes
None. The v1.3 public API is preserved byte-for-byte at the call-site level — same function names, same signatures, same dict shapes, same `None` semantics. Only the internal read path changed.

#### Unblocks
- **Harness A3** — trust-gating tests can now exercise the compat-wrapper path (`get_regulator_features` → derived dict → detector check) alongside the raw `lookup()` + `trusted()` path.
- **Harness A4** — detector integration tests can verify that v1.3 detectors on v1.4 caches still produce the same findings as v1.3 detectors on v1.3 caches, modulo the v1.4-never-populated fields (`has_soft_start`, `iss_time_us`, `en_v_ih_max`, `en_v_il_min`).
- **Phase 3 extraction** — new extractions land as v1.4 cache files and are read via the v1.4 path automatically. No detector migration required for Phase 3 to ship.
- **Phase 4 detector upgrades** — detector rewrites can migrate from `get_regulator_features(mpn).get('en_pin')` to direct `lookup(mpn).regulator.enable_pin` at a pace that matches Phase 4 scope, not blocked on all-or-nothing migration.

**Phase 2 main-repo scope is now complete.** Remaining Phase 2 deliverable (cache layout `datasheets/extracted/`, `datasheets/_families/`) is a small directory-convention follow-up that can ship standalone.

### Track 2.4 — Trust-Gating Helpers (2026-04-19)

**Theme: Per-field tri-state filtering of SpecValue lists by evidence confidence (spec §12).**

New module `skills/datasheets/datasheet_types/trust_gating.py` with three module-level functions:

- `has_data(specs) -> bool` — True when `specs` is a non-empty list. Distinguishes "field not extracted" (`None` or `[]`) from "field populated with values."
- `best(specs, *, min_confidence) -> Optional[SpecValue]` — first `SpecValue` whose `evidence.confidence` meets the gate, or `None`. Preserves extractor-intended ordering (no library-side re-ranking by confidence, method, or any other field).
- `trusted(specs, *, min_confidence) -> list[SpecValue]` — all `SpecValue`s meeting the gate, in input order.

All three accept `Optional[list[SpecValue]]`, so consumers can pass `ds.regulator.vin_range` (nullable) or `ds.base.thermal.get("theta_ja")` (keyed-dict lookup) directly without `None` guards at the call site.

The tri-state signal comes from **combining** `has_data` with `trusted`:
- `has_data=False` → field not extracted
- `has_data=True` and `trusted(specs, ...) == []` → field present but all values below gate
- `has_data=True` and `trusted(specs, ...) == [v1, ...]` → field present and some values pass

Addresses the Gemini-review concern that v1.3's `SpecValue | None` API conflated "missing" with "present-but-below-gate."

`min_confidence` is keyword-only and **required** — detectors must declare their trust level explicitly per spec §12. Invalid values (anything other than `"low" | "medium" | "high"`) raise `ValueError` with a clear message.

Module-level functions (not dataclass methods) work against any `Optional[list[SpecValue]]` without Track 2.2 type changes. Scales automatically to v1.5 category additions (mcu/opamp/diode/transistor/crystal). Slightly more verbose than spec §11's idealized `ds.base.thermal.best(...)` method form — consumers write `best(ds.base.thermal.get("theta_ja"), min_confidence="medium")` — but the functional surface is identical.

`datasheet_types` public API now exports 22 names (19 + `best`, `trusted`, `has_data`). Eager re-export (not lazy `__getattr__`) since `trust_gating.py` is pure Python with no sys.path manipulation or scripts/ coupling.

Tests: `tests/contract/test_trust_gating.py` — 16 contract tests (3 for `has_data`, 6 for `best`, 4 for `trusted`, 2 for ValueError, 1 for the package re-export). Self-contained — no Track 2.2 fixtures or filesystem setup needed.

#### Breaking changes
None. Purely additive — new module, new exports, no existing code modified.

#### Unblocks
- **Harness A3** — trust-gating tests with canned `DatasheetFacts` fixtures can now exercise `best()` / `trusted()` on synthetic-liar fixtures (wrong category, wrong Vref, low-score-correct-value) and assert that the gate correctly suppresses or downgrades them. A3 is now fully unblocked.
- **Phase 4 detector upgrades** — PU-001, LR-001, XT-*, FS-001, VM-001, AM-001, OV-001, TJ-001, FT-001, PM-001, EX-001 detector implementations can now call `best()`/`trusted()` with their module-level `MIN_CONFIDENCE` constant.
- Track 2.5 — v1.3 compat wrappers (`get_regulator_features` et al.) can use `trusted()` internally to apply a baseline trust gate during the v1.3 → v1.4 translation.

### Track 2.3 — Consumer API lookup() Facade (2026-04-19)

**Theme: Read-only MPN → DatasheetFacts entry point per spec §11.**

New module `skills/datasheets/scripts/datasheet_lookup.py`:

- `lookup(mpn: str, *, cache_dir: Path) -> Optional[DatasheetFacts]` — the consumer API entry point. Resolves `cache_dir / <sanitize_mpn(mpn)>.json`, parses the JSON via Track 2.2's codec into a `DatasheetFacts`, attaches a `CacheContext` with staleness metadata, and returns the instance. Returns `None` on cache-dir missing / cache-file missing / malformed JSON / wrong shape. Pure read — never writes, extracts, or triggers LLM calls (spec §11 Rules 1 & 2).
- `sanitize_mpn(mpn)` — MPN → filename component. Allows `[A-Za-z0-9_-]`, replaces everything else with `_`. Simpler than v1.3's sanitizer (no MD5 suffix), matches Track 2.1 fixture naming (`LM2596-ADJ.json`).
- `cache_path_for(mpn, cache_dir)` — composes `cache_dir / f"{sanitize_mpn(mpn)}.json"`.
- `CacheContext` — operational metadata attached to returned `DatasheetFacts`: `cache_path`, `pdf_path`, `is_stale`, `stale_reason` (`STALE_PDF_HASH_MISMATCH` / `STALE_PDF_MISSING` module constants or `None`).

Staleness: `lookup()` hashes the PDF at `cache_dir.parent / source.local_path` (with a fallback to `cache_dir.parent.parent / source.local_path` for v1.3-style `"datasheets/..."` paths) and compares to `source.sha256`. Three outcomes: fresh (hash match), stale with `pdf_hash_mismatch`, stale with `pdf_missing` (file gone or `local_path is None`).

`DatasheetFacts` gains three read-only `@property` methods:
- `quality: Optional[int]` — passthrough to `extraction.quality_score`.
- `stale: bool` — reads `_cache_context.is_stale`, defaults `False` when constructed outside `lookup()`.
- `cache_path: Optional[Path]` — reads `_cache_context.cache_path`, defaults `None`.

Properties are NOT dataclass fields — they don't participate in `from_dict` / `to_dict` / `__eq__`. Track 2.2's round-trip tests continue to pass unchanged.

The `datasheet_types` package re-exports `lookup` lazily via module-level `__getattr__`, so `from datasheet_types import lookup` works alongside `from datasheet_lookup import lookup` without forcing `skills/datasheets/scripts/` onto sys.path at `import datasheet_types` time. `lookup` appears in `datasheet_types.__all__` (now 19 names).

Tests: `tests/contract/test_datasheet_lookup.py` — 18 contract tests covering MPN sanitization (4), cache-path composition (1), cache-miss paths (4), happy path (3, including a full end-to-end happy path with fresh PDF + typed access), PDF staleness (4), cross-package re-export (1), plus 4 integration tests in `test_datasheet_types.py` for the `quality`/`stale`/`cache_path` properties. All tests are self-contained via `pytest.tmp_path` — no committed test cache or PDF files.

#### Breaking changes
None. Purely additive — new module + read-only property additions to `DatasheetFacts`.

#### Unblocks
- **Harness A3** — trust-gating tests with canned `DatasheetFacts` fixtures. A3 can now dispatch `lookup()` against an in-memory cache dir and assert on `.stale`, `.quality`, `.base.pinout.find(...)`, etc. Fixtures stay in-process via `tmp_path`.
- Track 2.4 — trust-gating helpers `best()` / `trusted()` attach to existing dataclass types.
- Track 2.5 — v1.3 compat wrappers (`get_regulator_features`, `get_mcu_features`, `get_pin_function`) can now rewrite over `lookup()` to get typed access + staleness for free.

### Track 2.2 — Typed Python Access Layer (2026-04-19)

**Theme: Ergonomic typed access on top of the Track 2.1 JSON schemas.**

Seven new Python modules under `skills/datasheets/datasheet_types/` mirror the Track 2.1 schema files. Stdlib-only dict ↔ dataclass codec. Package name is `datasheet_types` (not `types`) to avoid shadowing stdlib.

- `spec_value.py` — `SpecValue` + `Evidence` primitives.
- `pinout.py` — `AltFunction` + `Pin` dataclasses + `Pinout` wrapper class (non-dataclass, exposes `.find(pin=...)`, `.find(name=...)`, `.in_domain(rail)`, `__iter__`, `__len__`, `__eq__`). Serializes to/from a bare list matching `pinout.schema.json`'s root-array shape.
- `base_block.py` — `BaseBlock` plus `Package`, `BodyMm`, `MoistureSensitivity`, `ComplianceMark`, `PinRelationship`. Ratings dicts typed as `dict[str, list[SpecValue]]` (keyed-object shape from spec §4).
- `regulator.py` — `Regulator` plus `StabilityConditions` and `Sequencing`. Only `topology` required; all electrical params are `Optional[list[SpecValue]]`.
- `extraction.py` — `DatasheetFacts` top-level envelope + `Source` + `ExtractionMeta` + `SchemaVersion`.
- `codec.py` — stdlib-only `from_dict(cls, data)` / `to_dict(obj)`. Handles nested dataclasses, `Optional[T]`, `list[T]`, `dict[str, T]`, the Pinout wrapper special case, and an `omit_if_none` field-metadata opt-in for category sibling fields so `DatasheetFacts.regulator` serializes as "absent key" (not `null`) when None — preserves the Track 2.1 contract that regulator is "either valid object or absent key."

`skills/datasheets/datasheet_types/__init__.py` re-exports the 18 public names consumers need: `DatasheetFacts`, `SpecValue`, `Evidence`, `Pin`, `AltFunction`, `Pinout`, `BaseBlock`, `Package`, `BodyMm`, `MoistureSensitivity`, `ComplianceMark`, `PinRelationship`, `Regulator`, `StabilityConditions`, `Sequencing`, `Source`, `ExtractionMeta`, `SchemaVersion`.

Tests: `tests/contract/test_datasheet_types.py` — 34 contract tests covering per-type round-trip, canonical-SI value preservation, Pinout lookup helpers, codec type-guards (non-list / non-dict inputs raise TypeError), `omit_if_none` policy, and full end-to-end round-trip of both Track 2.1 fixtures (LM2596-ADJ + minimal) with schema re-validation. `to_dict(from_dict(DatasheetFacts, fixture))` matches each fixture via Python dict equality (key-value-equivalent, order-independent); JSON text byte-equality does not hold for lm2596-adj due to required-first Python dataclass ordering vs schema property order — cache rewrites are semantically idempotent but not text-idempotent.

The JSON schemas remain source of truth. The dataclasses are NOT derived from them — parity is enforced by fixture round-trip tests, not by code generation. Schema constraints richer than dataclass reflection can express (`patternProperties`, closed enums, `x-*` annotations) stay in the JSON.

During implementation, the LM2596-ADJ and minimal fixtures were completed with explicit null/empty values for previously-absent optional fields (`package.pitch_mm`, `package.body_mm`, `base.moisture_sensitivity`, `base.compliance`, `regulator.dropout`, plus an expanded minimal fixture). Each addition is schema-valid + semantically neutral (absent-key ≡ null for optional nullable scalars, absent-key ≡ empty for optional lists). The fixture modifications are captured in the `test_base_block_from_fixture` docstring for future maintainers.

#### Breaking changes
None. This track is purely additive — new package, no changes to existing analyzer or detector code.

#### Unblocks
- Track 2.3 — `lookup(mpn) -> DatasheetFacts | None` facade can now return a typed instance.
- Track 2.4 — trust-gating helpers (`best()`, `trusted()`) attach to existing dataclass types.
- Track 2.5 — v1.3 compat wrappers can build dicts from `DatasheetFacts` instances via `to_dict()`.
- Harness A3 (trust-gating tests with canned `DatasheetFacts` fixtures) — Track 2.2 provides the shape; A3 unblocks fully at Track 2.3 when `lookup()` is in place.

### Track 2.1 — Datasheet v2 JSON Schemas (2026-04-19)

**Theme: Canonical schema infrastructure for datasheet extraction v2.**

Six Draft 2020-12 schemas land under `skills/datasheets/schemas/` — the foundation every downstream Phase 2 sub-track (typed access layer, `lookup()` facade, trust gating, compat wrappers, cache layout) consumes:

- `spec_value.schema.json` 1.0 — atomic primitive for every electrical/physical fact (`{min, typ, max, unit, condition, notes, evidence: {page, section, confidence, method}}`). Always serialized as a one-element list. Canonical SI units only (including `°C/W` and `K/W` for thermal resistance).
- `pinout.schema.json` 1.0 (still-calibrating) — Pin shape with KiCad ERC type vocabulary, optional `alt_functions[]`, per-pin SpecValue arrays. BGA-safe via `numbers: string[]`.
- `base.schema.json` 1.0 — universal per-IC facts: `family`, `package`, `thermal`, `absolute_max`, `recommended_operating`, `esd`, `compliance[]`, `pinout` (ref), `pin_relationships[]`. `absolute_max`/`recommended_operating`/`esd`/`thermal` are objects keyed by parameter name → `SpecValue[]` for consumer-side indexability (spec §4).
- `regulator.schema.json` 0.3 — first category extension. Flat topology enum (spec §7). All electrical params optional `SpecValue[]`. Nested `stability_conditions` + `sequencing` blocks feed SV-001 and ST-001.
- `extraction.schema.json` 1.0 — top-level per-MPN file envelope composing base + categories.
- `manifest.schema.json` 1.0 — `datasheets/manifest.json` shape. New `pdfs` section keys by `sha256:` → `{path, mpns[]}` for Tier 1 dedup. Legacy `extractions` section retained for v1.3 compat.

Alongside the schemas:
- `fixtures/lm2596-adj.example.json`, `fixtures/minimal.example.json`, `fixtures/manifest.example.json` — round-trip fixtures covering realistic and minimal-valid shapes. LM2596-ADJ exercises the full `$ref` chain (extraction → base → pinout + spec_value, extraction → regulator → spec_value).
- `tests/contract/test_datasheet_schemas.py` — validates Draft 2020-12 conformance + fixture → schema round-trip via `referencing.Registry`. 36 tests total.
- `schemas/CHANGELOG.md` — per-schema semver-lite rules (additive within minor, breaking = major, stale-one-section-only).

No runtime code changes. Consumer API (`lookup()`), typed access layer (`DatasheetFacts`, `SpecValue`, `Pin` dataclasses), trust gating helpers (`best()`, `trusted()`), and v1.3 compat wrappers land in sub-tracks 2.2–2.6.

#### Breaking changes
- `requirements-dev.txt` gains explicit `referencing>=0.28` declaration (was implicit via `jsonschema`).
- `datasheets/manifest.json` gains a new `pdfs` section — **additive only**. Legacy `extractions` section stays intact; v1.3 consumers that ignore unknown keys continue to work.

#### Unblocks
- Track 2.2 — typed Python access layer (`skills/datasheets/types/`) can now import from these schemas.
- Track 2.6 — cache layout with SHA dedup: manifest schema landed.
- Harness A3 (trust-gating tests) still blocked on Track 2.3 (lookup + DatasheetFacts).

### Track 1.5 — Contract tiers documentation

**Theme: Explicit tiering of envelope keys.**

`skills/kicad/references/output-schema.md` now opens with a "Contract Tiers" section categorizing every top-level envelope key into Tier 1 (standardized, stable across v1.4), Tier 2 (analyzer-specific body), or Tier 3 (compatibility residue). Tier 3 is empty for v1.4 — the clean break during Tracks 1.1-1.3 removed the prior residue.

Text lives in `gen_output_schema_md.py`'s HEADER template so regeneration preserves it.

### Track 1.4 — Schema compatibility metadata

**Theme: Structured deprecation + experimental-field tracking.**

New shared primitive `CompatBlock` in `analyzer_envelope.py` with three fields: `minimum_consumer_version: str`, `deprecated_fields: list[str]`, `experimental_fields: list[str]`. Every envelope has a new required `compat: CompatBlock` field sibling to `inputs`.

For v1.4, every envelope emits `minimum_consumer_version: "1.4.0"` with both lists empty — the clean break left nothing deprecated and nothing experimental. v1.5 will start populating the lists as fields are scheduled for removal or introduced as best-effort experiments.

New helper: `inputs_builder.build_compat(minimum_consumer_version, deprecated_fields, experimental_fields)` centralizes construction with v1.4-sensible defaults.

#### Breaking changes
- Every envelope gains a required `compat` field. External consumers validating `--schema` output must accept the new top-level key.

#### Unblocks
- Track 2 per-category datasheet schemas can now reference `minimum_consumer_version` when declaring their own shapes.
- v1.5 consumer API can refuse reads of `deprecated_fields` and warn on `experimental_fields` use.

### Track 1.3 — Formal inputs / provenance block

**Theme: Consistent SHA-256 provenance across every analyzer.**

New shared primitives `InputsBlock` and `UpstreamArtifact` in `analyzer_envelope.py`. Every envelope now carries a required `inputs` field: `source_files[]` + `source_hashes{}` + `run_id` + `config_hash` + `upstream_artifacts{}`.

New helpers: `run_id.py` generates sortable IDs like `20260418T123456Z-a1b2c3`. `inputs_builder.py` centralizes SHA computation and upstream-artifact construction.

Derivative analyzers (thermal, EMC, cross_analysis) populate `inputs.upstream_artifacts` with structured metadata (`path`, `sha256`, `schema_version`, `run_id`) about each prior-stage JSON they consume — enabling Track 2 datasheet cache audits and Track 3 Layer 2 review to walk the full provenance chain.

#### Breaking changes
- `schematic.file` and `pcb.file` top-level fields **REMOVED**. Consumers read `inputs.source_files[0]` instead.
- Every analyzer envelope gains a required `inputs` field. External consumers validating `--schema` output must accept the new top-level key.

#### Kept (parsed content, not provenance)
- `kicad_version`, `file_version`, `title_block` stay on schematic / PCB envelopes — they describe parsed design content, not provenance of what we read.

#### Added modules
- `skills/kicad/scripts/run_id.py` — run_id generator
- `skills/kicad/scripts/inputs_builder.py` — `build_inputs()` + `build_upstream_artifact()` helpers

### Track 1.2 — Findings / Assessments separation

**Theme: Distinguish informational measurements from actionable warnings.**

New shared primitive `Assessment` (Finding-shaped minus `severity` and `recommendation`) added to `analyzer_envelope.py`. Every envelope gains a top-level `assessments: list[Assessment]` field alongside `findings: list[Finding]`.

Thermal analyzer TH-DET entries (per-component junction-temperature estimates) migrated from `findings[]` to `assessments[]`. Other analyzers emit `assessments: []` — reserved for future measurement-style records.

#### Breaking changes
- `thermal.findings[]` no longer contains TH-DET entries. `thermal.summary.total_findings` drops correspondingly (counts rule findings only).
- `thermal.trust_summary` rolls up findings only — assessments are not trust-summarized (they are factual measurements, not judgments).
- Consumers that want the union of findings + assessments must read both lists.

#### Consumer updates
- `summarize_findings.py` reports an Assessments section alongside findings (rule_id + count, no severity column).
- `diff_analysis.py` diffs assessments (added / removed / unchanged). Thermal analyzer newly included in the diff dispatch.
- `analyze_thermal.py` result dict: renamed `thermal_assessments` → `assessments`; removed the merge-and-recompute block that previously folded TH-DET into findings.

#### Unblocks
- Track 3 (Layer 2 LLM review) operates on `findings[]` only — the separation gives it a stable interface free of informational clutter.

### Track 1.1 — Typed Analyzer Envelope SOT

**Theme: Single Source of Truth for Analyzer Output** — Python dataclasses replace hand-maintained `_get_schema()` dicts across 6 analyzers. One typed definition now drives `--schema` emission (as real JSON Schema Draft 2020-12), generated reference docs, and contract-test validation of live runtime output.

#### Typed envelope source of truth

Every analyzer's output shape is now declared as a Python dataclass with field metadata for descriptions and JSON name mapping. The same definition:

- Emits real JSON Schema Draft 2020-12 via `--schema`
- Is validated at test time by 51 contract tests against runtime analyzer output
- Generates `skills/kicad/references/output-schema.md` via `gen_output_schema_md.py`
- Runs in CI via the new `schema-contract` job

#### Breaking changes

- **`--schema` output shape** — all six analyzers (schematic, PCB, gerber, thermal, EMC, cross_analysis) now emit JSON Schema Draft 2020-12. Prior format was a descriptive-string dict keyed by field name. Any external consumer parsing `--schema` output as the old dict shape will break.
- **`schema_version` bumped 1.3.0 → 1.4.0** on every analyzer.
- **`trust_summary.by_confidence` aggregate key renamed** `datasheet-backed` → `datasheet_backed` (rollup only; per-finding `confidence` VALUE stays `datasheet-backed` with the hyphen).
- **`trust_summary.provenance_coverage_pct`** relaxed from `float` to `Optional[float]` — runtime has always emitted `null` when `total_findings == 0`; envelope now honestly reflects that. Consumers should accept null.
- **`ThermalSummary`** now declares 6 previously-undeclared board-level fields: `total_board_dissipation_w`, `hottest_component`, and four related board-thermal rollup fields.
- **Schematic envelope optional fields** — `_redirected_from` and `_stale_file_warning` moved to declared optional fields (via `field(metadata={"json_name": ...})`) rather than implicit runtime additions.

#### Closed issues

- **KH-323** — `pin_coverage_warnings` now a declared OPTIONAL field on `SchematicEnvelope`. Harness can remove the `_KNOWN_UNDOCUMENTED['schematic']` allow-list entry.

#### Added modules

- `skills/kicad/scripts/schema_codec.py` — dataclass → JSON Schema Draft 2020-12 converter. Stdlib-only. `dataclass_to_json_schema(cls)` + `emit_schema(cls)` CLI helper. Honors `field(metadata={"description": ..., "const": ..., "json_name": ...})`.
- `skills/kicad/scripts/analyzer_envelope.py` — shared envelope primitives (TrustSummary, Finding, BySeverity, TitleBlock, BomCoverage, ByConfidence, ByEvidenceSource).
- `skills/kicad/scripts/envelopes/*.py` — per-analyzer envelope dataclasses (schematic, pcb, gerber, thermal, cross_analysis).
- `skills/emc/scripts/emc_envelope.py` — EMC envelope dataclass.
- `skills/kicad/scripts/gen_output_schema_md.py` — regenerates `skills/kicad/references/output-schema.md` from dataclass introspection.

#### Test infrastructure

- `tests/contract/` — pytest contract tests validating `--schema` output (Draft 2020-12 conformance) and live analyzer output against its declared schema. Uses `tests/fixtures/simple-project/`.
- `requirements-dev.txt` — dev deps (`pytest`, `jsonschema`).
- `schema-contract` CI job runs `pytest tests/contract/` on every PR.

#### Forward pointer

Track 1.3 (structured provenance block) builds on this typed SOT foundation.

---

## v1.3.1 — 2026-05-11

**Theme: Bug fixes + PCB connectivity rewrite** — a patch release closing
issues reported against v1.3.0 and reworking the PCB copper-connectivity model.

### Fixes

- **`format-report.py` crash on dict-shaped `power_rails`** (#16, #20) — the
  report formatter assumed `power_rails` was a list of strings; it now handles
  the dict form emitted for rails with metadata.
- **KH-147 — LED-driver false positive** — `detect_led_drivers` flagged a
  current resistor as a current-limiting LED resistor even when its value
  string carried an unparseable suffix (e.g. `215k_0402_<MPN>` from importers
  that append package/MPN tags). An unparseable value now means "can't confirm
  the current-limiting role — skip" rather than a false finding.
- **Pad rotation sign** — corrected the rotation sign convention in PCB
  footprint parsing; **analysis-dir resolution** unified across analyzers.

### Changes

- **PCB connectivity rewrite** — `pcb_connectivity.py` reworked to a
  track-as-node model with compound-pad handling and `*.Cu` layer wildcards,
  improving island detection and plane-split accuracy.
- **`.kicad_pro` `top_level_sheets` support** (#19) — flat multi-page projects
  imported from Altium (which list pages in `top_level_sheets` rather than a
  sheet hierarchy) are now analyzed across all pages.
- **Python 3.10 minimum** — the v1.4 floor lands early in this patch; install
  guidance added for Claude Code, Codex, and Gemini.

#### Breaking changes
None.

---

## v1.3.0 — 2026-04-16

**Theme: Harmonized Analysis + Trust Infrastructure** — 168 commits making every analyzer speak the same format, every finding carry its own provenance, and the whole pipeline uniformly queryable, filterable, and auditable.

### Harmonized output across all analyzers

Every analyzer — schematic, PCB, Gerber, thermal, EMC, cross-analysis, SPICE, lifecycle — now produces the same top-level envelope:

```json
{
  "analyzer_type": "schematic",
  "schema_version": "1.3.0",
  "summary": { "by_severity": {...}, ... },
  "findings": [ {detector, rule_id, category, severity, confidence, ...} ],
  "trust_summary": { "total_findings": N, "by_confidence": {...}, ... }
}
```

The `signal_analysis` wrapper is gone. Subcircuit detections live in the same flat `findings[]` stream as validation checks, DFM rules, and audits. One schema to query, filter, and export.

- `finding_schema.py` — `make_finding()` factory, `Det` constants for all 60+ detectors, `get_findings()` / `group_findings()` consumer helpers
- All 75+ existing detectors migrated to the rich finding format
- 25 consumer files updated for the new layout
- `signal_analysis` wrapper removed from schematic output
- `confidence_map` removed — per-finding `confidence` is now canonical

### Trust infrastructure

Every finding carries its own trust metadata:

- **Confidence taxonomy** — `deterministic`, `heuristic`, `datasheet-backed`. Risk scores weight heuristic findings at 0.5x.
- **Evidence source taxonomy** — `parsed_schematic`, `parsed_pcb`, `datasheet_extraction`, `inference`, `heuristic_matching`, etc.
- **Provenance annotations** — `make_provenance()` calls on all 61 detectors (KH-263 Phase 1). Records which field was used, which datasheet was consulted, which inference chain led to the claim.
- **trust_summary** — rollup on every analyzer output: finding counts by confidence, by evidence source, datasheet coverage percentage.

Consumers (reports, what-if, release gate) now surface trust posture alongside findings.

### New detectors (22 total, across validation, domain, and audit families)

**Validation detectors** (`validation_detectors.py`):
- PU-001 pull-up/pull-down resistor presence
- VM-001 cross-domain voltage mismatch
- PR-001..004 protocol electrical validation (I2C, SPI, CAN, USB)
- PS-001 power sequencing dependency graph
- LR-001 LED resistor sizing
- FS-001 feedback network stability pre-check

**Domain detectors** (`domain_detectors.py`):
- WL-001 wireless modules (WiFi/BLE, LoRa, cellular, GPS)
- TF-001 transformer SMPS feedback (optocoupler + TL431)
- IA-001 I2C address conflicts
- SC-001 supercapacitor / energy harvesting
- PL-001 PWM LED dimming topology
- AH-001 audio headphone jack switch

**Audit detectors** (new pattern — banner-level findings that aggregate evidence across many components):
- SS-001 / SS-002 sourcing-gate audits (MPN coverage, BOM-line coverage)
- DS-001 / DS-002 / DS-003 datasheet-coverage audits
- RS-001 / RS-002 rail-source audit (jumper-aware trace from rails to regulators/sources)
- LB-001 label-alias audit (multi-label nets)
- PP-001 power-pin DC-path audit (IC power pin DC continuity to a rail)
- NT-001 unnamed-net annotation

### PCB intelligence

New `pcb_connectivity.py` — union-find copper connectivity graph built from pads, tracks, vias, and zone fills. Produces per-net island map with gap locations, disconnected pad pairs, and a full component graph (`--full` mode).

Six new cross-domain PCB checks consuming the connectivity graph:
- NR-001 critical net routing near board edges
- RP-002 return path continuity (plane gaps under classified signals)
- TW-001 trace width validation vs current (IPC-2152)
- PS-002 power supply island detection
- VS-002 voltage plane split detection (with signal-crossing analysis)
- DP-005 differential pair routing quality (via/layer/length asymmetry)

Seven new assembly/DFM checks:
- FD-001 fiducial presence
- TE-001 test point coverage
- OR-001 orientation consistency
- SK-001 silkscreen-on-pad overlap
- VP-001 via-in-pad tenting (`--full` only)
- BV-001 board-edge via clearance (`--full` only)
- KO-001 keepout violations

### Stage and audience filtering

All analyzers accept `--stage {schematic|layout|pre_fab|bring_up}` and `--audience {designer|reviewer|manager}` flags. Filter findings to what matters for each review phase. Stage readiness (`pass` / `needs_review` / `needs_work`) reported per phase.

### Datasheet pipeline

The datasheet workflow got its own top-level skill (`skills/datasheets/`), promoted from `skills/kicad/scripts/`:

- Structured per-MPN extraction cache in `datasheets/extracted/<MPN>.json`
- Heuristic page selection with TOC detection and keyword scoring
- Five-dimension quality scoring rubric
- Consumer helper API (`datasheet_features.py`) — returns None on cache miss / stale / low-score
- Cross-check extraction vs schematic usage (consistency verification)
- Trust gates on all consumers (thermal, SPICE, verifier) — extractions below score 6.0 are ignored

### Cross-analysis

`cross_analysis.py` — consumes schematic + PCB JSON, runs six cross-domain checks:
- CC-001 connector current capacity vs trace width
- EG-001 ESD coverage gap analysis
- DA-001 decoupling strategy adequacy
- XV-001 / XV-002 / XV-003 schematic/PCB cross-validation

### KiCad 10 format compatibility

- KH-318 PCB via type detection — fixed decade-old bug where `via["type"]` was always None. Now correctly classifies blind/buried/micro (buried added in KiCad 10 file version 20250926).
- KH-319 `(hide yes)` boolean handling — hidden pins on schematics saved by KiCad 9.0+ now correctly detected.

### Schema hardening (Batch 20)

- `schema_version: "1.3.0"` on every analyzer output
- Severity normalization (removed raw `critical/high/medium/low/info` aliases in favor of canonical severities)
- `confidence_map` field removed (replaced by per-finding `confidence`)
- Legacy `group_findings_legacy()` / `DETECTOR_TO_LEGACY_KEY` removed from first-party code
- `--schema` output synced to match real emitted JSON on all 8 analyzer types
- Deterministic `findings[]` ordering + stable `detection_id` (KH-316)

### Tools

- `summarize_findings.py` — cross-run finding summary. Reads the current analysis run, groups findings by rule_id, prints a severity × count table. `--top`, `--severity`, `--json` flags.
- `export_issues.py` — finding-to-GitHub-Issues export. Structured body, label-based dedup, severity/rule-id filters, dry-run by default.
- `--mpn-list FILE` on all four distributor sync scripts (KH-312) — batch datasheet sync without a KiCad project. Filters via `is_real_mpn()`, de-duplicates, skips blank lines and `#` comments.
- `analyze_thermal.py --schema` — rounds out the `--schema` coverage on all analyzers.

### Bugfixes (33+ KH-* issues closed)

Highlights:

- KH-311, KH-313 — EMC detector crashes on edge-case input
- KH-314 — thermal `--schema` support
- KH-315 — hierarchy_context schema drift
- KH-316 — deterministic findings[] ordering
- KH-317 — XT-001 diff-pair suppression path (session-10 regression)
- KH-318 / KH-319 — KiCad 10 format-compat (above)
- KH-312 — `--mpn-list` batch mode (above)
- KH-283, KH-284, KH-285, KH-286 — PCB analyzer crashes (crystal, netclass, pad position, rich-format migration)
- KH-263 Phase 1 — provenance annotation rollout

See the issue tracker (harness ISSUES.md / FIXED.md) for the complete list with root causes.

### Test corpus

- 5,829 repos, 2M+ regression assertions at 99.98% pass
- 972 unit tests, 0 failures
- Smoke cross-section (27 repos, 16,434 runs) green after KH-318/KH-319
- quick_200 cross-section (275 repos, 411,198 assertions) green
- Schema drift regression test covers all 8 analyzers (permanent since session 10)

### Known limitations shipped with v1.3

- `group_findings_legacy()` removed from first-party code but internal consumers (`what_if.py`, `diff_analysis.py`) still use a compat shim pending v1.4 Priority 0 modernization
- EMC and thermal `summary` retain raw `critical/high/medium/low/info` counts alongside `by_severity` for consumer migration
- Schematic and PCB outputs have deterministic top-level `findings[]` ordering, but nested-list ordering inside findings (e.g., `load_caps` under DO-DET) is not yet fully deterministic — v1.4 item
- `fab_release_gate.py` aggregates 4 analyzers (schematic, PCB, thermal, EMC), not cross_analysis — v1.4 enhancement

---

## v1.2.0 — 2026-04-09

**Theme: Trust + Reach** — 102 commits making the engine trustworthy to teams and reachable from both platforms.

### New skill: kidoc (beta)

Professional engineering documentation from KiCad projects. Auto-runs all analyses, renders schematics and PCB layouts, generates publication-quality figures, and produces markdown scaffolds with auto-updating data sections and narrative placeholders. Early skill with rough edges — actively developed.

- 8 report types: Hardware Design Description, CE Technical File, Design Review, Interface Control Document, Manufacturing Transfer, Schematic Review, Power Analysis, EMC Report
- Custom reports via `--spec` JSON files
- Output formats: PDF (ReportLab), DOCX (python-docx), ODT (odfpy), HTML, Markdown
- Schematic SVG renderer with KiCad-parity colors, font scaling, pin text, net annotations, crop/focus/highlight
- PCB layout renderer with 6 layer presets, net highlighting, crop, annotations
- 12 publication-quality figure generators: power tree, architecture, bus topology, connector pinouts, thermal margin, EMC severity, SPICE validation, Monte Carlo distributions
- Datasheet integration: comparison tables, pin audits, spec summaries
- Narrative engine: per-section context builder with writing guidance
- Hash-based figure caching — unchanged data skips re-render

### New detectors (15 domain-specific)

Extracted domain-specific detectors into `domain_detectors.py` (~4,500 LOC) alongside core `signal_detectors.py` (~3,100 LOC). 40+ total schematic detectors (was 25 in v1.0).

| Detector | What it finds |
|----------|---------------|
| ESD protection audit | Cross-references every external connector with TVS/ESD devices; flags unprotected pins |
| USB-C CC validation | Verifies 5.1k pull-downs on CC1/CC2; detects PD controller ICs as alternative |
| Debug interfaces | Detects SWD/JTAG connectors, verifies MCU connections |
| Power path / load switches | Load switch ICs, ideal diode / power MUX, USB PD controllers |
| ADC signal conditioning | Voltage references, anti-alias filters, input scaling |
| Reset / supervisor | Supervisor ICs, watchdog timers, RC reset circuits |
| Clock distribution | PLL / clock generators, oscillator outputs, reference crystal matching |
| Display / touch | Display drivers, backlight drivers, touch controller ICs |
| Sensor fusion | IMU / accelerometer / gyro / magnetometer / barometer ICs, interrupt connections |
| Level shifters | TXB/TXS ICs, discrete BSS138-based, voltage domain verification |
| Audio circuits | Amplifier ICs, codec chips, speaker impedance matching |
| LED driver ICs | PWM / matrix / constant-current drivers |
| RTC circuits | RTC ICs, backup battery detection, crystal pairing |
| LED lighting audit | Chain tracing (5 hops), current limiting resistor verification, multi-pin exclusion |
| Thermocouple / RTD | Thermocouple amplifiers, RTD interfaces, cold junction compensation |
| Power sequencing | Power-good daisy chains, enable chain validation, cross-rail dependencies |
| LVDS interfaces | FPD-Link, DS90, SN65LVDS families with serializer/deserializer classification |

### First-class Codex support

- `.agents/skills/` with symlinks to all 11 skills for auto-discovery
- `.agents/plugins/marketplace.json` for Codex marketplace browsing
- Enriched `.codex-plugin/plugin.json` with full metadata
- Agent-neutral language across all SKILL.md files and references
- README presents Claude Code and Codex as equal install paths
- GitHub Action docs cover both `claude-code-action` and `codex-action`

### Project config and suppressions

- `.kicad-happy.json` project config: compliance target, derating profile, preferred suppliers, board class, rail overrides, BOM conventions
- Per-finding suppressions with reasons: `suppress: [{rule: "DC-001", ref: "C5", reason: "intentional"}]`
- Suppressed findings listed but marked, not hidden; active vs suppressed counts in summary
- Cascading config: project-level merges with user-level `~/.kicad-happy.json`
- Design intent auto-detection (hobby/consumer/industrial/medical/automotive/aerospace)
- IPC class detection from fab notes with class-aware DFM thresholds

### Report improvements

- **Per-finding confidence labels**: deterministic, datasheet-backed, heuristic, AI-inferred
- **Missing information section**: separates "I don't know" from "there's a problem"
- **Top-risk summary**: top 3 respin risks, bring-up blockers, and manufacturing blockers
- **Fabrication release gate**: 8-category "ready for fab?" check (routing, BOM, DFM, documentation, schematic-PCB consistency, Gerbers, thermal, EMC)

### Schematic-to-PCB cross-verification

New `cross_verify.py` with 7 cross-checks:
- Component reference bidirectional matching (orphans, missing, value mismatches, DNP conflicts)
- Differential pair length matching with per-protocol tolerances (USB 2mm, Ethernet 5mm, HDMI 1mm)
- Differential pair intra-pair skew check per protocol
- Power trace width assessment per regulator output rail
- Decoupling cap placement distance cross-check
- Bus routing advisory (signal lengths, SPI clock-to-data skew)
- Thermal via adequacy check

### Protocol electrical parameter checks

Complete coverage across all major protocols:
- **I2C**: Pull-up rise time validation, speed mode assessment, open-drain VOL compatibility, bus current budget
- **SPI**: Chip select conflict detection, device loading advisory, signal integrity (series termination)
- **UART**: TX/RX crossover verification, RS-232 transceiver detection with charge pump cap check
- **USB**: CC resistor validation (5.1k sink, source levels), D+/D- series resistors, VBUS capacitor sizing
- **Ethernet**: Bob Smith termination detection, magnetics/impedance advisory
- **HDMI**: 100ohm TMDS differential termination check
- **CAN**: 120ohm termination detection

### What-if enhancements

- **Sweep tables**: `R5=1k,2.2k,4.7k,10k` (comma list) and `R5=1k..100k:10` (log range) with markdown table output
- **Tolerance analysis**: `R5=4.7k+-5%` worst-case corner analysis (2^N combinations)
- **Fix suggestions**: `--fix voltage_dividers[0] --target 3.3` with E12/E24/E96 snapping
- **EMC impact preview**: `--emc` runs analyze_emc.py on patched JSON, diffs findings
- **PCB parasitic awareness**: `--pcb` with auto-discovery, trace R/L injection, footprint compatibility

### Detection schema

Centralized all per-detection-type metadata into `detection_schema.py`. Eliminated 4 hard-coded consumer-side registries (`_DERIVED_FIELDS`, `_recalc_derived`, `SIGNAL_REGISTRY`, `PRIMARY_METRIC`). Adding a new detection type is now 1 schema entry instead of 4-file edits.

### Diff analysis improvements

- **Cache integration**: `--analysis-dir` / `--run` for diffing runs from analysis cache
- **Multi-run trends**: `--trend N` shows metric evolution across last N runs
- **Change attribution**: "cutoff_hz changed because R5 went from 1k to 4.7k"
- **Regression detection**: flags new ERC warnings, removed protections, SPICE pass-to-fail, EMC score increases
- **Stable detection IDs**: hash-based `detection_id` on every signal detection for ref-renumbering resilience

### Analysis enrichment (complete)

Phase 1-4 enrichment across schematic, PCB, and EMC outputs:
- Bus electrical parameters: I2C speed mode, voltage, pull-up ohms; CAN termination; bus device dicts with controller field
- Power dissipation for switching regulators (buck/boost/buck-boost with efficiency estimates)
- Crystal load cap validation (target, error%, ok/marginal/out_of_spec)
- ESD device details on connector audit entries
- Decoupling proximity matrix in PCB output
- Switching loop area pre-computation in PCB output (via --schematic flag)
- EMC category summary pre-rollup

### Datasheet verification bridge

New `datasheet_verify.py` bridges extracted datasheet data with schematic analysis:
- Pin voltage abs_max violation (CRITICAL) and operating range exceeded (HIGH/MEDIUM)
- Missing required external components per datasheet pin specs
- Per-IC decoupling verification against application circuit recommendations
- Activates automatically when `datasheets/extracted/` cache exists

### Professional quick wins

- Fab notes completeness check (IPC class, surface finish, thickness, copper weight, material)
- Silkscreen completeness audit (revision, board name, ref visibility, connector labels, polarity)
- BOM lock verification (MPN coverage %, missing MPNs, generic values)
- Connector ground pin distribution (flag >4 signal pins per ground)
- Certification requirement identification (FCC/CE/IEC/UL from detected RF, battery, USB, Ethernet, high voltage)

### Analysis cache integration

All analyzers now support `--analysis-dir` for automatic cache management:
- Timestamped run folders with manifest tracking
- Copy-forward of unchanged outputs between runs
- Automatic new-run vs overwrite-current decision based on diff severity
- Pre-analysis datasheet sync prompt in skill workflow

### Sub-sheet detection (KH-228)

Detection rate improved from 34% to 99% using `.kicad_pro` stem matching as primary heuristic. Zero false positives on root schematics.

### Registry trust & CI

- GitHub Actions CI workflow (py_compile on Python 3.8 + 3.12)
- CODE_OF_CONDUCT.md (Contributor Covenant v2.1)
- Dependabot for GitHub Actions version tracking
- SECURITY.md moved to `.github/` for scanner compatibility
- Security architecture documentation in SKILL.md (Snyk W011 mitigation)

### Additional analysis improvements

- **Hierarchical context for sub-sheets**: automatic root schematic discovery and cross-sheet net resolution when analyzing individual sub-sheets
- **Sleep current estimation**: realistic vs worst-case analysis, per-rail breakdown with EN pin detection and GPIO state inference
- **Keepout zone analysis**: surface area calculation, ESD IC decoupling proximity checks, touch pad GND clearance verification
- **Lifecycle audit integration**: wired into analyzer via `--lifecycle` flag, queries 4 distributor APIs
- **Technical debt cleanup**: shared detector helpers (`detector_helpers.py`), hoisted 40+ deferred imports, consolidated duplicate calculations, tightened exception handling
- **`.kicad_pro` / `.kicad_dru` / library table parsing**: net classes, design rules, text variables from project files

### E-series standard values

- E12, E24, E96 decade tables in `kicad_utils.py`
- `snap_to_e_series()` function for component value snapping
- Used by what-if fix suggestions and EMC decoupling recommendations

### Bugfixes (25 issues)

KH-194 through KH-228 — most discovered via automated Layer 3 LLM batch review:

- KH-194: ESD audit "can" word boundary matching "scan"
- KH-195: USBPDSINK01 assertion update for PD controller detection
- KH-196: Bare capacitor values parsed as Farads in inrush/PDN calculations
- KH-197: Key matrix topology false positives (19 boards fixed)
- KH-198: LC filter reference collision in multi-project schematics
- KH-199/200: None rail names crash power_tree and narrative
- KH-204: power_rails uses UUID sheet paths instead of human-readable names
- KH-206: Global labels with different names merged into one net
- KH-207: Legacy KiCad 5 matrix decomposition producing wrong pin positions
- KH-208: Component type classification ignoring lib_id for Connector/Sensor/Motor/CircuitBreaker
- KH-209: Power rails with nnVn naming pattern (3V3, 12V0) classified as signal
- KH-210: SPI chip select detection missing CSN/NCS/SSEL patterns
- KH-211: pin_nets filtering out unnamed nets (hiding sub-sheet connections)
- KH-212: Bare capacitor values <1.0 parsed as Farads instead of microfarads
- KH-213: P-MOSFET detection missing PMOS/P-MOS/P-MOSFET keyword variants
- KH-214: INA2xx power monitors misclassified as opamp circuits
- KH-215: LM2576/LM2596 switching bucks classified as LDO
- KH-216: Multi-unit IC pin_nets showing wrong unit's pins
- KH-217: Crystal frequency parsing case-sensitive (kHZ/MHZ not matched)
- KH-218: Vref heuristic wrong for TPS62912, TPS73601, LM22676
- KH-219: Load switches classified as LDO topology
- KH-220: Active oscillators with custom lib symbols misclassified as connector
- KH-221: Opamp TIA feedback classified as compensator; false voltage dividers
- KH-222: Multi-unit symbol duplication in led_audit/sleep_current/usb_compliance
- KH-223: Power sequencing cascade not resolved (overbar pin name matching)
- KH-224: Multi-unit IC power_domains only showing one unit's rails
- KH-225: Charge pump LM2664 classified as LDO (now charge_pump topology)
- KH-226: NUCLEO dev board module classified as switching regulator
- KH-227: Logic gates misclassified as level_shifter_ic
- KH-228: detect_sub_sheet only identifying 34% of sub-sheets
- AP63357/AP632xx Vref entries added (0.8V)
- EMC IO-001 jumper false positive exclusion

### Validation

- 681,000+ schematic + 517,000+ EMC regression assertions at 100% pass rate
- 5,829 repos, 40+ schematic detectors, 42 EMC rules, 17 SPICE subcircuit types
- 400+ unit tests across 22 test files
- 0 open issues at release
- 102 commits since v1.1.0

---

## v1.1.0 — 2026-04-02

**EMC Pre-Compliance + Analysis Toolkit**

### New skill: EMC pre-compliance

42 rule checks across 17 categories predicting EMC test failures from schematic and PCB data. SPICE-enhanced when ngspice is available. Covers FCC, CISPR, automotive, and military standards.

| Category | Rule IDs |
|----------|----------|
| Ground plane integrity | GP-001, GP-002 |
| Decoupling | DC-001 through DC-005 |
| I/O filtering | IO-001 through IO-003 |
| Switching harmonics | SW-001, SW-002 |
| Clock routing | CK-001 through CK-004 |
| Differential pairs | DP-001, DP-002 |
| PDN impedance | PD-001 through PD-004 |
| ESD paths | ES-001 |
| Via stitching | VS-001 |
| Board edge radiation | BE-001 |
| Thermal-EMC coupling | TE-001 |
| Shielding | SH-001 |
| Crosstalk | XT-001, XT-002 |
| Connector filtering | CF-001 |
| Return path continuity | RP-001 |
| Cavity resonance | CR-001 |
| Component placement | CP-001 |

SPICE enhancements: lumped and distributed PDN impedance sweep, EMI filter insertion loss verification, switching harmonic FFT via Goertzel algorithm, capacitor suggestion verification.

### New analysis tools

- **Monte Carlo tolerance analysis** — `--monte-carlo N` runs N simulations with randomized component values. Reports 3-sigma bounds and per-component sensitivity (Pearson r-squared).
- **Design diff** — compares two analysis JSONs, reports component/signal/EMC/SPICE changes. GitHub Action `diff-base: true` for automatic PR comparison.
- **Thermal hotspot estimation** — junction temperature for LDOs, switching regulators, shunt resistors. Package theta-JA lookup, thermal via correction, proximity warnings. 7 rule IDs (TS-001..005, TP-001..002).
- **What-if parameter sweep** — patches component values, recalculates derived fields, optional SPICE re-simulation.

### Plugin distribution

- Published on official Anthropic Claude Code marketplace
- Install: `/plugin marketplace add aklofas/kicad-happy`

### Code audit (22 fixes)

3 critical, 9 high, 6 medium, 4 low severity fixes discovered during comprehensive code audit:

- **Critical**: Trace inductance formula 25x overestimate, circular board bounding box wrong, inner-layer traces mapped to wrong reference plane
- **High**: PDN target impedance 2x too lenient, Goertzel normalization missing 2x factor, two-digit regulator suffix parser (LM2596-12 read as 1.2V), operator precedence in decoupling shared nets, courtyard shapes silently dropped, GP-002 ignoring 2-layer boards, via stitching counting all vias (not just ground), unknown SMPS skipping EMC checks, Tier 2 functions not using AnalysisContext
- **Medium**: No-connect sheet collision, rail voltage estimation duplication, distributed PDN magnitude addition, PCB --full mode re-parsing, zone fill detection KiCad 9/10, layer alias type guard, ground net name matching, SH-001 INFO noise, DC bias derating

### Validation

- 6,853 EMC analyses across 1,035 repos (zero crashes)
- 96 equations verified against primary sources
- 404,558 regression assertions at 100% pass rate
- 30,646 SPICE simulations

---

## v1.0 — 2026-03-31

**First Stable Release**

The first production-ready release. Every piece of the analysis pipeline — schematic parsing, PCB layout review, Gerber verification, SPICE simulation, datasheet cross-referencing, BOM sourcing, and manufacturing prep — built and tested against 1,035 real-world KiCad projects.

### Schematic analysis

- S-expression parser for KiCad 5-10 `.kicad_sch` and legacy `.sch` files
- 25 subcircuit detectors: regulators (buck/boost/LDO), filters (RC/LC/pi/notch), opamps, H-bridges, rectifier bridges, protection circuits, bus protocols, crystal oscillators, current sense, decoupling, voltage dividers
- Mathematical verification: feedback divider calculations, filter cutoff frequencies, power dissipation, bias current paths
- Voltage derating: ceramic (50%), electrolytic (80%), tantalum capacitors; IC absolute max; resistor power. Commercial, military, and automotive profiles.
- Protocol validation: I2C pull-up value and rise time, SPI chip select counts, UART voltage domain crossing, CAN termination
- Op-amp checks: bias current paths, capacitive output loading, high-impedance feedback, unused channels

### PCB layout analysis

- Footprint parsing, track/via/zone analysis, thermal management, DFM scoring
- Thermal via adequacy per pad
- Impedance calculation from stackup parameters
- Differential pair matching and proximity/crosstalk analysis
- Zone stitching, tombstoning risk, courtyard overlap detection

### SPICE simulation

- Auto-generated testbenches for 17 subcircuit types
- Per-part behavioral models (~100 opamps)
- PCB parasitic injection (trace resistance, via inductance)
- Multi-simulator: ngspice, LTspice, Xyce

### Datasheet infrastructure

- Structured extraction cache with quality scoring (5-dimension rubric)
- Heuristic page selection for large PDFs
- DigiKey API as primary datasheet source (direct PDF URLs)
- SPICE spec integration from extracted data

### Component sourcing

- DigiKey (OAuth 2.0), Mouser (API key), LCSC (jlcsearch, no auth), element14/Newark/Farnell
- Per-supplier order file export, pricing comparison
- Datasheet sync: 96% download success rate across corpus

### Manufacturing

- JLCPCB and PCBWay format export (BOM + CPL)
- Design rule validation per fab house
- Basic vs extended parts classification (JLCPCB)
- Rotation offset tables

### Lifecycle audit

- Component EOL/NRND/obsolescence alerts from 4 distributor APIs
- Temperature grade auditing (commercial/industrial/automotive/military)
- Alternative part suggestions

### Gerber verification

- Layer identification, alignment checks, drill analysis
- Zip archive scanning
- Mixed plating detection, NPTH classification

### GitHub Action

- Automated PR reviews on KiCad file changes
- Two-tier: deterministic analysis (free) + optional AI review via Claude
- Commit status checks with findings summary

### KiCad support

- KiCad 5, 6, 7, 8, 9, 10
- Legacy `.sch` format
- Single-sheet and multi-sheet hierarchical designs
- Integer and string net ID formats (KiCad 10 change)

### Validation

- 1,035 repos, 6,845 schematic files, 3,498 PCB files, 1,050 Gerber directories
- 312,956 components parsed, 531,418 nets traced
- 294,000+ regression assertions at 100% pass rate
- 30,646 SPICE simulations across 17 subcircuit types
