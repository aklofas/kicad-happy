# Architecture notes (v3 arc, living document)

This file records the few decisions a contributor needs that the code does not state on its own. It is expanded in round 7 of the v3 refactor (module ownership map); until then it holds the dependency rules and the facade register.

## Dependency rules (enforced by `tools/check_refactor.py imports`)

- `kicad` and `datasheets` are the **core**; every other skill is optional.
- An optional skill may import the core. It never imports another optional skill.
- Inside `skills/kicad/scripts/`, `kicad_core/` imports stdlib and itself only.
- No module imports a CLI module (`analyze_*.py`, `cross_analysis.py`, `diff_analysis.py`, `what_if.py`, `lifecycle_audit.py`, `simulate_subcircuits.py`, `bom_manager.py`); shared code lives in a non-CLI module.
- Existing violations are listed in `tools/import_baseline.json`. The list may only shrink; CI fails on a new entry.

## Finding emit sites (enforced by `tools/check_refactor.py tags`)

Every emit site carries literal string keywords `detector=`, `rule_id=` and `schema_era=`. An emit site is a `make_finding`/`_make_finding` call, or a caller of a dict-returning `_make_*` factory. A `_make_*` wrapper whose own inner `make_finding` call carries all three literals is itself the emit site, and its callers are not scanned. `_make_*` helpers that are not finding factories are ignored. Known legacy sites are in `tools/tag_baseline.json`; the list may only shrink. Emitted detector strings and rule IDs are public API and never change.

## Facade register

A facade is code kept only so a named consumer keeps working. Each entry names the consumer and the condition that retires it. Round 9 of the v3 arc requires this table to be empty or every row re-justified.

| Symbol | Location | Consumer | Retire when |
|---|---|---|---|
| `make_finding(design_context=...)` ignored keyword | `skills/kicad/scripts/finding_schema.py` | harness contract tests (one real call: `tests/contract/test_finding_id.py:118`; two docstring mentions) | harness migrates per round-1 relocation map |
| `AnalysisContext.design_context`, `AnalysisContext.hierarchy_context` fields | `skills/kicad/scripts/kicad_types.py` | harness fixtures (`tests/fixtures/_build_ctx.py`, 15 contract files, `tests/test_schema_drift.py`, `tools/generate_catalog.py`) | same |
| `lookup_helpers.read_design_context` | `skills/kicad/scripts/lookup_helpers.py` | harness `tests/contract/test_lookup_helpers.py` | same |
