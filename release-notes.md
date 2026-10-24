# Release notes

The story of each kicad-happy release — what changed and why it matters when upgrading. For line-level detail, see the [CHANGELOG](CHANGELOG.md).

## 🚀 v3.0.0 — The v3 refactor

The 2.x line had grown around a few very large files: the schematic analyzer alone was over nine thousand lines, a shared utility module was imported by everything, and each distributor kept its own copy of the datasheet sync loop. v3 restructures that code without changing what it reports. It was done in nine gated rounds. Eight changed no analysis output: every output field was compared against the previous candidate and found identical, on a 200-project cross-section of the regression corpus (5,829 open-source KiCad projects) for the first two rounds and on all 149,629 corpus analysis units for the other six. One round changed output on purpose, under a declared budget that the corpus gate checked class by class; the corpus was then relocked at schema era `v3.0`. The last round removed the compatibility layer that kept the old import paths alive while the corpus tooling moved to the new ones.

What a user sees is small. Every analyzer output and the SPICE report carry a `diagnostics` list: when a guarded step fails, it is recorded there and printed once on stderr instead of being swallowed. EMC findings now have the same keys in the same order as every other finding; the duplicate `title` is gone and its text is in `summary`. The datasheet-verification, cross-verify and finding-summary tools use one severity vocabulary, `error`, `warning` and `info`, and still accept the old names as input. Findings of 40 detectors carry `schema_era: "v3.0"`. RS-001 no longer fires on nets fed only by gate-driver bootstrap pins, and PP-001 keeps every power pin on boards with duplicate references. The `retention`, `diff_threshold` and `output_dir` settings in `.kicad-happy.json` are now read; they were documented before but ignored. A few error paths got better too: a missing input to `lifecycle_audit.py` or `analyze_gerbers.py` is a usage error, and a temp directory with a space in its path no longer makes SPICE skip every measurement.

What a script author does: if your Python imported `kicad_utils`, `sexp_parser`, `bus_resolver`, `pcb_connectivity`, `datasheet_lookup`, or helpers through `analyze_schematic` / `analyze_pcb`, import them from their new owner. The [CHANGELOG](CHANGELOG.md) lists every removed path with its owner. Every CLI, flag and rule ID from 2.3.2 is unchanged, and EMC's `title` is the only finding key removed; the summary keys of `summarize_findings --json` and of the datasheet-verification block now use `error`/`warning`/`info` (`high` is `error`).

Upgrading:

- GitHub Action: `uses: aklofas/kicad-happy@v3`. `@v2` stays on v2.3.2.
- Saved analysis JSON from earlier versions stays readable by `diff_analysis`, `what_if`, `summarize_findings` and the Action's report renderer.
- If your `.kicad-happy.json` sets `analysis.retention: N`, the oldest unpinned runs beyond N are deleted on the first 3.0.0 run.
- `make_finding(design_context=...)` no longer exists as a keyword. An unknown keyword lands in the finding through `**extra`, so drop the argument.
- Build an `AnalysisContext` with `kicad_types.build_analysis_context(...)`. A directly constructed context no longer derives its indexes, and `known_power_rails=set()` now means no power rails.
- Scripts that imported the removed paths follow the table in the CHANGELOG.

## 🔧 v2.3.2 — Backport

A small release from the field while the v3 refactor continues on its own branch. imrcly found that AM-001, the absolute-maximum check, had never fired on a real datasheet extraction: it looked up `VIN` where extractions store `VIN_max`. With the key convention honoured, an LM2596 on a 50 V rail against its 45 V limit is reported, as it should have been all along. The same PR makes every datasheets script read and write UTF-8, so Windows users on a cp1252 locale stop losing `°C` and `Ω` in unit strings.

