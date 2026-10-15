# Architecture notes (v3 arc, living document)

This file records the few decisions a contributor needs that the code does not state on its own. It is expanded in round 7 of the v3 refactor (module ownership map); until then it holds the dependency rules and the facade register.

## Dependency rules (enforced by `tools/check_refactor.py imports`)

- `kicad` and `datasheets` are the **core**; every other skill is optional.
- An optional skill may import the core. It never imports another optional skill.
- Inside `skills/kicad/scripts/`, `kicad_core/` imports stdlib and itself only.
- No module imports a CLI module (`analyze_*.py`, `cross_analysis.py`, `diff_analysis.py`, `what_if.py`, `lifecycle_audit.py`, `simulate_subcircuits.py`, `bom_manager.py`); shared code lives in a non-CLI module.
- Existing violations are listed in `tools/import_baseline.json`. The list may only shrink; CI fails on a new entry.
- Deliberate, dated exceptions live in `tools/layer_rules.json` under `exceptions`, each with a reason and a retire-by round; they are listed on every `imports` run.

## Finding emit sites (enforced by `tools/check_refactor.py tags`)

Every emit site carries literal string keywords `detector=`, `rule_id=` and `schema_era=`. An emit site is a `make_finding`/`_make_finding` call, or a caller of a dict-returning `_make_*` factory. A `_make_*` wrapper whose own inner `make_finding` call carries all three literals is itself the emit site, and its callers are not scanned. `_make_*` helpers that are not finding factories are ignored. Known legacy sites are in `tools/tag_baseline.json`; the list may only shrink. Emitted detector strings and rule IDs are public API and never change.

## Facade register

A facade is code kept only so a named consumer keeps working. Each entry names the consumer and the condition that retires it. Round 9 of the v3 arc requires this table to be empty or every row re-justified.

| Symbol | Location | Consumer | Retire when |
|---|---|---|---|
| `make_finding(design_context=...)` ignored keyword | `skills/kicad/scripts/finding_schema.py` | harness contract tests (one real call: `tests/contract/test_finding_id.py:118`; two docstring mentions) | harness migrates per round-1 relocation map |
| `AnalysisContext.design_context`, `AnalysisContext.hierarchy_context` fields | `skills/kicad/scripts/kicad_types.py` | harness fixtures (`tests/fixtures/_build_ctx.py`, 15 contract files, `tests/test_schema_drift.py`, `tools/generate_catalog.py`) | same |
| `lookup_helpers.read_design_context` | `skills/kicad/scripts/lookup_helpers.py` | harness `tests/contract/test_lookup_helpers.py` | same |
| `kicad_utils` (whole module, 72 re-exports) | `skills/kicad/scripts/kicad_utils.py` | harness (10 names: is_power_net_name, is_ground_name, MPN_FIELD_ALIASES, MPN_FIELD_ALIASES_PRIMARY, normalize_field_name, lookup_regulator_vref, classify_component); user scripts | round 9, after harness and Action import `kicad_core.*` |
| `diff_analysis` re-exports of `diff_engine` names | `skills/kicad/scripts/diff_analysis.py` | harness `tests/test_diff_analysis.py`, `tests/test_detection_schema.py` (`SIGNAL_REGISTRY`), `tests/contract/test_diff_deep_review.py` | same |
| `sexp_parser` (whole module) | `skills/kicad/scripts/sexp_parser.py` | harness `validate/verify_parser.py`, `tests/...` (1 import), references docs | round 9, after the harness imports `kicad_core.sexp` |
| `project_config.load_jsonc`, `project_config._strip_jsonc` re-exports | `skills/kicad/scripts/project_config.py` | harness `tests/test_kh368_jsonc.py`, `tests/test_kh400_jsonc_trailing_comma.py` | same |
| `_core_path` helpers | `skills/{emc,spice,bom}/scripts/_core_path.py` | the skills themselves | permanent (not a facade; listed for discoverability) |
| `AnalysisContext.__post_init__` fill-when-empty derivation | `skills/kicad/scripts/kicad_types.py` | harness: 26 direct `AnalysisContext(...)` constructions in 20 files + `tests/fixtures/_build_ctx.py` | harness builds contexts with `build_analysis_context` (round-3 relocation map) |
| `signal_detectors._get_net_components` index-less branch | `skills/kicad/scripts/signal_detectors.py` | same harness contexts (no `nq`) | same |

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
| `netquery.py` | net helpers (`get_two_pin_nets`, `build_net_id_map`); grows into the typed index in round 3 | stdlib |

`kicad_core` imports stdlib and itself only (CI-enforced).
