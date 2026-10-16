# Architecture notes (v3 arc, living document)

This file records the few decisions a contributor needs that the code does not state on its own. It is expanded in round 7 of the v3 refactor (module ownership map); until then it holds the dependency rules and the facade register.

## Dependency rules (enforced by `tools/check_refactor.py imports`)

- `kicad` and `datasheets` are the **core**; every other skill is optional.
- An optional skill may import the core. It never imports another optional skill.
- Inside `skills/kicad/scripts/`, `kicad_core/` imports stdlib and itself only.
- No module imports a CLI module (`analyze_*.py`, `cross_analysis.py`, `diff_analysis.py`, `what_if.py`, `lifecycle_audit.py`, `simulate_subcircuits.py`, `bom_manager.py`); shared code lives in a non-CLI module.
- Existing violations are listed in `tools/import_baseline.json`. The list may only shrink; CI fails on a new entry. A verbatim file move may relocate entries with `imports --update-baseline --moved-from FILE`, which accepts a new entry only when an entry of the same shape was retired from that file.
- Deliberate, dated exceptions live in `tools/layer_rules.json` under `exceptions`, each with a reason and a retire-by round; they are listed on every `imports` run.

## Finding emit sites (enforced by `tools/check_refactor.py tags`)

Every emit site carries literal string keywords `detector=`, `rule_id=` and `schema_era=`. An emit site is a `make_finding`/`_make_finding` call, or a caller of a dict-returning `_make_*` factory. A `_make_*` wrapper whose own inner `make_finding` call carries all three literals is itself the emit site, and its callers are not scanned. `_make_*` helpers that are not finding factories are ignored. Known legacy sites are in `tools/tag_baseline.json`; the list may only shrink. Moving an emit site to another file uses `tags --update-baseline --moved-from FILE`, which never lets the count of untagged shapes grow. Emitted detector strings and rule IDs are public API and never change.

## Facade register

A facade is code kept only so a named consumer keeps working. Each entry names the consumer and the condition that retires it. Round 9 of the v3 arc requires this table to be empty or every row re-justified.

| Symbol | Location | Consumer | Retire when |
|---|---|---|---|
| `make_finding(design_context=...)` ignored keyword | `skills/kicad/scripts/finding_schema.py` | harness contract tests (one real call: `tests/contract/test_finding_id.py:118`; two docstring mentions) | harness migrates per round-1 relocation map |
| `AnalysisContext.design_context`, `AnalysisContext.hierarchy_context` fields | `skills/kicad/scripts/kicad_types.py` | harness fixtures (`tests/fixtures/_build_ctx.py`, 15 contract files, `tests/test_schema_drift.py`, `tools/generate_catalog.py`) | same |
| `lookup_helpers.read_design_context` | `skills/kicad/scripts/lookup_helpers.py` | harness `tests/contract/test_lookup_helpers.py` | same |
| `kicad_utils` (whole module, 72 re-exports) | `skills/kicad/scripts/kicad_utils.py` | harness (10 names: is_power_net_name, is_ground_name, MPN_FIELD_ALIASES, MPN_FIELD_ALIASES_PRIMARY, normalize_field_name, lookup_regulator_vref, classify_component); user scripts | round 9, after harness and Action import `kicad_core.*` |
| `diff_analysis` re-exports of `diff_engine` names | `skills/kicad/scripts/diff_analysis.py` | harness `tests/test_diff_analysis.py`, `tests/test_detection_schema.py` (`SIGNAL_REGISTRY`), `tests/contract/test_diff_deep_review.py` | same |
| `sexp_parser` (whole module) | `skills/kicad/scripts/sexp_parser.py` | harness `validate/verify_parser.py`, `tests/...` (1 import); docs `skills/kicad/SKILL.md:810` (edit in place in round 9; SKILL.md is at its line ceiling), `skills/kicad/scripts/README.md`, `skills/kicad/scripts/methodology_schematic.md`, `skills/kicad/scripts/methodology_pcb.md`, `skills/kicad/references/pcb-layout-analysis.md`, `skills/kicad/references/supplementary-data-sources.md` | round 9, after the harness imports `kicad_core.sexp` and those docs point at `kicad_core.sexp` |
| `analyze_schematic.build_pin_to_net_map` (import binding) | `skills/kicad/scripts/analyze_schematic.py` | harness (2 sites) | round 9 |
| `signal_detectors.detect_led_drivers` (alias of `enrich_transistor_led_drivers`) | `skills/kicad/scripts/signal_detectors.py` | none known in the harness inventory; user scripts | round 9 |
| `bus_resolver` (whole module) | `skills/kicad/scripts/bus_resolver.py` | harness `tests/test_bus_resolver.py` | round 9, after the harness imports `schematic.connectivity` |
| `project_config.load_jsonc`, `project_config._strip_jsonc` re-exports | `skills/kicad/scripts/project_config.py` | harness `tests/test_kh368_jsonc.py`, `tests/test_kh400_jsonc_trailing_comma.py` | same |
| `_core_path` helpers | `skills/{emc,spice,bom}/scripts/_core_path.py` | the skills themselves | permanent (not a facade; listed for discoverability) |
| `AnalysisContext.__post_init__` fill-when-empty derivation | `skills/kicad/scripts/kicad_types.py` | harness: 26 direct `AnalysisContext(...)` constructions in 20 files + `tests/fixtures/_build_ctx.py` | harness builds contexts with `build_analysis_context` (round-3 relocation map) |
| `signal_detectors._get_net_components` index-less branch | `skills/kicad/scripts/signal_detectors.py` | same harness contexts (no `nq`) | same |
| `schematic.pipeline.parse_legacy_schematic` (alias of `analyze_legacy_schematic`) | `skills/kicad/scripts/schematic/pipeline.py` | none known in the harness inventory; user scripts (re-exported through `analyze_schematic`) | round 9 |
| `analyze_schematic` module re-exports (115 names from `schematic.*` and `kicad_core.*`) | `skills/kicad/scripts/analyze_schematic.py` | harness (13 imports: `build_net_map`, `_detect_differential_pairs`, `validate_hierarchical_labels`, `detect_sub_sheet`, `audit_pwr_flags`, `audit_datasheet_coverage`, `audit_sourcing_gate`, `analyze_usb_compliance`, `analyze_sleep_current`, `analyze_power_budget`, `analyze_bus_topology`, `_estimate_rail_voltage`, and `import analyze_schematic as asch` attribute access); user scripts | round 9, after the harness imports `schematic.*` |

