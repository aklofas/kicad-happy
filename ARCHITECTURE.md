# Architecture notes (v3 arc, living document)

This file records the decisions a contributor needs that the code does not state on its own: which contracts are frozen, which way imports may point, which module owns what, and which code is kept only for a named consumer. The per-package ownership tables for `kicad_core/`, `schematic/`, `pcb/` and `distributor_core/` follow the top-level module map. The facade register lists compatibility code that is retired in round 9 of the v3 arc.

## Contracts: frozen and open

Frozen for the whole arc:

- input formats (`.kicad_sch`, `.sch`, `.kicad_pcb`, Gerber/Excellon, `.kicad-happy.json`, `.kicad_dru`);
- readability of artifacts written by earlier versions: saved analysis JSON (by `diff_analysis`, `what_if`, `summarize_findings`, the Action renderer), datasheet manifests, extraction caches, `analysis/manifest.json`;
- rule IDs and emitted `detector` strings (users' suppression configs, harness identities);
- script paths, skill names, CLI flags and exit codes.

Open, under the round-8 budget: output key order, EMC finding shape, severity vocabulary, `schema_era` coverage, swallowed exceptions becoming diagnostics, additive schema fields. `finding_id`s may move where content legitimately changes. Wholesale output key renames (`ref`→`reference`, `net`→`net_name`) are **excluded**; a key is renamed only where it is actively misleading, and each such rename is listed in the round-8 budget.

Everything outside the round-8 budget is expected to produce strict-field identical output.

## Dependency rules (enforced by `tools/check_refactor.py imports`)

- `kicad` and `datasheets` are the **core**; every other skill is optional.
- An optional skill may import the core. It never imports another optional skill.
- Inside `skills/kicad/scripts/`, `kicad_core/` imports stdlib and itself only.
- No module imports a CLI module (`analyze_*.py`, `cross_analysis.py`, `diff_analysis.py`, `what_if.py`, `lifecycle_audit.py`, `simulate_subcircuits.py`, `bom_manager.py`); shared code lives in a non-CLI module.
- Existing violations are listed in `tools/import_baseline.json`. The list may only shrink; CI fails on a new entry. A verbatim file move may relocate entries with `imports --update-baseline --moved-from FILE`, which accepts a new entry only when an entry of the same shape was retired from that file.
- Deliberate, dated exceptions live in `tools/layer_rules.json` under `exceptions`, each with a reason and a retire-by round; they are listed on every `imports` run.

**Policy names.** Several predicates look alike but encode different policies; each carries its own name so a caller picks one on purpose. The differences below are copied from each variant's docstring; the shared predicate's accepted set is read from its code.

- `kicad_core.netnames.is_ground_name` is the shared ground predicate. It strips a sheet path, then accepts the exact ground set (GND, VSS, AGND, DGND, PGND, GNDPWR, GNDA, GNDD, SGND, COM, 0V), the 0V<suffix> family (0VA, 0V_A, +0V; not 0V<digit>), battery-negative names (BATT-, VBAT_N, ...) and GND-prefix/suffix and VSS-prefix patterns.
- `emc_rules.is_emc_ground_name` (EMC rules) differs from `is_ground_name`: it also accepts EARTH and VEE, and does not accept COM, the 0V<suffix> family (only the literal 0V) or battery-negative names.
- `cross_analysis.is_cross_analysis_ground_name` (cross-analysis checks) removes every `/`, `-` and `_` and then matches an exact set. It also accepts EARTH and CHASSIS. It has no GND-prefix/suffix or VSS-prefix patterns (SGND, GNDPWR, GND_ISO, VSSA are not ground), no COM, no 0V<suffix> family and no battery-negative names. A sheet path is concatenated, not stripped: "/Power/GND" is not ground, "/GND" is.
- `kicad_core.classify.classify_ic_function` returns a fixed enum (`mcu`, `fpga`, `memory`, ..., `other_ic`) used for component classification.
- `schematic.ic_analysis.classify_ic_pinout_role` returns the free-form label serialised as `ic_pin_analysis[].function` ("linear regulator", "microcontroller", ...). It is disjoint from `classify_ic_function`.

Two pin-name tables follow the same rule: `validation_detectors._PS_PG_PIN_NAMES` is PS-001's power-good set, and `domain_detectors._PG_PIN_NAMES` is a deliberately wider set for power-sequencing detection.

## Finding emit sites (enforced by `tools/check_refactor.py tags`)

Every emit site carries literal string keywords `detector=`, `rule_id=` and `schema_era=`. An emit site is a `make_finding`/`_make_finding` call, or a caller of a dict-returning `_make_*` factory. A `_make_*` wrapper whose own inner `make_finding` call carries all three literals is itself the emit site, and its callers are not scanned. `_make_*` helpers that are not finding factories are ignored. `schema_era` is `v1.4` for the datasheet-authority detectors and `v3.0` for every site whose emitted dict changed in the v3 line. `tools/tag_baseline.json` records the 56 detector/rule literal shapes that predate the checks, and may only shrink. Moving an emit site to another file uses `tags --update-baseline --moved-from FILE`, which never lets the count of untagged shapes grow. Emitted detector strings and rule IDs are public API and never change.

## Round 8 output changes

Round 8 changed output under five budget classes, with magnitudes in `handoff-round8.md` in the arc folder.

- B1: a `diagnostics` list at the root of every analyzer envelope and the SPICE report (`[]` when nothing degraded); the six `--schema` outputs gain the property.
- B2: EMC `findings[*]` take `make_finding`'s key order and lose `title` (its text is `summary`); `finding_id` is unchanged; the same removal in `audience_summary.*.top_issues`.
- B3: `schema_era: "v3.0"` is added on findings of the 89 previously untagged emit sites and on RS-001/PP-001.
- B4: one severity vocabulary (`info`/`warning`/`error`) in `datasheet_verification` (findings and `summary.by_severity`), `cross_verify.py` output and `summarize_findings` (`high` becomes `error`); legacy names are accepted on input only.
- B5: RS-001 is removed on nets whose only `power_in` pins are bootstrap-named (KH-454); PP-001 is added on boards with duplicate component refs (KH-455).

Behaviour changes outside the budget leave output identical at defaults: the config knobs (`retention`, `diff_threshold`, `output_dir`), EMC and SPICE runs through `output_io.write_primary_run`, and KH-463 (SPICE workdir). Round 8 added no facade rows: `analyze_schematic` binds no `validate_power_sequencing`.

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
| `_core_path` helpers | `skills/{emc,spice,bom,digikey,mouser,lcsc,element14}/scripts/_core_path.py` | the skills themselves | permanent (not a facade; listed for discoverability) |
| `AnalysisContext.__post_init__` fill-when-empty derivation | `skills/kicad/scripts/kicad_types.py` | harness: 26 direct `AnalysisContext(...)` constructions in 20 files + `tests/fixtures/_build_ctx.py` | harness builds contexts with `build_analysis_context` (round-3 relocation map) |
| `signal_detectors._get_net_components` index-less branch | `skills/kicad/scripts/signal_detectors.py` | same harness contexts (no `nq`) | same |
| `schematic.pipeline.parse_legacy_schematic` (alias of `analyze_legacy_schematic`) | `skills/kicad/scripts/schematic/pipeline.py` | none known in the harness inventory; user scripts (re-exported through `analyze_schematic`) | round 9 |
| `analyze_schematic` module re-exports (115 names from `schematic.*` and `kicad_core.*`; re-exports the names the module DEFINED at the round-3 tip, incl. 7 round-4 additions; names it merely imported, e.g. `parse_file`, `classify_component`, `make_finding`, `AnalysisContext`, are not re-bound, no known consumer) | `skills/kicad/scripts/analyze_schematic.py` | harness (13 imports: `build_net_map`, `_detect_differential_pairs`, `validate_hierarchical_labels`, `detect_sub_sheet`, `audit_pwr_flags`, `audit_datasheet_coverage`, `audit_sourcing_gate`, `analyze_usb_compliance`, `analyze_sleep_current`, `analyze_power_budget`, `analyze_bus_topology`, `_estimate_rail_voltage`, and `import analyze_schematic as asch` attribute access); user scripts | round 9, after the harness imports `schematic.*` |
| `pcb_connectivity` (whole module, 9 re-exports) | `skills/kicad/scripts/pcb_connectivity.py` | user scripts and the scripts README; no harness import | round 9 |
| `analyze_pcb` module re-exports (94 defined names, `main` excluded, plus the imported `parse_file` and `build_connectivity_graph` the harness binds through it) | `skills/kicad/scripts/analyze_pcb.py` | harness: 15 `from analyze_pcb import` names (`MIN_REAL_DRILL_MM`, `_pad_drills`, `ZoneFills`, `_dist_point_to_segment`, `_compute_switching_loop_areas`, `_degenerate_drills`, `_nearest_zone_copper_distance`, `_pad_on_layer`, `_pad_outline_points`, `analyze_pcb`, `analyze_design_rule_compliance`, `analyze_placement`, `_chain_segments`, `analyze_via_in_pad`, `analyze_vias`), `import analyze_pcb as ap` attribute access, and two `patch.object(analyze_pcb, ...)` sites (`extract_footprints`, `build_connectivity_graph`) that migrate to `pcb.reader` / `pcb.presentation`; user scripts | round 9, after the harness imports `pcb.*` |
| `sync_datasheets_<p>` module re-exports (×4: digikey, mouser, lcsc, element14; re-exports every name the module DEFINED at the round-5 tip (`tools/tests/sync_datasheets_<p>_names_round5.json`), e.g. `extract_parts`/`load_mpn_list` one-argument wrappers, `sync_one_part`, `get_oauth_token`; names it merely imported from its fetch module, e.g. `download_pdf`, `try_alternative_sources`, `verify_datasheet`, the provider's search/accessor names, are not re-bound, no known consumer; `sync_datasheets(**kwargs)` delegates to `distributor_core.sync`) | `skills/<p>/scripts/sync_datasheets_<p>.py` | harness runs them as scripts only (`run/run_datasheets.py`, `tools/detect_changes.py`); user scripts. Re-exported names are bindings, not patch seams: patching `sync_datasheets_digikey.get_oauth_token` no longer reaches the driver | round 9 |
| `fetch_datasheet_<p>` module re-exports (×4; the moved helpers from `distributor_core.*` and `provider_<p>`; LCSC and element14 re-export the provider's no-redirect `normalize_url`/`download_pdf` wrappers) | `skills/<p>/scripts/fetch_datasheet_<p>.py` | lcsc: harness `tests/test_kh405_lcsc_wmsc_fallthrough.py` (4 names: `search_lcsc_direct`, `enrich_with_wmsc`, `_get_datasheet_url`, `_get_manufacturer`; its `mock.patch.object(fdl, "search_lcsc_direct")` sites migrate to `provider_lcsc`, where `enrich_with_wmsc` looks the name up); docs `skills/lcsc/SKILL.md` (points at `provider_lcsc.search_lcsc_direct()` since round 6); the other three: user scripts | round 9, after the harness imports `provider_lcsc` |
| `datasheet_lookup` (whole module, 9 re-exports of `datasheet_types.cache_reader`; keeps its `_TYPES_PARENT` sys.path insert) | `skills/datasheets/scripts/datasheet_lookup.py` | harness: 9 test files bind its names (`test_b5d_detector_fire_shapes.py`, `test_detect_changes.py`, `datasheets/test_a3_lookup_path.py`, `test_a3_compat_path.py`, `test_a7_known_divergences.py`, `test_a3_trust_gates_deny.py`, `contract/test_datasheet_cache_roundtrip.py`, `contract/test_datasheet_lookup.py`, `contract/test_datasheet_features.py`); its one `monkeypatch.setattr(datasheet_lookup, "_UNSAFE_CHAR", ...)` site migrates to `datasheet_types.cache_reader`; scripts-dir importers | round 9, after the harness imports `datasheet_types` |
| `finding_schema.normalize_severity`, `finding_schema._SEVERITY_NORMALIZE` (import bindings of `kicad_core.render.normalize_severity` / `SEVERITY_ALIASES`) | `skills/kicad/scripts/finding_schema.py` | `normalize_severity`: harness `tests/contract/test_action_format_report_v14.py` (one import, 16 assertions) and the harness `tools/api_migration.py` inventory; in this repo `action/format-report.py`, `diff_engine.py`, `fab_release_gate.py`. `_SEVERITY_NORMALIZE`: no importer in the harness or in this repo; only the identity check in `tools/tests/test_render.py` | round 9, after each consumer imports `kicad_core.render` |
| `analyze_schematic._classify_ic_function` (alias of `schematic.ic_analysis.classify_ic_pinout_role`) | `skills/kicad/scripts/analyze_schematic.py` | no harness import (the name appears only in a `regression/bugfix_registry.json` summary string); `skills/datasheets/references/extraction-schema.md` no longer names it; user scripts | round 9, after the consumer imports `schematic.ic_analysis.classify_ic_pinout_role` |
| `output_filters._severity_bucket` (import alias of `kicad_core.render.severity_bucket`) | `skills/kicad/scripts/output_filters.py` | the module's own call sites; no harness import | round 9 |

`_core_path` anchors on `Path(__file__).resolve()`, so a symlinked skill directory resolves to its real parent before walking up to `skills/`; the previous ad hoc inserts used `os.path.abspath` (no symlink following). Byte-identical copies live in emc, spice, bom and the four distributor skills (digikey, mouser, lcsc, element14) by design; the distributor skills use it to reach `skills/datasheets/distributor_core/`, which sits in the core.

## Module ownership — `skills/kicad/scripts/` top level

One row per module outside the packages. "Imports" lists only in-repo modules, as a direction; "lazy" means a function-level import.

| Module | Owns | Imports |
|---|---|---|
| `analyze_schematic.py` | schematic CLI (`main(argv=None) -> int`) and the facade re-exports of `schematic.*` | `schematic`, `kicad_core`, `output_filters`, `output_io`, `project_config`, `envelopes`, `schema_codec`, `inputs_builder`, `capability_mode` |
| `analyze_pcb.py` | PCB CLI and the facade re-exports of `pcb.*` | `pcb`, `kicad_core`, `output_filters`, `output_io`, `project_config`, `envelopes`, `schema_codec`, `inputs_builder`, `capability_mode` |
| `analyze_gerbers.py` | Gerber/Excellon reader, GR-001..005, CLI | `kicad_core`, `finding_schema` (lazy), `output_filters` (lazy), `output_io` (lazy), `envelopes`, `schema_codec`, `inputs_builder`, `capability_mode` |
| `analyze_thermal.py` | thermal estimator (TS-001..005, TP-001..002, TH-DET), CLI | `kicad_core`, `finding_schema` (lazy), `lookup_detectors`, `analysis_cache` (lazy), `output_filters` (lazy), `output_io` (lazy), `project_config` (lazy), `envelopes`, `schema_codec`, `inputs_builder`, `capability_mode` |
| `cross_analysis.py` | schematic + PCB cross-domain checks (CC, EG, DA, XV, NR, RP, TW, PS-002, VS-002, DP-005), `is_cross_analysis_ground_name`, CLI | `kicad_core`, `finding_schema`, `analysis_cache` (lazy), `output_filters` (lazy), `output_io` (lazy), `envelopes`, `schema_codec`, `inputs_builder`, `capability_mode` |
| `diff_analysis.py` | diff CLI and re-exports of `diff_engine` names | `diff_engine`, `finding_schema`, `kicad_core`, `analysis_cache` (lazy) |
| `diff_engine.py` | pure comparison of two analysis outputs | `detection_schema`, `finding_schema` |
| `what_if.py` | parameter sweep and fix suggestions, CLI | `kicad_core`, `finding_schema`, `detection_schema`; lazy `spice_tolerance`, `simulate_subcircuits`, `spice_simulator` from the spice skill (the `simulate_subcircuits` import is a `no-cli-import` baseline entry) |
| `lifecycle_audit.py` | distributor lifecycle and temperature audit (LC-001..006, LT-001), CLI | `kicad_core`, `finding_schema` (lazy), `analysis_cache` (lazy) |
| `summarize_findings.py` | cross-run finding summary, CLI | `kicad_core` |
| `export_issues.py` | findings to GitHub Issues through `gh`, CLI | stdlib |
| `fab_release_gate.py` | fab-readiness pass/fail gate over analyzer JSON | `finding_schema` |
| `check_report_sections.py` | report completeness gate (required report sections from analyzer data) | `analysis_cache` (lazy) |
| `cross_verify.py` | schematic-to-PCB cross-verification script | stdlib |
| `gen_output_schema_md.py` | regenerates `references/output-schema.md` from the envelope dataclasses (dev tool) | `envelopes`, `emc_envelope` (by path) |
| `analysis_cache.py` | `analysis/` folder convention: manifest, runs, SHA-256 staleness, retention | `diff_engine` (lazy) |
| `output_io.py` | `write_primary_run` / `write_derived_output`, the analysis-cache write paths of the kicad CLIs | `analysis_cache` |
| `project_config.py` | `.kicad-happy.json` loading, suppression matching, design intent, power-rail config | `kicad_core` |
| `output_filters.py` | stage/audience filtering, audience summary, text report | `kicad_core` |
| `finding_schema.py` | `make_finding`, `Det`, trust summary, `sort_findings`, `assign_finding_ids`, consumer helpers | `kicad_core` |
| `detection_schema.py` | detection-type schemas: derived fields, inverse solvers, primary metrics | stdlib |
| `analyzer_envelope.py` | shared envelope dataclasses (Finding, Assessment, TrustSummary, InputsBlock, CompatBlock, ...) | stdlib |
| `schema_codec.py` | dataclass to JSON Schema Draft 2020-12, `emit_schema` | stdlib |
| `envelopes/` | per-analyzer envelope dataclasses (schematic, pcb, gerber, thermal, cross_analysis) | `analyzer_envelope` |
| `inputs_builder.py` | the `inputs` and `compat` envelope blocks | `run_id` |
| `run_id.py` | sortable run IDs | stdlib |
| `capability_mode.py` | run-level `capability_mode.json` writer and the per-envelope reference | `run_id` |
| `kicad_types.py` | `AnalysisContext`, `build_analysis_context` | `kicad_core`, `netlist_queries` (lazy) |
| `netlist_queries.py` | `NetlistQueries` multi-hop net tracing | `kicad_types` (type-checking only) |
| `detector_helpers.py` | helpers shared by the detector modules | `kicad_types` |
| `signal_detectors.py` | core signal-path detectors; the regulator detector is `_screen_regulator_candidate` then `_build_regulator_record` per IC, followed by `_cross_reference_feedback_dividers`, `_attach_regulator_capacitors` and `_estimate_regulator_dissipation` | `kicad_core`, `kicad_types`, `detector_helpers`, `finding_schema`, `lookup_helpers` |
| `domain_detectors.py` | domain-specific detectors (interfaces, power path, sensors, audio, LEDs, ...) | `signal_detectors`, `kicad_core`, `kicad_types`, `detector_helpers`, `finding_schema` |
| `validation_detectors.py` | validation detectors (PU, VM, PR, PS-001, LR, FS) | `kicad_core`, `kicad_types`, `detector_helpers`, `finding_schema`, `lookup_helpers`, `datasheet_features` |
| `lookup_detectors.py` | datasheet-backed detectors over `lookup()` | `finding_schema`, `lookup_helpers` |
| `lookup_helpers.py` | detector-side `lookup()` glue; `read_design_context` facade | `datasheet_types` |
| `kicad_utils.py` | facade re-exporting `kicad_core.*` | `kicad_core` |
| `sexp_parser.py` | facade for `kicad_core.sexp` | `kicad_core` |
| `bus_resolver.py` | facade for `schematic.connectivity` | `schematic` |
| `pcb_connectivity.py` | facade for `pcb.connectivity` | `pcb` |

The twelve analyzer and consumer CLIs (`analyze_schematic`, `analyze_pcb`, `analyze_gerbers`, `analyze_thermal`, `cross_analysis`, `diff_analysis`, `what_if`, `lifecycle_audit`, `summarize_findings`, and outside this directory `analyze_emc`, `simulate_subcircuits`, `extract_parasitics`) define `main(argv=None) -> int` and take their shared flag declarations from `kicad_core/cli.py`. Eleven of them exit with `sys.exit(main())`. `lifecycle_audit.py` is the one seam: its `__main__` block calls `main()` bare, because the traceback printed on missing input quotes that line and that text is frozen. Its exit codes still come from `main`, which calls `sys.exit(1)` on its error paths.

### `skills/emc/scripts/` (optional skill; imports the core only, through `_core_path`)

| Module | Owns | Imports |
|---|---|---|
| `analyze_emc.py` | EMC CLI, risk scoring, test plan | `emc_rules`, `emc_formulas`, `emc_spice`, `emc_envelope`; core `kicad_core`, `finding_schema`, `output_filters`, `analysis_cache`, `project_config`, `inputs_builder`, `capability_mode`, `schema_codec` |
| `emc_rules.py` | the EMC rule checks (findings have `make_finding`'s key shape), `is_emc_ground_name` | `emc_formulas`, `emc_spice` (lazy); core `kicad_core`, `finding_schema`, `datasheet_features` (optional: a module-level `try` import with a stub fallback) |
| `emc_formulas.py` | radiation, harmonics, cavity resonance, PDN impedance formulas | core `kicad_core` |
| `emc_spice.py` | SPICE-enhanced PDN and filter analysis | `emc_formulas`; `spice_simulator`, `spice_templates` from the spice skill (`optional-to-optional` baseline entries) |
| `emc_envelope.py` | EMC envelope dataclass | core `analyzer_envelope` |

### `skills/spice/scripts/` (optional skill; imports the core only, through `_core_path`)

| Module | Owns | Imports |
|---|---|---|
| `simulate_subcircuits.py` | simulation orchestrator CLI | spice modules; core `kicad_core`, `analysis_cache` (lazy), `output_filters` (lazy) |
| `extract_parasitics.py` | PCB parasitic R/L/C extraction CLI | core `kicad_core` |
| `spice_templates.py`, `spice_models.py`, `spice_model_generator.py`, `spice_model_cache.py`, `spice_part_library.py`, `spice_spec_fetcher.py` | testbenches, behavioral models, the project model cache, the part spec table and spec fetching | spice modules only |
| `spice_simulator.py`, `spice_results.py` | simulator backends; result parsing | spice modules; `spice_results` lazily imports core `finding_schema` |
| `spice_tolerance.py` | Monte Carlo tolerance analysis | core `kicad_core`, `detection_schema` |

### `skills/bom/scripts/` (optional skill; imports the core only, through `_core_path`)

| Module | Owns | Imports |
|---|---|---|
| `bom_manager.py` | BOM analysis and export CLI | `kicad_sexp`; core `kicad_core`, `project_config` (lazy) |
| `edit_properties.py`, `kicad_sexp.py` | symbol property edits; the skill's own S-expression helpers | bom modules only |
| `sync_datasheet_urls.py` | writes datasheet URLs from `datasheets/manifest.json` back into symbol properties | `edit_properties`, `kicad_sexp` |
| `translate_bom_pnp.py` | BOM/CPL translation into JLCPCB upload format | stdlib |

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
| `model.py` | typed records: Component/Pin/NetPin/NetLabel/Net TypedDicts, PinNetEntry, SheetData, ResolvedConfig, PcbReaderState | stdlib |
| `netquery.py` | net helpers (`get_two_pin_nets`, `build_net_id_map`), `build_pin_to_net_map`, `build_ref_pins`, `BridgeFact`/`BridgeFacts`/`build_bridge_facts` | `model`, `values` |
| `render.py` | severity normaliser and text fragments: `normalize_severity` + `SEVERITY_ALIASES`; `severity_bucket` (the text-report bucket, kept as a named adapter: it differs on `WARN` and accepts `ERROR`); `plural`, `finding_line`, `wrap_lines`, `fmt_signed`, `fmt_g4` | stdlib |
| `diagnostics.py` | `Diagnostic` and `record(sink, source, exc, effect)`: a guarded failure that degraded a run is printed to stderr and appended to the envelope's `diagnostics` list | stdlib |
| `cli.py` | shared argparse declarations: `STAGES`, `AUDIENCES`, `add_stage_audience_args`, `add_only_deterministic_arg`, `add_schema_arg`, `add_output_arg`, `add_compact_arg`, `add_text_arg`, `add_config_arg` | stdlib |

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
| `pipeline.py` | the named phases (topologies → reconcile → domain detectors → signal assembly; project: read → context → analyses → assemble; `finalize_for_cli`) | everything above, the detector modules, `kicad_types`, `finding_schema`, `lifecycle_audit` (lazy; a `no-cli-import` baseline entry), `datasheet_verify`, `output_filters`, `project_config` |
| `presentation.py` | result-dict assembly in the historical key order; legacy result | `kicad_core`, `bom_stats`, `connectivity`, `finding_schema`, `detection_schema` |

Mutation contract (D4): `reconcile_detections` rewrites phase-1 records in place; `assemble_signal_results` enriches capacitor entries in place; `assemble_result` adds `category`/`parsed_value`/`pin_nets` to components and pops `_unit_pins`; `finalize_for_cli` mutates the result (findings filtering, summary recompute). Nothing else mutates caller-owned lists.

## `skills/kicad/scripts/pcb/` ownership (round 5)

| Module | Owns | Imports |
|---|---|---|
| `geometry.py` | polygon area/containment, `ZoneFills`, `CopperPresence`, `copper_connected`, pad outlines/sampling, `_point_in_pad` | `kicad_core` |
| `connectivity.py` | union-find copper connectivity graph (`build_connectivity_graph`) | stdlib |
| `reader.py` | `.kicad_pcb` extraction (layers, setup, nets, footprints, tracks, vias, zones, outline, silkscreen, metadata, dimensions, groups, net classes); `_build_net_mapping` → `PcbReaderState` | `kicad_core`, `geometry` |
| `routing.py` | connectivity, power-net routing, routed distances, return path, net lengths/impedance, ground domains, trace proximity, current capacity, layer transitions | `kicad_core`, `geometry` |
| `copper.py` | via analysis, thermal vias, thermal-pad vias, copper presence, via-in-pad, board-edge via clearance | `kicad_core`, `geometry`, `dfm` |
| `assembly.py` | decoupling placement, placement/courtyards, tombstoning, switching loops, fiducials, test points, orientation, silkscreen overlaps, keepouts | `kicad_core`, `geometry` |
| `dfm.py` | the fab tables (`JLCPCB_LIMITS_STANDARD`, `JLCPCB_LIMITS_ADVANCED`, `IPC_CLASS_LIMITS`); drill measurement (`MIN_REAL_DRILL_MM`, `_pad_drills`, `_degenerate_drills`); `_build_net_class_lookup(net_classes)` returning the net-to-class dict; the `_measure_*` scans (track widths, track spacing, drills, `_measure_annular_rings(all_vias)`, board size) and the `_emit_*` builders over their results, incl. `_emit_ipc_class_violations(m_rings, m_drills, ipc_class, ipc_limits)`; `_dfm_tier`; `analyze_dfm` composes them; project design-rule compliance | stdlib |
| `presentation.py` | `group_components`, `compute_statistics`, `assemble_result` (result dict in the historical key order; the opt-in trace-proximity scan, switching-loop areas, design-rule compliance and, in `--full`, `build_connectivity_graph` still run here) | `kicad_core`, `connectivity`, `routing`, `dfm`, `assembly`, `finding_schema` |
| `pipeline.py` | `read_board` → `run_facts` → `run_checks` (`run_analyses` composes the two into `PcbAnalyses`) → `presentation.assemble_result`; the phase records `BoardData`, `PcbFacts`, `PcbChecks`, `PcbAnalyses`; `resolve_power_rails`; `finalize_for_cli`; `_copper_order_from_stackup` is imported here | `reader` (module attribute: harness patch target), `geometry`, `routing`, `copper`, `assembly`, `dfm`, `presentation`, `kicad_core`, `finding_schema`, `output_filters`, `project_config` |

`PcbFacts` holds the board facts (connectivity, statistics, versions, component groups, net lengths, power routing, pad distances, ground domains, current capacity, layer transitions, silkscreen, metadata, dimensions, groups, net classes, project settings, the reference-layer map, return path, GP-001 samples, keepout zones). `PcbChecks` holds the checks in their historical relative order: decoupling, vias, thermal vias, placement, DFM, tombstoning, thermal-pad vias, copper presence, then the seven checks that used to run inside the result build (fiducials, test-point coverage, orientation, silkscreen overlaps, keepout violations, via-in-pad, board-edge via clearance).

Mutation contract: `read_board` backfills `net`/`net_number` on the extracted records (KiCad 10) through the per-call `PcbReaderState`. `run_facts` and `run_checks` pass the board's containers by reference and mutate neither the board nor the facts; `tools/tests/test_pcb_phase_purity.py` proves it on the fixture boards and proves that `run_analyses` equals `run_facts` followed by `run_checks`. `assemble_result` pops `unrouted` out of `connectivity` and the finding sections out of the result, and in `--full` it calls `build_connectivity_graph`, which stays there because the harness patches it as `pcb.presentation.build_connectivity_graph`. `finalize_for_cli` mutates the result (debug strip, filters, finding_id). Nothing else mutates caller-owned lists.

## `skills/datasheets/distributor_core/` and the provider adapters (round 6)

| Module | Owns | Imports |
|---|---|---|
| `distributor_core/inputs.py` | BOM / MPN-list projection (`extract_parts`, `load_mpn_list` with per-provider `id_keys`), `is_real_mpn`, `get_analyzer_output` (runs the schematic analyzer; keeps the one `no-cli-import` baseline edge) | stdlib |
| `distributor_core/manifest.py` | `manifest.json` IO (legacy `index.json` migration), filename primitives (`sanitize_filename`, `friendly_filename`) | stdlib |
| `distributor_core/download.py` | transport cascade (`requests` → `urllib` → Playwright), redirect normalisation (opt-in via `resolve_redirects`), the Microchip alternative source | stdlib + optional `requests`/`playwright` (guarded; declared in the harness compat policy) |
| `distributor_core/verify.py` | PDF text extraction and datasheet verification | stdlib (+ optional `pdftotext` binary) |
| `distributor_core/sync.py` | `sync_datasheets(provider, ...)`: the one sync driver over a provider adapter (thirteen substitution sites over the adapter's `DEFAULT_DELAY`, `preflight`, `ID_KEYS`, `SKIPPED_COUNTS_IDS`, `LABELS`, `KEY_PRIORITY`, `RENAME_PRESENT`, `authenticate`, `sync_one_part`, `FAILED_DETAIL_WITH_URL`, `report_tail`) | `inputs`, `manifest` |
| `skills/<p>/scripts/provider_<p>.py` (×4) | the adapter: auth, search, response accessors, `sync_one_part(part, output_dir, index, delay, ctx)`, adapter constants | `distributor_core` (via `_core_path`) |
| `fetch_datasheet_<p>.py`, `sync_datasheets_<p>.py` (×4 each) | argparse `main()` + facade re-exports; basenames and flags frozen | `provider_<p>`, `distributor_core` |
| `skills/datasheets/datasheet_types/cache_reader.py` | extraction-cache reader: `lookup`, `cache_path_for`, `sanitize_mpn`, staleness (`CacheContext`, `STALE_PDF_*`) | `.codec`, `.extraction` |
| `skills/datasheets/scripts/extraction_schema.py` | JSON Schema validation of extraction results: `schema_registry` (local `$ref` resolution over `skills/datasheets/schemas/`), `validate_against_schema`; shared by `merge_results.py` and `validate_extraction_result.py` | stdlib + optional `jsonschema`/`referencing` (imported when validation runs) |

`distributor_core` imports no provider; a provider imports no other provider and no CLI. The manifest contract (`manifest.json` keys and the per-part entry fields `status`, `datasheet_url`, `verification`, `references`, `source`) is read by `skills/bom/scripts/sync_datasheet_urls.py`; the product oracle `tools/distributor_offline.py` freezes it byte-for-byte for all four providers.
