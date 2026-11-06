# Architecture notes

This file records the decisions a contributor needs that the code does not state on its own: which contracts are frozen, which way imports may point, which module owns what, and which code is kept only for a named consumer. The per-package ownership tables for `kicad_core/`, `schematic/`, `pcb/` and `distributor_core/` follow the top-level module map. The facade register lists every facade kept for a named consumer; it is empty.

## Contracts: frozen and open

Frozen for the 3.x line:

- input formats (`.kicad_sch`, `.sch`, `.kicad_pcb`, Gerber/Excellon, `.kicad-happy.json`, `.kicad_dru`);
- readability of artifacts written by earlier versions: saved analysis JSON (by `diff_analysis`, `what_if`, `summarize_findings`, the Action renderer), datasheet manifests, extraction caches, `analysis/manifest.json`;
- rule IDs and emitted `detector` strings (users' suppression configs, harness identities);
- script paths, skill names, CLI flags and exit codes.

Output is not frozen, but an output change after 3.0.0 needs a declared budget before it lands: each changed class (key, finding, severity, `schema_era`) is listed with its expected magnitude, and the corpus gate checks it. Everything outside the budget must produce strict-field identical output. `finding_id`s may move only where content legitimately changes. Wholesale output key renames (`ref`→`reference`, `net`→`net_name`) are **excluded**; a key is renamed only where it is actively misleading, and each such rename is listed in the budget.

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

## v3.0.0 output changes

The 3.0.0 release changed output under five budget classes; the user-facing list is the `CHANGELOG.md` v3.0.0 "Changed" section.

- A `diagnostics` list at the root of every analyzer envelope and the SPICE report (`[]` when nothing degraded); the six `--schema` outputs gain the property.
- EMC `findings[*]` take `make_finding`'s key order and lose `title` (its text is `summary`); `finding_id` is unchanged; the same removal in `audience_summary.*.top_issues`.
- `schema_era: "v3.0"` is added on findings of the 40 detectors listed in the `CHANGELOG.md` v3.0.0 "Changed" section, RS-001 and PP-001 among them; `tools/tag_baseline.json` shrank from 89 to 56 untagged shapes.
- One severity vocabulary (`info`/`warning`/`error`) in `datasheet_verification` (findings and `summary.by_severity`), `cross_verify.py` output and `summarize_findings` (`high` becomes `error`); legacy names are accepted on input only.
- RS-001 is removed on nets whose only `power_in` pins are bootstrap-named; PP-001 is added on boards with duplicate component refs.

Behaviour changes outside the budget leave output identical at defaults: the config knobs (`retention`, `diff_threshold`, `output_dir`), EMC and SPICE runs through `output_io.write_primary_run`, and SPICE working-directory handling.

## Facade register

No facades remain as of 3.0.0: the facade modules, re-exports and aliases kept during the 3.0 refactor were removed, and `CHANGELOG.md` lists each removed import path with its new owner. Code added only so a named consumer keeps working needs a row here naming the consumer and the condition that removes it.

The `_core_path` helpers (`skills/{emc,spice,bom,digikey,mouser,lcsc,element14}/scripts/_core_path.py`) are permanent and are not facades. `_core_path` anchors on `Path(__file__).resolve()`, so a symlinked skill directory resolves to its real parent before walking up to `skills/`; the previous ad hoc inserts used `os.path.abspath` (no symlink following). Byte-identical copies live in emc, spice, bom and the four distributor skills (digikey, mouser, lcsc, element14) by design; the distributor skills use it to reach `skills/datasheets/distributor_core/`, which sits in the core.

## Module ownership — `skills/kicad/scripts/` top level

One row per module outside the packages. "Imports" lists only in-repo modules, as a direction; "lazy" means a function-level import.

| Module | Owns | Imports |
|---|---|---|
| `analyze_schematic.py` | schematic CLI (`main(argv=None) -> int`) over `schematic.*` | `schematic`, `kicad_core`, `output_filters`, `output_io`, `project_config`, `envelopes`, `schema_codec`, `inputs_builder`, `capability_mode` |
| `analyze_pcb.py` | PCB CLI over `pcb.*` | `pcb`, `kicad_core`, `output_filters`, `output_io`, `project_config`, `envelopes`, `schema_codec`, `inputs_builder`, `capability_mode` |
| `analyze_gerbers.py` | Gerber/Excellon reader, GR-001..005, CLI | `kicad_core`, `finding_schema` (lazy), `output_filters` (lazy), `output_io` (lazy), `envelopes`, `schema_codec`, `inputs_builder`, `capability_mode` |
| `analyze_thermal.py` | thermal estimator (TS-001..005, TP-001..002, TH-DET), CLI | `kicad_core`, `finding_schema` (lazy), `lookup_detectors`, `datasheet_types` from the datasheets skill, `analysis_cache` (lazy), `output_filters` (lazy), `output_io` (lazy), `project_config` (lazy), `envelopes`, `schema_codec`, `inputs_builder`, `capability_mode` |
| `cross_analysis.py` | schematic + PCB cross-domain checks (CC, EG, DA, XV, NR, RP, TW, PS-002, VS-002, DP-005), `is_cross_analysis_ground_name`, CLI | `kicad_core`, `finding_schema`, `analysis_cache` (lazy), `output_filters` (lazy), `output_io` (lazy), `envelopes`, `schema_codec`, `inputs_builder`, `capability_mode` |
| `diff_analysis.py` | diff CLI over `diff_engine` | `diff_engine`, `finding_schema`, `kicad_core`, `analysis_cache` |
| `diff_engine.py` | pure comparison of two analysis outputs | `detection_schema`, `finding_schema`, `kicad_core` |
| `what_if.py` | parameter sweep and fix suggestions, CLI | `kicad_core`, `finding_schema`, `analysis_cache`; lazy `detection_schema`, `diff_engine`, and `simulate_subcircuits`, `spice_simulator`, `spice_model_cache` from the spice skill (the `simulate_subcircuits` import is a `no-cli-import` baseline entry) |
| `lifecycle_audit.py` | lifecycle audit CLI over `lifecycle_engine` | `lifecycle_engine`, `kicad_core`, `analysis_cache`, `output_io` (lazy) |
| `lifecycle_engine.py` | distributor lifecycle and temperature audit (LC-001..006, LT-001): the four distributor queries, extraction temperature reads, `audit_component`, `audit_bom` | `kicad_core`, `finding_schema` (lazy); lazy `distributor_core`, `datasheet_extract_cache`, `datasheet_types` from the datasheets skill |
| `summarize_findings.py` | cross-run finding summary, CLI | `kicad_core`, `analysis_cache`, `finding_schema` |
| `export_issues.py` | findings to GitHub Issues through `gh`, CLI | `diff_engine`, `kicad_core` |
| `fab_release_gate.py` | fab-readiness pass/fail gate over analyzer JSON | `kicad_core` |
| `check_report_sections.py` | report completeness gate (required report sections from analyzer data) | `kicad_core`, `analysis_cache` (lazy) |
| `cross_verify.py` | schematic-to-PCB cross-verification script | `kicad_core` |
| `gen_output_schema_md.py` | regenerates `references/output-schema.md` from the envelope dataclasses (dev tool) | `envelopes`, `emc_envelope` (by path), `kicad_core` |
| `analysis_cache.py` | `analysis/` folder convention: manifest, runs, SHA-256 staleness, retention | `kicad_core`, `finding_schema`, `diff_engine` (lazy) |
| `output_io.py` | `write_primary_run` / `write_derived_output`, the analysis-cache write paths of the kicad CLIs | `analysis_cache` |
| `project_config.py` | `.kicad-happy.json` loading, suppression matching, power-rail config | `kicad_core` |
| `design_intent.py` | `resolve_design_intent`: explicit config merged with IPC class, product class and market detected from the design | stdlib |
| `risk_summary.py` | finding risk scores and `compute_top_risks` (respin, bring-up, manufacturing buckets) | `kicad_core` |
| `output_filters.py` | stage/audience filtering, audience summary, text report | `kicad_core` |
| `finding_schema.py` | `make_finding`, `Det`, trust summary, `sort_findings`, `assign_finding_ids`, consumer helpers | `kicad_core` |
| `detection_schema.py` | detection-type schemas: derived fields, inverse solvers, primary metrics | stdlib |
| `analyzer_envelope.py` | shared envelope dataclasses (Finding, Assessment, TrustSummary, InputsBlock, CompatBlock, ...) | `kicad_core.diagnostics` |
| `schema_codec.py` | dataclass to JSON Schema Draft 2020-12, `emit_schema` | stdlib |
| `envelopes/` | per-analyzer envelope dataclasses (schematic, pcb, gerber, thermal, cross_analysis) | `analyzer_envelope` |
| `inputs_builder.py` | the `inputs` and `compat` envelope blocks | `run_id` |
| `run_id.py` | sortable run IDs | stdlib |
| `capability_mode.py` | run-level `capability_mode.json` writer and the per-envelope reference | `kicad_core`, `run_id` |
| `kicad_types.py` | `AnalysisContext`, `build_analysis_context` | `kicad_core`; lazy `netlist_queries`, `schematic.net_analysis` |
| `netlist_queries.py` | `NetlistQueries` multi-hop net tracing | `kicad_types` (type-checking only) |
| `detector_helpers.py` | helpers shared by the detector modules | `kicad_core`, `kicad_types` |
| `signal_detectors.py` | core signal-path detectors; the regulator detector is `_screen_regulator_candidate` then `_build_regulator_record` per IC, followed by `_cross_reference_feedback_dividers`, `_attach_regulator_capacitors` and `_estimate_regulator_dissipation` | `kicad_core`, `kicad_types`, `detector_helpers`, `finding_schema`, `lookup_helpers` |
| `domain_detectors.py` | domain-specific detectors (interfaces, power path, sensors, audio, LEDs, ...) | `kicad_core`, `kicad_types`, `detector_helpers`, `finding_schema` |
| `validation_detectors.py` | validation detectors (PU, VM, PR, PS-001, LR, FS) | `kicad_core`, `kicad_types`, `detector_helpers`, `finding_schema`, `lookup_helpers`, `datasheet_features` |
| `lookup_detectors.py` | datasheet-backed detectors over `lookup()` | `finding_schema`, `lookup_helpers` |
| `lookup_helpers.py` | detector-side `lookup()` glue | `kicad_core`, `datasheet_types` |

The twelve analyzer and consumer CLIs (`analyze_schematic`, `analyze_pcb`, `analyze_gerbers`, `analyze_thermal`, `cross_analysis`, `diff_analysis`, `what_if`, `lifecycle_audit`, `summarize_findings`, and outside this directory `analyze_emc`, `simulate_subcircuits`, `extract_parasitics`) define `main(argv=None) -> int` and take their shared flag declarations from `kicad_core/cli.py`. All twelve exit with `sys.exit(main())`. Each calls `kicad_core.cli.utf8_stdio()` first in its `__main__` block, which re-encodes stdout and stderr as UTF-8 when they are not; it sets the encoding only, not line endings.

### `skills/emc/scripts/` (optional skill; imports the core only, through `_core_path`)

| Module | Owns | Imports |
|---|---|---|
| `analyze_emc.py` | EMC CLI, risk scoring, test plan | `emc_rules`, `emc_formulas`, `emc_spice`, `emc_envelope`; core `kicad_core`, `finding_schema`, `output_filters`, `output_io`, `analysis_cache`, `project_config`, `inputs_builder`, `capability_mode`, `schema_codec` |
| `emc_rules.py` | the EMC rule checks (findings have `make_finding`'s key shape), `is_emc_ground_name` | `emc_formulas`, `emc_spice` (lazy); core `kicad_core`, `pcb`, `finding_schema`, `datasheet_features` (optional: a module-level `try` import with a stub fallback) |
| `emc_formulas.py` | radiation, harmonics, cavity resonance, PDN impedance formulas | core `kicad_core` |
| `emc_spice.py` | SPICE-enhanced PDN and filter analysis | `emc_formulas` (lazy); core `kicad_core`; `spice_models`, `spice_simulator`, `spice_templates` from the spice skill (`optional-to-optional` baseline entries) |
| `emc_envelope.py` | EMC envelope dataclass | core `analyzer_envelope` |

### `skills/spice/scripts/` (optional skill; imports the core only, through `_core_path`)

| Module | Owns | Imports |
|---|---|---|
| `simulate_subcircuits.py` | simulation orchestrator CLI | `spice_results`, `spice_templates`, `spice_simulator` (lazy), `spice_model_cache` (lazy), `spice_tolerance` (lazy); core `kicad_core`, `analysis_cache` (lazy), `output_filters` (lazy), `output_io` (lazy) |
| `extract_parasitics.py` | PCB parasitic R/L/C extraction CLI | core `kicad_core` |
| `spice_templates.py`, `spice_models.py`, `spice_model_generator.py`, `spice_model_cache.py`, `spice_part_library.py`, `spice_spec_fetcher.py` | testbenches, behavioral models, the project model cache, the part spec table and spec fetching | spice modules; core `kicad_core` (`spice_templates`, `spice_model_cache`, `spice_spec_fetcher`); `datasheet_types` (`spice_model_cache`, `spice_spec_fetcher`); `distributor_core.manifest` (`spice_model_cache`, `spice_spec_fetcher`); `distributor_core.verify` (`spice_spec_fetcher`) |
| `spice_simulator.py`, `spice_results.py` | simulator backends; result parsing | spice modules; core `kicad_core.executables` (`spice_simulator`); `spice_results` imports core `kicad_core` and, lazily, `finding_schema` |
| `spice_tolerance.py` | Monte Carlo tolerance analysis | core `kicad_core`, `detection_schema` |

### `skills/bom/scripts/` (optional skill; imports the core only, through `_core_path`)

| Module | Owns | Imports |
|---|---|---|
| `bom_fields.py` | field-name aliases and per-symbol part-number lookups shared by the BOM scripts | core `kicad_core.fields` |
| `bom_manager.py` | BOM analysis and export CLI | `bom_fields`, `kicad_sexp`; core `kicad_core`, `project_config` (lazy), `schematic.legacy_reader` (lazy) |
| `edit_properties.py`, `kicad_sexp.py` | symbol property edits; the skill's own S-expression helpers | `edit_properties` imports `kicad_sexp`; `kicad_sexp` imports core `kicad_core` (`fileio`, `instances`, `sexp`) |
| `sync_datasheet_urls.py` | writes datasheet URLs from `datasheets/manifest.json` back into symbol properties | `bom_fields`, `edit_properties`, `kicad_sexp`; core `distributor_core.manifest` |
| `translate_bom_pnp.py` | BOM/CPL translation into JLCPCB upload format | `bom_fields` |

## `skills/kicad/scripts/kicad_core/` ownership

| Module | Owns | Imports |
|---|---|---|
| `fields.py` | property-field aliases, `pick_field`/`pick_mpn`/`get_mpn_property` | `sexp` |
| `values.py` | `parse_value`, tolerance, E-series, coordinate units | stdlib |
| `parts.py` | regulator Vref and switching-frequency tables | stdlib |
| `classify.py` | component / IC-function / connector / jumper classification | stdlib |
| `netnames.py` | rail, ground, USB-net recognition; voltage-from-name | `sexp` |
| `passives.py` | capacitor package/ESR/ESL, dielectric, derating, inductor shielding | stdlib |
| `project.py` | `.kicad_pro`/`.kicad_dru`/lib-table readers, root-schematic discovery; also hosts `load_jsonc` / `_strip_jsonc` | `sexp`, `textvars` |
| `sexp.py` | S-expression parser (parse/find/get helpers) | stdlib |
| `model.py` | typed records: Component/Pin/NetPin/NetLabel/Net TypedDicts, PinNetEntry, SheetData, ResolvedConfig, PcbReaderState | stdlib |
| `netquery.py` | net helper (`build_net_id_map`), `build_pin_to_net_map`, `build_ref_pins`, `BridgeFact`/`BridgeFacts`/`build_bridge_facts` | `model`, `values` |
| `render.py` | severity normaliser and text fragments: `normalize_severity` + `SEVERITY_ALIASES`; `severity_bucket` (the text-report bucket, kept as a named adapter: it differs on `WARN` and accepts `ERROR`); `plural`, `finding_line`, `wrap_lines`, `fmt_signed`, `fmt_g4` | stdlib |
| `diagnostics.py` | `Diagnostic` and `record(sink, source, exc, effect)`: a guarded failure that degraded a run is printed to stderr and appended to the envelope's `diagnostics` list | stdlib |
| `executables.py` | `find_executable`: absolute path of an external program (Windows: absolute `PATH` entries only, never the current directory) | stdlib |
| `cli.py` | shared argparse declarations: `STAGES`, `AUDIENCES`, `add_stage_audience_args`, `add_only_deterministic_arg`, `add_schema_arg`, `add_output_arg`, `add_compact_arg`, `add_text_arg`, `add_config_arg` | stdlib |
| `coords.py` | schematic coordinate identity in KiCad internal units: `to_iu` and the segment-distance helper used to join connection points | stdlib |
| `fileio.py` | `atomic_write_text`: atomic text writes shared by the scripts that rewrite user files | stdlib |
| `hotloop.py` | switching-regulator hot-loop area proxies shared by the PCB analyzer and EMC SW-003: `polygon_loop_area`, `triangle_loop_area` | stdlib |
| `instances.py` | which instance data KiCad 10 uses for a placed symbol on one sheet path: `resolve_instance`, `inline_instances`, variant overrides | `fields`, `sexp` |
| `pairing.py` | schematic part to PCB footprint pairing as KiCad's Update PCB pairs them: `pair_by_path` | stdlib |
| `pdn.py` | PDN branch impedances and their parallel combination (`cap_branch_z`, `parallel_impedance`), shared by the EMC and schematic PDN models | stdlib |
| `textvars.py` | KiCad text variable expansion (`${NAME}`) as KiCad 10 expands field text | `diagnostics` |
| `token_cache.py` | private per-user cache for short-lived API access tokens (`load_token`, `store_token`) | stdlib |

`kicad_core` imports stdlib and itself only (CI-enforced).

## `skills/kicad/scripts/schematic/` ownership

| Module | Owns | Imports |
|---|---|---|
| `reader.py` | `.kicad_sch` symbols, pins, wires, labels, sheets → `SheetData` | `kicad_core` |
| `legacy_reader.py` | KiCad 5 `.sch` / `.lib` reading, pin snapping | `kicad_core`, `reader` (field-key tuples) |
| `hierarchy.py` | sheet traversal (`parse_all_sheets`), `top_level_sheets` merge | `kicad_core`, `reader` |
| `connectivity.py` | `build_net_map`, bus pass (`BusGraph`, `expand_bus_name`, `match_ports`), label output filter | `kicad_core` |
| `ic_analysis.py` | IC function classification, pinouts, subcircuits | `kicad_core`, `kicad_types`, `connectivity` |
| `erc_pins.py` | ERC pin semantics as KiCad 10 applies them by default: the pin-conflict map, the driver sets, stacked pins and the default severities | `kicad_core` |
| `net_analysis.py` | net classification, power domains, bus/protocol detection, diff pairs, ERC-style checks, `analyze_design_rules` | `kicad_core`, `kicad_types`, `detector_helpers`, `erc_pins` |
| `audits.py` | annotation / label / PWR_FLAG / footprint / sourcing / DNP / symbol / coverage audits | `kicad_core`, `connectivity`, `reader` |
| `system_analyses.py` | PDN, sleep current, derating, protocol compliance, power budget/sequencing, BOM optimisation, test coverage, assembly, USB, inrush | `kicad_core`, `kicad_types`, `net_analysis`, `finding_schema`; lazy `datasheet_types`, `distributor_core` |
| `bom_stats.py` | `generate_bom`, `compute_statistics` | `kicad_core` |
| `pipeline.py` | the named phases (topologies → reconcile → domain detectors → signal assembly; project: read → context → analyses → assemble; `finalize_for_cli`) | `reader`, `legacy_reader`, `hierarchy`, `connectivity`, `ic_analysis`, `net_analysis`, `audits`, `system_analyses`, `bom_stats`, `presentation`, `kicad_core`, `kicad_types`, `finding_schema`, `signal_detectors`, `domain_detectors`, `validation_detectors`, `lookup_detectors`; lazy `design_intent`, `lifecycle_engine`, `datasheet_verify`, `datasheet_types`, `output_filters`, `project_config` |
| `presentation.py` | result-dict assembly in the historical key order; legacy result | `kicad_core`, `bom_stats`, `connectivity`, `finding_schema`, `detection_schema` |

Mutation contract: `reconcile_detections` rewrites phase-1 records in place; `assemble_signal_results` enriches capacitor entries in place; `assemble_result` adds `category`/`parsed_value`/`pin_nets` to components and pops `_unit_pins`; `finalize_for_cli` mutates the result (findings filtering, summary recompute). Nothing else mutates caller-owned lists.

## `skills/kicad/scripts/pcb/` ownership

| Module | Owns | Imports |
|---|---|---|
| `geometry.py` | polygon area/containment, `ZoneFills`, `CopperPresence`, `copper_connected`, pad outlines/sampling, `_point_in_pad` | `kicad_core` |
| `connectivity.py` | union-find copper connectivity graph (`build_connectivity_graph`) | `geometry` |
| `reader.py` | `.kicad_pcb` extraction (layers, setup, nets, footprints, tracks, vias, zones, outline, silkscreen, metadata, dimensions, groups, net classes); `_build_net_mapping` → `PcbReaderState` | `kicad_core`, `geometry` |
| `routing.py` | connectivity, power-net routing, routed distances, return path, net lengths/impedance, ground domains, trace proximity, current capacity, layer transitions | `kicad_core`, `geometry` |
| `copper.py` | via analysis, thermal vias, thermal-pad vias, copper presence, via-in-pad, board-edge via clearance | `kicad_core`, `geometry`, `dfm` |
| `assembly.py` | decoupling placement, placement/courtyards, tombstoning, switching loops, fiducials, test points, orientation, silkscreen overlaps, keepouts | `kicad_core`, `geometry` |
| `dfm.py` | the fab tables (`JLCPCB_LIMITS_STANDARD`, `JLCPCB_LIMITS_ADVANCED`, `IPC_CLASS_LIMITS`); drill measurement (`MIN_REAL_DRILL_MM`, `_pad_drills`, `_degenerate_drills`); `_build_net_class_lookup(net_classes)` returning the net-to-class dict; the `_measure_*` scans (track widths, track spacing, drills, `_measure_annular_rings(all_vias)`, board size) and the `_emit_*` builders over their results, incl. `_emit_ipc_class_violations(m_rings, m_drills, ipc_class, ipc_limits)`; `_dfm_tier`; `analyze_dfm` composes them; project design-rule compliance | `kicad_core` (`project`, `sexp`) |
| `presentation.py` | `group_components`, `compute_statistics`, `assemble_result` (result dict in the historical key order; the opt-in trace-proximity scan, switching-loop areas, design-rule compliance and, in `--full`, `build_connectivity_graph` still run here) | `kicad_core`, `connectivity`, `routing`, `dfm`, `assembly`, `finding_schema` |
| `pipeline.py` | `read_board` → `run_facts` → `run_checks` (`run_analyses` composes the two into `PcbAnalyses`) → `presentation.assemble_result`; the phase records `BoardData`, `PcbFacts`, `PcbChecks`, `PcbAnalyses`; `resolve_power_rails`; `finalize_for_cli`; `_copper_order_from_stackup` is imported here | `reader` (module attribute: harness patch target), `geometry`, `routing`, `copper`, `assembly`, `dfm`, `presentation`, `kicad_core`, `finding_schema`, `output_filters`, `design_intent` (lazy) |

`PcbFacts` holds the board facts (connectivity, statistics, versions, component groups, net lengths, power routing, pad distances, ground domains, current capacity, layer transitions, silkscreen, metadata, dimensions, groups, net classes, project settings, the reference-layer map, return path, GP-001 samples, keepout zones). `PcbChecks` holds the checks in their historical relative order: decoupling, vias, thermal vias, placement, DFM, tombstoning, thermal-pad vias, copper presence, then the seven checks that used to run inside the result build (fiducials, test-point coverage, orientation, silkscreen overlaps, keepout violations, via-in-pad, board-edge via clearance).

Mutation contract: `read_board` backfills `net`/`net_number` on the extracted records (KiCad 10) through the per-call `PcbReaderState`. `run_facts` and `run_checks` pass the board's containers by reference and mutate neither the board nor the facts; `tools/tests/test_pcb_phase_purity.py` proves it on the fixture boards and proves that `run_analyses` equals `run_facts` followed by `run_checks`, and that `assemble_result` writes nothing else (with `--proximity`, schematic data, a project that ignores DRC checks, and a failing connectivity graph). `assemble_result` writes to two facts late: it pops `unrouted` out of `connectivity` and `_ignored_drc_checks` out of `project_settings`. It also pops the finding sections out of the result, and in `--full` it calls `build_connectivity_graph`, which stays there because the harness patches it as `pcb.presentation.build_connectivity_graph`. `finalize_for_cli` mutates the result (debug strip, filters, finding_id). Nothing else mutates caller-owned lists.

## `skills/datasheets/distributor_core/` and the provider adapters

| Module | Owns | Imports |
|---|---|---|
| `distributor_core/inputs.py` | BOM / MPN-list projection (`extract_parts`, `load_mpn_list` with per-provider `id_keys`), `is_real_mpn`, `get_analyzer_output` (runs the schematic analyzer) | stdlib; lazy `schematic.pipeline` from the kicad skill, with `analyze_schematic.py` as a subprocess fallback |
| `distributor_core/manifest.py` | `manifest.json` IO (legacy `index.json` migration), filename primitives (`sanitize_filename`, `friendly_filename`) | `datasheet_types`; stdlib |
| `distributor_core/download.py` | transport cascade (`requests` → `urllib` → Playwright), redirect normalisation (opt-in via `resolve_redirects`), the Microchip alternative source | `manifest`, lazy `kicad_core.project`; stdlib + optional `requests`/`playwright` (guarded; declared in the harness compat policy) |
| `distributor_core/verify.py` | PDF text extraction and datasheet verification | stdlib (+ optional `pdftotext` binary); `kicad_core.executables` (lazy) |
| `distributor_core/sync.py` | `sync_datasheets(provider, ...)`: the one sync driver over a provider adapter (it reads twelve names from the adapter: `NAME`, `DEFAULT_DELAY`, `ID_KEYS`, `SEARCH_KEY`, `KEY_PRIORITY`, `LABELS`, `RENAME_PRESENT`, `FAILED_DETAIL_WITH_URL`, `preflight`, `authenticate`, `sync_one_part`, `report_tail`) | `inputs`, `manifest`, `download` |
| `skills/<p>/scripts/provider_<p>.py` (×4) | the adapter: auth, search, response accessors, `sync_one_part(part, output_dir, delay, ctx)`, adapter constants | `distributor_core` (via `_core_path`); `provider_digikey` also `kicad_core.token_cache` |
| `fetch_datasheet_<p>.py`, `sync_datasheets_<p>.py` (×4 each) | argparse `main()`; basenames and flags frozen | `provider_<p>`, `distributor_core`, `kicad_core.cli` |
| `skills/datasheets/datasheet_types/cache_reader.py` | extraction-cache reader: `lookup`, `cache_path_for`, `sanitize_mpn`, staleness (`CacheContext`, `STALE_PDF_*`) | `.codec`, `.extraction` |
| `skills/datasheets/scripts/extraction_schema.py` | JSON Schema validation of extraction results: `schema_registry` (local `$ref` resolution over `skills/datasheets/schemas/`), `validate_against_schema`; shared by `merge_results.py` and `validate_extraction_result.py` | stdlib + optional `jsonschema`/`referencing` (imported when validation runs) |

`distributor_core` imports no provider; a provider imports no other provider and no CLI. The manifest contract (`manifest.json` keys and the per-part entry fields `status`, `datasheet_url`, `verification`, `references`, `source`) is read by `skills/bom/scripts/sync_datasheet_urls.py`; the product oracle `tools/distributor_offline.py` freezes it byte-for-byte for all four providers.