EldarPolitkin audited an eight-sheet board and filed four issues, each with a repro sheet and a test, then sent the four fixes. PU-001 no longer demands a pull-up on a pin the designer has explicitly marked no-connect. PP-001 no longer reports the bootstrap pin of a gate driver as a supply pin with no DC path; the bootstrap capacitor is the intended break. RS-001 is now honest about how it recognised a rail: when the only evidence is the net's name, the finding says so and carries heuristic confidence instead of deterministic. And `cross_analysis.py` prints a usage error rather than a traceback when pointed at a directory.

Upgrading: every change removes a false positive or clarifies a message. The RS-001 change flips `confidence` from `deterministic` to `heuristic` on roughly two in five RS-001 findings corpus-wide (those on name-only rails), so trust-summary counts move; the finding ids do not.

## 🔧 v2.3.1 — Maintenance batch

A follow-up to v2.3.0 in three layers. The first is the batch itself: jlecoeur's report that `Manufacturer P/N` and `Digikey P/N` were invisible to the analyzers turned into one shared, case-insensitive alias set for the schematic analyzer, the PCB analyzer and the BOM manager, plus six small v2.3.0 follow-ups — thermal-via counting on rotated QFNs, through-hole touch pads, pad-sourced drill violations, a clearer thermal skip reason, RP-001 wording on touch nets, and bus wires on Altium-style peer sheets. A malformed `capability_mode.json` sidecar, which had been silently crashing every analyzer in one harness environment, is now warned about and bypassed.

The second layer is what the corpus gate caught before the tag. Making the MPN pick deterministic exposed boards where a generic `Part#` holding an LCSC code sat before the real `MPN` in the file, so part-number aliases are now tiered: manufacturer-specific names always win. And the new through-hole touch-pad sampling took a 10×12 touch keyboard from ten seconds to over a hundred; an exact per-fill segment grid brings it back to nine with byte-identical output.

The third layer came from a fresh-eyes soak on a real board after the gate. On its two Ø15 mm round touch pads, CP-003 was sampling the bounding box of the pad, three millimetres outside the copper, and reporting a clearance that was simply wrong; circle and oval pads now sample their real outline, and the via-in-pad list uses the same geometry. The same board showed VM-001 flagging a correct 3.3 V GPIO-to-EN connection as a domain crossing whenever a datasheet extraction existed but lacked the EN threshold, and the diff tool crashing on an EMC comparison. All three are fixed, and the soak's longer list of observations is filed in the tracker.

Upgrading: everything is additive except the MPN re-ranking, which changes which value wins on symbols that carry both a manufacturer-specific and a generic part-number field. CP-003 clearances on round or oval touch pads will move to their true values.

## 🔧 v2.3.0 — Correctness batch

Eighteen tracker defects fixed at the root, three community contributions, and one proposed fix that ground truth rejected. The headline is CP-003, the touch-pad clearance check: it measured footprint origin to zone bounding box, which is 0.0 mm for any enclosing pour, and it fired on test points because their references start with `TP`. It now measures the pad outline to the nearest filled-polygon edge and only fires on parts that actually claim to be touch pads — expect the finding count to drop by about 96% and the survivors to carry real numbers. The same corpus pass found that KiCad stores pad orientation as an absolute board angle, which the batch now honours.

Power accounting got the same treatment. The power budget was dropping any IC whose control pin happened to sort before its supply pin on a shared net, ignored regulator outputs with unconventional rail names, and counted no LEDs at all; the sleep audit zeroed rails whose regulator merely *had* an EN pin and threw away battery dividers it could not name a voltage for. Both now reason from connectivity, and thermal analysis names every regulator it could not assess instead of quietly leaving it out. On the EMC side, DC-001 only pairs a capacitor with an IC when they share a supply net, PD-001 stops modelling feedback feedforward caps as decouplers, and the 200 MHz band keeps decoupling-irrelevant anti-resonances from driving severity.