`_core_path` anchors on `Path(__file__).resolve()`, so a symlinked skill directory resolves to its real parent before walking up to `skills/`; the previous ad hoc inserts used `os.path.abspath` (no symlink following). Byte-identical copies live in emc, spice and bom by design.

## `skills/kicad/scripts/kicad_core/` ownership (round 2)

| Module | Owns | Imports |
|---|---|---|
| `fields.py` | property-field aliases, `pick_field`/`pick_mpn`/`get_mpn_property` | stdlib |
| `values.py` | `parse_value`, tolerance, E-series, coordinate units | stdlib |
| `parts.py` | regulator Vref and switching-frequency tables | stdlib |
| `classify.py` | component / IC-function / connector / jumper classification | stdlib |
| `netnames.py` | rail, ground, USB-net recognition; voltage-from-name | stdlib |
| `passives.py` | capacitor package/ESR/ESL, dielectric, derating, inductor shielding | stdlib |
| `project.py` | `.kicad_pro`/`.kicad_dru`/lib-table readers, root-schematic discovery | stdlib (+ kicad_core.sexp); also hosts `load_jsonc` / `_strip_jsonc` |
| `sexp.py` | S-expression parser (parse/find/get helpers) | stdlib |
| `model.py` | typed records: Component/Pin/NetPin/NetLabel/Net TypedDicts, PinNetEntry, SheetData, ResolvedConfig | stdlib |
| `netquery.py` | net helpers (`get_two_pin_nets`, `build_net_id_map`), `build_pin_to_net_map`, `build_ref_pins`, `BridgeFact`/`BridgeFacts`/`build_bridge_facts` | `model`, `values` |

`kicad_core` imports stdlib and itself only (CI-enforced).

## `skills/kicad/scripts/schematic/` ownership (round 4)

| Module | Owns | Imports |
|---|---|---|
| `reader.py` | `.kicad_sch` symbols, pins, wires, labels, sheets → `SheetData` | `kicad_core` |
| `legacy_reader.py` | KiCad 5 `.sch` / `.lib` reading, pin snapping | `kicad_core`, `reader` (field-key tuples) |
| `hierarchy.py` | sheet traversal (`parse_all_sheets`), `top_level_sheets` merge | `kicad_core`, `reader` |
| `connectivity.py` | `build_net_map`, bus pass (`BusGraph`, `expand_bus_name`, `match_ports`), label output filter | `kicad_core` |
| `ic_analysis.py` | IC function classification, pinouts, subcircuits | `kicad_core`, `kicad_types`, `connectivity` |
| `net_analysis.py` | net classification, power domains, bus/protocol detection, diff pairs, ERC-style checks, `analyze_design_rules` | `kicad_core`, `kicad_types` |
| `audits.py` | annotation / label / PWR_FLAG / footprint / sourcing / DNP / symbol / coverage audits | `kicad_core`, `connectivity` |
| `system_analyses.py` | PDN, sleep current, derating, protocol compliance, power budget/sequencing, BOM optimisation, test coverage, assembly, USB, inrush | `kicad_core`, `kicad_types`, `net_analysis`, `finding_schema` |
| `bom_stats.py` | `generate_bom`, `compute_statistics` | `kicad_core` |
| `pipeline.py` | the named phases (topologies → reconcile → domain detectors → signal assembly; project: read → context → analyses → assemble; `finalize_for_cli`) | everything above, the detector modules, `kicad_types`, `finding_schema` |
| `presentation.py` | result-dict assembly in the historical key order; legacy result | `kicad_core`, `bom_stats`, `connectivity`, `finding_schema` |

Mutation contract (D4): `reconcile_detections` rewrites phase-1 records in place; `assemble_signal_results` enriches capacitor entries in place; `assemble_result` adds `category`/`parsed_value`/`pin_nets` to components and pops `_unit_pins`; `finalize_for_cli` mutates the result (findings filtering, summary recompute). Nothing else mutates caller-owned lists.