Two contributors carried real weight this release. danielboston38 sent SP-001, which catches a two-pin part wired to a single net — the one wiring mistake ERC structurally cannot see — plus fuse bridging for PP-001 and a much better power-rail name classifier; both PRs were reworked within hours of review and checked against `kicad-cli`. Alan Rosenthal added `search_lcsc.py`, the first real search CLI in the LCSC skill. And KH-395, a per-file bus-alias scoping that the tracker had filed as a KiCad-parity gap, was implemented, refuted by `kicad-cli`'s netlist on a real project, and reverted: KiCad resolves aliases across sheets, and so do we. Late in the soak, dev-nul1 reported that every datasheet sync script crashed on Windows on its second manifest save (`Path.rename` will not overwrite there) and UfukGuler34 sent the `Path.replace` fix the same week; it is in this release.

One thing to check when upgrading: the EMC PD-001 field `transient_amps` is now `transient_a`. Everything else is additive.

## 🔧 v2.2.1 — Maintenance batch

Twenty-five verified fixes, no new subsystems — nearly all of them traceable to someone who took the time to file a precise report. Curtis Galloway's two reports killed the loudest false-positive pair in PCB analysis: GP-001 no longer reads every ordinary via's antipad as a return-path hole, and schematic-declared power rails now actually reach the PCB net classifier, so `P1_VBUS`-style per-port rails stop masquerading as signals. William Leismer's report ended the "Internal Reference, Oscillator, and Comparator" false oscillator cascade; Erik Norfelt's fixed BE-001 measuring board-edge distance to a rectangle's diagonal. And danielboston38 went one further and contributed the fix themselves: no-connect markers no longer absorb pins into wires passing underneath — verified against `kicad-cli`'s netlist as ground truth, and the corpus run showed it mattered (one board had eight I2C pairs falsely shorted).

The release also closes out a quieter class of bugs: output nondeterminism. A hash-order audit fixed ~26 sites where findings could differ byte-for-byte between identical runs, and CI now runs every analyzer twice with an unpinned hash seed so the class stays dead. On the honesty front, analysis that can't run now says so instead of vanishing: cross-analysis reports a per-check `checks_run` manifest, connectivity-graph failures surface as a visible note, conditional `.kicad_dru` rules are skipped-and-counted rather than misapplied board-wide, and files newer than the tested KiCad format get a best-effort flag.

Two things to check when upgrading. **GitHub Action users with multi-project repos must now set the `schematic`/`pcb` inputs explicitly** — auto-detection fails loudly with a candidate list instead of silently picking an arbitrary project. And if you consume `DS-003`'s `bom_size`, it now counts unique BOM lines rather than components. New opt-in goodness: pass `--schematic analysis/schematic.json` (or `--power-rails`) to `analyze_pcb.py` and the PCB checks classify your declared rails correctly; the new `power_net_resolution` block shows exactly what was resolved and how.

## 🧭 v2.2 — Hierarchical bus connectivity

One theme: the schematic analyzer's view of connectivity now matches KiCad's. Bus groups (`D[0..7]`, `{SDA SCL}`, aliases) expand into member nets, bus entries and bus wires join the net graph, and hierarchical bus pins connect positionally per sheet instance — the phantom single-pin nets reported in #25 on bus-heavy hierarchical designs are gone (thanks Reid-n0rc for the clean report and repro). Where a bus connection genuinely can't be resolved, the analyzer now says so in a `bus_topology.unresolved` list instead of guessing.

Two entangled identity fixes shipped with it: same-name local labels on different sheets no longer merge into one net (bare-name collisions get KiCad-style `/<sheet>/<name>` keys, and every net carries a `display_name`), and wire union joins every overlapping wire instead of stopping at the first.

Validation went a level deeper than previous releases: alongside the full-corpus regression gate, the connectivity work was checked against `kicad-cli`'s own netlist export as ground truth on five golden boards — from an 80-net incrementer to a 1,220-net m68k homebrew computer. This is the first brick of the correctness-floor direction: where KiCad has an authoritative answer, the analyzer must agree with it.

One behavior note when upgrading: bare net-name suppression patterns now also match the tails of hierarchical net keys (both `/uuid/Name` and the new `/<sheet>/<name>` shapes). If you suppress by bare net name on a multi-sheet project, review those patterns.

Also in this release: findings no longer over-claim datasheet provenance — thermal package-table estimates and lifecycle API lookups are labeled for what they are (thanks fl4p for a model bug report, verified end-to-end); the plugin installs on Google Antigravity now that the Gemini CLI is deprecated (thanks ademuri); OSHWA certification-readiness docs (thanks Daniel Gleason); and the dangling symlink that broke GitHub Action downloads for v2 consumers is fixed (thanks orthdron for the precise diagnosis and fork test).

## 🔧 v2.1 — Correctness batch

Seventeen analyzer fixes, no new subsystems. This release is what the field asked for: three GitHub reports (#24 inner-plane connectivity, #28/#29 via-in-pad and courtyard false positives), two external review rounds of a real ESP32-S3 board, and a fork sweep that turned up three never-submitted fixes by Anya Sabo (ported with authorship preserved — thank you).

The headline classes: inner power planes no longer fragment into false islands on 4+ layer boards; via-in-pad and courtyard-overlap checks use real geometry instead of bounding boxes; USB compliance failures finally surface as findings (UC-001..UC-004) instead of hiding in an aux section; and a dozen smaller false-positive fixes across sleep current, decoupling, derating, ERC-style warnings, and lifecycle checks.

**Upgrading from v2.0.0:** expect finding churn in exactly those classes — it is overwhelmingly false positives disappearing. Four additive JSON fields (`has_pwr_flag`, `courtyard_poly`, `measurement_basis`, `capability_note`); no breaking schema changes; no skill-instruction changes.

## 🎯 v2.0 — Deep Review

First stable release since v1.3.2. It absorbs the v1.4 release-candidate line (which closes without a standalone final — see the next section for what that line introduced) and adds the Deep Review pass on top.

**The direction change.** The v1.4 RCs shipped an LLM review layer that annotated analyzer findings — confirm, suppress, escalate, with severity caps and a merge pipeline. Real-project testing showed that structure added complexity without adding correctness, and the grown skill instructions measurably degraded how well models followed them. v2.0 removes that layer and replaces it with something narrower and more defensible: **Deep Review**, a per-IC comparison of how each part is actually wired in your schematic against its datasheet. Its findings are durable (`analysis/deep_review.json`) and must pass an **evidence gate** before they count: every finding has to cite at least one design anchor that exists in the analyzer output (component, net, or pin) and at least one evidence source — a verbatim datasheet quote verified against the PDF text, or a computation script that exists on disk. Findings that fail are quarantined visibly with a reason, never silently dropped. The gate bounds what a review can *claim*; like any agent-driven pass, what it *finds* still varies run to run.

**The correctness fix worth upgrading for.** Pin positions of schematic symbols that are both mirrored and rotated were computed with the wrong transform order. The fix derives the matrix composition from KiCad's own eeschema source and is validated against a 48-case oracle fixture. Across the 5,857-repo validation corpus it corrected the pin-to-net mapping in **1,074 repos (18%)**. **Upgrade note:** if your design uses mirrored+rotated symbols, expect finding churn on upgrade — net names may change and pull-up / LED-resistor / power-pin findings may appear or disappear. The pre-v2.0 versions of those findings were computed from wrong pin-net maps.

Why a major version: a skill is removed (kidoc, since the rc.2 line), analyzer output changes on real designs (the mirror fix), and the review architecture is replaced.

**Highlights:**

| Category | What changed |
| --- | --- |
| **Deep Review** | Per-IC usage-vs-datasheet review pass with an evidence gate (`deep_review_gate.py`): schema validation → citation checks (components/nets/pins against analyzer output, quotes against PDF text, computation scripts against disk) → stable finding IDs → visible quarantine. Nets can be cited by schematic name, display name, or PCB net name. |
| **Mirrored+rotated pin transform** | Correct KiCad matrix composition; oracle-validated (48/48); corrected pin-net mapping in 1,074/5,857 corpus repos. |
| **Facts stay deterministic, gates get honest** | Datasheet feature lookups now return facts with a `quality` flag instead of silently returning nothing below a threshold; low-quality or unverifiable extractions produce visible info findings (`extraction_quality_low`, `extraction_not_verifiable`) instead of silent no-ops. |
| **Leaner skill core** | The main `kicad` skill instructions were rebuilt from the v1.3 text under a hard instruction budget — the v1.4 growth measurably hurt model compliance. |
| **Removed** | The v1.4 Layer-2 review pipeline (severity tuning, merge step, reviewer prompt) and the kidoc skill (removed in rc.2; source in git history at `v1.3.1`). |
| **Carried from the v1.4 RC line** | Schema-driven datasheet extraction with page-anchored evidence, 11 detectors with datasheet authority, provenance (`inputs`) + compatibility (`compat`) envelope blocks, opencode platform support, JLCPCB pick-and-place translator in the bom skill, rule IDs LA-004 / RS-003 / LC-007. |

Validation: full-corpus regression gate strict-clean (5,857 repos / 170,014 assertion units, zero deltas outside the budgeted mirror correction), 659-test schema contract suite, and an A/B design review of a real board against the v1.3 baseline before tagging.

See the full [CHANGELOG](CHANGELOG.md) for details.

## 🎯 v1.4 — Datasheet Extraction (RC line — closed into v2.0)

> Shipped as `v1.4.0-rc.1` and `v1.4.0-rc.2` for opt-in testing. No standalone `v1.4.0` final was released — the line closed into v2.0, which carries all of it except the Layer-2 review pipeline. This section stands as the record of what the RC line introduced.

v1.3 harmonized analyzer output. v1.4 builds the **datasheet knowledge layer** detectors consume from. Schema-driven structured extraction replaces ad-hoc PDF scraping; every value carries page-anchored evidence and a confidence label; per-detector trust gating lets analyzers downgrade or suppress findings based on source quality. A separate LLM review layer sits on top of analyzer findings — optional, additive, and provably non-destructive (strip the overlay and the byte-identical baseline returns).

~50 commits. 11 detectors gain datasheet authority (5 upgraded + 6 new). 6 production datasheet extractions across all 6 part categories. Full Layer 1 regression gate clean corpus-wide (5,857 repos: 0 disappeared / 0 downgrades / 0 fail). 462 contract tests green.

**Highlights:**

| Category | Capabilities |
| --- | --- |
| **Schema-driven extraction** | JSON Schema Draft 2020-12 with a `SpecValue` primitive (min/typ/max/unit/condition/evidence). Canonical SI units everywhere. Six part categories: regulator, diode, transistor, opamp, mcu (catalog tier), crystal. |
| **5 upgraded detectors** | Pull-up validation, LED resistor, crystal load cap, feedback stability, voltage mismatch — now consume verified datasheet facts when present, with heuristic fallback when not. |
| **6 new detectors** | Absolute-max violation, operating-range, junction temp vs TJmax, 5V-tolerance, peripheral function mismatch, missing required regulator passives. All datasheet-backed; soft-skip on cache miss. |
| **LLM review layer** | Optional overlay on top of analyzer findings. Reviewer subagent confirms / suppresses / escalates with structured annotations; merge pipeline writes `analysis/merged/` while baseline `analysis/<analyzer>.json` stays byte-identical. Active but uncalibrated — precision/recall calibration in v1.5. |
| **Trust + provenance** | Every analyzer emits structured `inputs` provenance (SHA-256 source hashes, run_id, upstream artifact chain). Every envelope declares `compat` (minimum consumer version, deprecated/experimental fields). Layer 1 findings deterministic and byte-stable across runs. |
| **Removed: kidoc** | The engineering-documentation skill (introduced in v1.2 as beta) is removed. Its scope — PDF/DOCX/ODT/HTML report generation with custom SVG rendering and LLM-authored prose — conflicted with the `kicad` skill's analysis identity. Source remains accessible in git history at the `v1.3.1` tag. See [CHANGELOG](CHANGELOG.md) for the salvage notes. |

See the full [CHANGELOG](CHANGELOG.md) for details.

## 🎯 v1.3.2 — Bug fix

- Fix `format-report.py` full-report crash on dict-shaped protocol `devices` (#22). The full report's Protocol Compliance section raised `TypeError` when schematic findings carried enriched `{ref, value, lib_id}` device entries (e.g. boards with named I2C buses); it now coerces them the same way the short report already did. Thanks to @krisztiankurucz.

## 🎯 v1.3.1 — Bug fixes + Connectivity

Patch release: `format-report.py` dict-shaped `power_rails` crash fix (#16, #20), Altium `top_level_sheets` flat multi-page support (#19), PCB connectivity rewrite (track-as-node, compound pads, `*.Cu` wildcards), pad rotation sign fix, LED-driver false-positive suppression on parser-unreadable resistor values (KH-147), Python 3.10 minimum.

## 🎯 v1.3 — Harmonized Analysis

v1.2 made findings trustworthy. v1.3 makes them uniform and traceable. **Every analyzer** — schematic, PCB, Gerber, thermal, EMC, cross-analysis, SPICE, lifecycle — now produces the same flat `findings[]` format with rich envelopes (`detector`, `rule_id`, `severity`, `confidence`, `evidence_source`, `recommendation`, `report_context`). Every finding carries its own provenance. One schema to query, filter, export, and audit.

168 commits. 22 new detectors. Trust infrastructure (confidence + evidence taxonomies, trust_summary, per-finding provenance). PCB intelligence (union-find connectivity, 6 cross-domain checks, 7 DFM/assembly checks). Stage/audience filtering. Datasheet pipeline promoted to its own skill. KiCad 10 format compatibility. Full harness regression at 2M+ assertions, 99.98% pass.

**Highlights:**

| Category | Capabilities |
| --- | --- |
| **Harmonized output** | All 8 analyzers produce `{analyzer_type, schema_version, summary, findings[], trust_summary}`. Flat finding envelope with detector/rule_id/severity/confidence/evidence_source/recommendation/report_context. `signal_analysis` wrapper removed. |
| **Trust infrastructure** | Confidence taxonomy (`deterministic`, `heuristic`, `datasheet-backed`). Evidence source taxonomy. `make_provenance()` on all 61 detectors. `trust_summary` rollup on every output. Risk scores weight heuristic findings 0.5x. |
| **22 new detectors** | 7 validation (pull-ups, voltage mismatch, protocol buses, power sequencing, LED resistor, feedback stability) + 6 domain (wireless, transformer SMPS, I2C conflicts, supercaps, PWM LEDs, headphone jacks) + 9 audit (SS-001/002 sourcing, DS-001/002/003 datasheet coverage, RS-001/002/003 rail sources, LB-001 label aliases, PP-001 power pin DC paths, LC-007 lifecycle-skip notice). LA-004 LED rail-Vf floor added under existing `audit_led_circuits` detector. |
| **PCB intelligence** | Union-find copper connectivity graph. 6 new cross-domain checks: critical net routing, return path continuity, trace width vs current, power island detection, voltage plane splits, differential pair return paths. |
| **PCB DFM/assembly** | 7 new checks: fiducial presence, test point coverage, orientation consistency, silkscreen-pad overlap, via-in-pad tenting, board-edge via clearance, keepout violations. |
| **Stage/audience filtering** | `--stage schematic\|layout\|pre_fab\|bring_up` and `--audience designer\|reviewer\|manager` flags on all analyzers. |
| **Datasheet pipeline** | Promoted to its own top-level skill. Structured per-MPN extraction cache, heuristic page selection, five-dimension quality scoring, consumer helper API with trust gates. |
| **Cross-analysis** | `cross_analysis.py` consumes schematic + PCB JSON. 6 cross-domain checks: connector current, ESD gaps, decoupling adequacy, 3-way schematic/PCB cross-validation. |
| **KiCad 10 compat** | KH-318 via type detection (blind/buried/micro now correctly classified, buried split out in KiCad 10). KH-319 `(hide yes)` boolean form handled. |
| **Schema hardening** | `schema_version: "1.4.0"` on every output. `--schema` emits Draft 2020-12 JSON Schema synced to live envelope dataclasses on all analyzers. Deterministic `findings[]` ordering. Stable `detection_id`. Top-level `inputs` + `compat` blocks for provenance and forward-compat. |
| **Tools** | `summarize_findings.py` (cross-run rollup), `export_issues.py` (GitHub Issues), `--mpn-list` batch mode on all 4 distributor sync scripts. |
| **Test corpus** | 5,829 repos, 2M+ regression assertions at 99.98% pass, 972 unit tests, schema drift regression across all 8 analyzers. |

See the full [CHANGELOG](CHANGELOG.md) for details.

## 🎯 v1.2 — Trust + Reach

v1.1 shipped the analysis engine. v1.2 makes it something you'd actually hand to a teammate. **Trust** — every finding now carries a confidence label, can be suppressed with a reason, and is cross-checked against datasheets and a 5,829-project regression corpus. When it says there's a problem, you can believe it. **Reach** — first-class Codex support, analysis caching with manifests, and CI infrastructure mean it works wherever your team works, not just on one developer's machine.

102 commits. New skill: **KiDoc** (beta) for engineering documentation. 15+ new domain detectors. Datasheet verification bridge. What-if sweep/tolerance/fix tools. Full protocol electrical parameter coverage. Cross-verification. Analysis cache. 25 bug fixes.

**Highlights:**

| Category | Capabilities |
| --- | --- |
| **Codex support** | First-class OpenAI Codex support with agent-neutral docs, skill-installer compatibility, and global installs via `~/.codex/skills/`. |
| **KiDoc (beta)** | 8 document types, 12 figure generators, PDF/DOCX/ODT/HTML output. Scaffolds with auto-updating data + narrative placeholders. |
| **Datasheet verification** | Pin voltage enforcement, required external component checks, per-IC decoupling validation against manufacturer specs. |
| **What-if tools** | Sweep tables, tolerance analysis, fix suggestions with E-series snapping, EMC impact preview, PCB parasitic awareness. |
| **Protocol checks** | I2C, SPI, UART, USB, Ethernet, HDMI, LVDS, CAN — complete electrical parameter validation. |
| **Cross-verification** | 7 schematic-to-PCB cross-checks: component matching, diff pairs, power traces, decoupling, thermal vias. |
| **Professional checks** | Fab notes, silkscreen completeness, BOM lock, connector ground distribution, certification suggestions. |
| **Test corpus** | 5,829 repos, 1.2M+ regression assertions at 100% pass, 400+ unit tests, 0 open issues. |

## 🎯 v1.1 — EMC Pre-Compliance + Analysis Toolkit

New skill: **EMC pre-compliance risk analysis** — predicts the most common causes of EMC test failures from your KiCad schematic and PCB layout. Plus four new analysis tools for tolerance, diffing, thermal, and what-if exploration.

**What's in v1.1:**

| Category                  | Capabilities                                                                                                                                                                                                                                                              |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **EMC pre-compliance**    | 44 rule checks across ground plane integrity, decoupling, I/O filtering, switching harmonics, diff pair skew, PDN impedance, ESD paths, crosstalk, board edge radiation, thermal-EMC, shielding, and magnetic leakage from switching inductors. SPICE-enhanced when ngspice is available. FCC/CISPR/automotive/military. |
| **Plugin install**        | Available as a Claude Code plugin marketplace — `/plugin marketplace add aklofas/kicad-happy`.                                                                                                                                                                            |
| **Monte Carlo tolerance** | `--monte-carlo N` runs N simulations with randomized component values within tolerance bands. Reports 3σ bounds and per-component sensitivity analysis.                                                                                                                   |
| **Design diff**           | Compares two analysis JSONs — component changes, signal parameter shifts, EMC finding deltas. GitHub Action `diff-base: true` for automatic PR comparison.                                                                                                                |
| **Thermal hotspots**      | Junction temperature estimation for LDOs, switching regulators, shunt resistors. Package Rθ_JA lookup, thermal via correction, proximity warnings.                                                                                                                        |
| **No-connect detection**  | Correctly identifies NC markers, library-defined NC pins, and KiCad `unconnected` pin types. Eliminates false floating-pin warnings across 2,253 files.                                                                                                                   |
| **Code audit**            | 22 bug fixes (trace inductance 25x overestimate, PDN target impedance, regulator voltage suffix parser, inner-layer reference planes, and more). Full AnalysisContext migration for cleaner internals.                                                                    |
| **Validation**            | 6,853 EMC analyses across 1,035 repos (zero crashes), 96 equations verified against primary sources, 404K+ regression assertions at 100% pass rate.                                                                                                                       |

## 🎯 v1.0 — First Stable Release

This is the first stable release of kicad-happy. It marks the point where every piece of the analysis pipeline — schematic parsing, PCB layout review, Gerber verification, SPICE simulation, datasheet cross-referencing, BOM sourcing, and manufacturing prep — has been built, tested against 1,035 real-world KiCad projects, and validated with 294K+ regression assertions. Zero analyzer crashes across the full corpus.

This isn't a beta or a preview. It's production-ready. If you're designing boards in KiCad, this is the version to start with.

**What's in v1.0:**

| Category                 | Capabilities                                                                                                                                                                                                         |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Schematic analysis**   | 25+ subcircuit detectors (regulators, filters, opamps, bridges, protection, buses, crystals, current sense) with mathematical verification                                                                           |
| **Voltage derating**     | Ceramic (50%), electrolytic (80%), tantalum capacitors. IC absolute max voltage. Resistor power dissipation. Commercial, military, and automotive profiles. Over-designed component detection for cost optimization. |
| **Protocol validation**  | I2C pull-up value and rise time calculation, SPI chip select counts, UART voltage domain crossing, CAN 120Ω termination                                                                                              |
| **Op-amp checks**        | Bias current path detection, capacitive output loading, high-impedance feedback warning, unused channel detection for dual/quad parts                                                                                |
| **SPICE simulation**     | Auto-generated testbenches for 17 subcircuit types, per-part behavioral models (~100 opamps), PCB parasitic injection, ngspice/LTspice/Xyce                                                                          |
| **Datasheet extraction** | Structured extraction cache with quality scoring, heuristic page selection, SPICE spec integration                                                                                                                   |
| **Lifecycle audit**      | Component EOL/NRND/obsolescence alerts from 4 distributor APIs, temperature grade auditing (commercial/industrial/automotive/military), alternative part suggestions                                                 |
| **PCB layout**           | DFM scoring, thermal via adequacy, impedance calculation, differential pair matching, proximity/crosstalk, zone stitching, tombstoning risk                                                                          |
| **BOM sourcing**         | DigiKey, Mouser, LCSC, element14 — per-supplier order file export, pricing comparison, datasheet sync (96% download success rate)                                                                                    |
| **Manufacturing**        | JLCPCB and PCBWay format export, design rule validation, rotation offset tables, basic vs extended parts classification                                                                                              |
| **GitHub Action**        | Two-tier automated PR reviews: deterministic analysis (free, no API key) + optional AI-powered review via Claude (`ANTHROPIC_API_KEY`). Datasheet download from LCSC (free) and optional DigiKey/Mouser/element14.   |
| **KiCad support**        | KiCad 5 through 10, including legacy `.sch` format. Single-sheet and multi-sheet hierarchical designs.                                                                                                               |

