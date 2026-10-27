# Changelog

All notable changes to kicad-happy are documented here.

This project follows [Semantic Versioning](https://semver.org/). Each release is validated against a [corpus of 5,800+ real-world KiCad projects](VALIDATION.md) before tagging.

---

## v3.0.1 — unreleased

### Security

- Datasheet syncs write their temporary files under random names and ignore manifest `file` entries that point outside `datasheets/`, so a planted symlink or a crafted manifest can no longer redirect writes or moves. A `datasheets/` folder that is itself a symlink is refused unless named with `--output`. A worker error in `--parallel` mode is no longer swallowed. (KH-497)
- Datasheet downloads accept only `http`/`https` URLs on public addresses, checked on every redirect, and stop at 50 MB or 120 s (`--max-download-mb`, `--download-timeout`). Private hosts need `datasheets.allow_private_hosts: true` in `~/.kicad-happy.json`. Spaces after the host are sent as `%20`; URLs with credentials, a backslash, a blank or `%` in the host or a control character are refused, since parsers disagree on their host. The browser fallback runs only for URLs that pass the same check. (KH-498)
- SPICE netlists strip line breaks and other control characters from component references, values and net names, so schematic text can no longer add simulator commands. A reference that contains a comma, such as `C8,9`, now simulates instead of failing. (KH-499)
- SPICE no longer pastes a project's cached model (`spice/models/*.sub`) into the netlist when it contains simulator control commands or includes any file; the part falls back to the next model source with one `diagnostics` record. `spice.trust_project_models: true` in `~/.kicad-happy.json` restores verbatim use. Model files are written without following symlinks and with the usual umask-based mode. A project whose `spice/` or `spice/models/` folder is a symlink caches its models in the run's workdir instead, with one `diagnostics` record; an explicit `--model-cache-dir` is used as given. (KH-500)
- The DigiKey access token is cached in a private per-user folder (`~/.cache/kicad-happy` (or `$XDG_CACHE_HOME/kicad-happy`), or `%LOCALAPPDATA%\kicad-happy`) with mode 0600 from creation, bound to the client ID, shared by the three DigiKey callers. The old `/tmp/digikey_token_cache.json` is no longer read. (KH-501)
- `analysis/` runs never copy from or write through a symlinked file; such a file is skipped with a warning, and no run reports it as written or updated. (KH-502)
- `sync_datasheet_urls.py --recursive` writes only schematics inside the root sheet's folder; sheets outside it are reported and left alone. Schematic writes from `sync_datasheet_urls.py` and `edit_properties.py` are atomic, line breaks in property values and new property names are escaped. (KH-503)
- `plan_extraction.py` and `merge_results.py` name their files with the same MPN-to-filename mapping as the extraction readers, so MPNs with `/` (such as `LM317/NOPB`) work and no MPN can write outside the cache. (KH-505)
- The Action report reads and writes UTF-8 whatever the host locale. (KH-504)

### Changed

- The pick-and-place translator (`translate_bom_pnp.py pnp`) needs `--units mm|in|mil` when a position file does not state its unit (without it the run stops with a usage error, exit 2, and writes no output); it used to read a KiCad position CSV (which has no unit marker, and which `kicad-cli pcb export pos` writes in inches by default) as millimetres. A unit in the Mid X / Mid Y header or in the cell still wins. (kf/A13-F1)
- `fab_release_gate.py` exits 1 when the verdict is FAIL (most real projects today: 289 of 300 sampled full-chain projects end in FAIL) and 2 when a path given on the command line does not exist, holds an empty JSON object or is the wrong analyzer's output; it was 0 in both cases. Scripts that run it under `set -e` must handle exit 1. (KH-563)
- Legacy (KiCad 5 `.sch`) pins now sit where KiCad connects them. Every legacy pin was flipped top-to-bottom and components whose orientation matrix starts with `-` (about one in eight) ignored their rotation, so asymmetric parts, diode/LED/electrolytic polarity and IC pins were mis-mapped; only symbols from the built-in fallback table are still snapped to a nearby wire end, and only to one no other pin, power symbol or label holds. Legacy `angle`/`mirror_x`/`mirror_y` now describe the placement (an unmirrored part read `mirror_x: true`), and `legacy_analysis_quality.pin_source_coverage` counts built-in symbols under `builtin_fallback` (they were counted as `parsed_lib`). Expect different nets and findings on most KiCad 5 projects. (KH-511)
- KiCad 5 hierarchical sheets now connect through their sheet pins (the parent wire and the child's hierarchical label were never joined, and same-name labels in different sheets were merged), and a sheet used more than once contributes each instance's components with its own reference from the symbol's `AR` record (the `L` reference when there is none). Hierarchical net names become `/<sheet timestamp>/NAME`, `sheets_parsed`/`sheet_files` list every instance, and BOM counts grow on projects that repeat a sheet. A sheet that includes itself or one of its ancestors is skipped with one `diagnostics` record (`sheet file X includes its own ancestor Y`). (KH-513)
- Nets named like a rail plus a control suffix (`VCC_EN`, `3V3_PG`, `VBUS_SENSE`, `PWR_ON`) are signals, not power rails; power-rail lists and rail-source findings shrink accordingly, and pull-up, label and LED-resistor checks now see these nets. A rail listed in the project's power rails keeps its classification. (KH-518)
- Negative rails keep their sign: net names such as `-5V`, `NEG12V` and `-3V3` (not yet under a sheet path: `/Analog/-5V` still reads +5 V) read as -5, -12 and -3.3 V in `power_rails`, `rail_voltages` and the rail-compatibility checks. Checks that scale with magnitude (sleep current, voltage derating, level shifters, IC supply domains, supervisor thresholds) use the absolute value. Abs-max and recommended-range lookups and the LED rail-floor check skip negative rails. An I2C device's negative supply is no longer taken as its logic level. (KH-519)
- A local label joins the global label or power symbol of the same name on its own sheet, as KiCad does (rails such as `GND` and `+3V3` and signals such as `nRST` were split in two); a local label on another sheet stays apart. Power symbols in files older than KiCad 8 (version before 20230221) and in KiCad 5 schematics are named from their hidden power pin, as KiCad 10 does on load: a `power:+3.3V` symbol whose pin is `+3V3` is the `+3V3` net, and a `power:VCC` symbol relabelled `+1V8` is `VCC`; `power_symbols`, `power_rails` and `rail_voltages` follow. A power symbol whose pin is visible keeps its Value. (kf/A3-F1, kf/A2-F2, kf/A2-X1)
- Net names follow KiCad's driver priority and tie-break: a net carrying a local label and a hierarchical label or sheet pin is named after the local label, and equal-rank names resolve to the shallower sheet, then the alphabetically lower name (as KiCad escapes it; sibling sheets of equal depth still resolve by sheet order); finding ids that embed a net name change with it. The hierarchical-label `unconnected_hierarchical` list no longer reports labels that a net carries (kf/A3-F7).
- Root-sheet references and KiCad 6 per-instance values and footprints are read as KiCad reads them: every symbol takes the instance whose path is its sheet's full path (root-sheet symbols kept a stale `Reference` field, often `R?` or a copied project's number), a KiCad 6 root's `symbol_instances` value and footprint replace the placed fields (whole KiCad 6 projects showed empty values or footprints, and empty-Value `PWR_FLAG`s joined unrelated rails into one net), a newer file's leftover `symbol_instances` is ignored, and a symbol with no instance for its path takes its project's first instance. A field whose text is `~` in a file older than format 20250318 is empty, so most parts in such files no longer report the datasheet `~` (kf/A4-F1, hb-N2; the instance-value half of KH-403/404).
- Net names keep KiCad's escaped form (`{slash}`) as their identity, in the schematic and on the board, as KiCad does: a label shown as `A/B`, whether written `A{slash}B` or (KiCad 6) with a plain `/`, is the net `A{slash}B`, other escapes are decoded as KiCad shows them (`A{comma}B` is `A,B`), and a power symbol's Value, a bus alias member and a bus group member are escaped the same way. A schematic net whose name carries an escape gains a decoded `display_name`; finding summaries, descriptions and recommendations, and the rail, ground and signal-name heuristics, still use the decoded name, and suppression patterns match either form. Two board nets whose names differ only by an escape (`{slash}RAS` and `/RAS`) are no longer merged into one. Legacy `.sch` labels are unchanged. (kf/A1-F1)
- Pins carry the alternate function KiCad assigns: a placed pin whose alternate (e.g. `USBDM` on an MCU pin `PA11`) is set in the schematic takes that name and electrical type in `nets`, `ic_pin_analysis` and the pin-name checks, as in KiCad's netlist; an alternate the library pin does not define is ignored. Pull-up checks can now see function names such as `I2C1_SCL` and `SPI1_MISO`, and MCU pins that only looked like regulator switch pins by their port name are no longer detected as regulators. (kf/A2-F3)
- In KiCad 7+ files a symbol's do-not-populate flag comes from its DNP attribute, as in KiCad, not from a "DNP" value: a `DNP` value on a symbol marked `(dnp no)` is populated, so it now counts in the BOM, sourcing audit and statistics. KiCad 6 files, which have no attribute, keep the value guess. A symbol with no Value property reads the value of its cached library symbol under `lib_name` when it has one. (KH-088, ruling 24)
- Component values are read the way KiCad's simulator reads them: a Greek μ or the Ω sign, SPICE `Meg`, a decimal comma (`4,7k`, `0,1uF`), digit-group spaces (`78 182`), a sign, `fF`/`fH`, and a value followed by a comma-separated field list (`0.1uF, 50V`) now parse; spaced `10 μF` values were read 10⁶ times too small. A lone comma before three digits (`1,000`) may be a decimal mark or a thousands separator, so it is left unparsed with a `diagnostics` record on resistors, capacitors and inductors instead of guessed. Expect new RC/LC/divider and decoupling detections on designs that use these notations (kf/A15-F1, A15-F2, A15-F3, A15-F4).
- Several bus labels on one bus wire now join their members onto the label KiCad picks to drive that bus (a global label first, then a label whose members include all the others', then the alphabetically first), as in KiCad's own netlist: vector labels pair by position and group labels by member name, so a `D[4..7]` label on a wire that also carries `D[0..7]` joins D4 with D0, D5 with D1 and so on. Relabelling part of a bus can short members you meant to keep apart. The `ambiguous_bus_width` note is gone. (netid N1)
- Vias inherit the board's tenting setting, as KiCad 10 reads it: a via without its own setting is tented unless the board says otherwise, and KiCad ≤ 8 boards (`viasonmask false`) now report tented vias. A KiCad 9 via `(tenting none)` now means "board default", as KiCad 10 loads it. VP-001 and the TV-001 note judge a via inside a pad by the pad's own mask opening, which exposes the via whatever its tenting: such vias stay warnings, now worded "exposed by the pad's mask opening"; only a via in a pad with no mask opening is judged by its tenting. KiCad 5 vias saved without a drill take their net class's via (or micro-via) drill instead of 0, so annular-ring and drill checks now see them. (kf/A8-F3, A9-F4, A9-F5)
- `bom_manager` accepts KiCad 5 `.sch` projects (read only), through the schematic analyzer's legacy reader: user fields, per-instance references of repeated sheets and multi-unit parts follow the same grouping as `.kicad_sch`. A KiCad 5 field whose text is `~` is shown as `~` on the BOM line, as KiCad 5 keeps it. `edit_properties.py` and `sync_datasheet_urls.py` still need a `.kicad_sch` and say so. (entry 23)
- `--variant <name>` selects a KiCad 10 design variant in `analyze_schematic` and `bom_manager`: each symbol and sheet takes the DNP, BOM and board flags and the field values that variant sets (files saved before KiCad's 20260306 format store a variant's BOM flag inverted; that is read as KiCad reads it). Power nets keep their own names. Without `--variant` the default variant is used and output is unchanged; an unknown name is a usage error (exit 2) listing the project's variants. `analyze_schematic` reports the selected name as `project_settings.variant`. (entries 23, 45)
- Cross-analysis pairs each PCB footprint with its schematic part by the footprint's schematic path, as KiCad's Update PCB does (the reference only when no path matches), so a re-annotated schematic no longer compares the wrong parts; a part whose PCB reference differs from the schematic's is reported as one XV-001 finding with `reason: reference_mismatch` instead of a missing plus an extra part. A footprint that no symbol owns although its reference is used by another symbol is reported as `reason: unlinked_footprint` rather than "in PCB but not schematic". Schematic `components[]` carry that path as `instance_path`. XV-003 (documented, never emitted until now) reports a PCB footprint that differs from the symbol's (its lowest unit's) footprint: a `warning` per part when the footprint name differs, one `info` listing the parts that differ only in the library name; a KiCad 5 `.sch` Value or Footprint of `~` (a footprint assigned outside the schematic, through CvPcb) is not compared. XV-004 reports a footprint MPN that differs from its symbol's when both are set, and `checks_run` gains an `XV-004` entry. XV-002 now also reports a value never synchronised to the PCB (the footprint name left as the value), which it used to skip, and DA-001 counts a multi-unit IC once. Symbols that share a reference but are not units of one multi-unit part are compared and counted separately. `cross_verify.py` pairs the same way and lists `reference_mismatches`. (kf/A13-F2, A13-F3, A13-F7, A13-F8; KH-426)

### Fixed

- `bom_manager` takes a multi-unit part's Value, Footprint, Datasheet, Description and other fields from its lowest unit that sets them, as KiCad's netlist does, instead of from whichever unit comes first in the file; a DNP part no longer joins a fitted part's BOM line and gets a line of its own. (kf/A13-F4)
- Power-net routing statistics include arc tracks, so `track_count`, `total_length_mm` and `min_width_mm` can change (a narrow arc lowers the minimum width). (kf/A9-F6)
- Board outlines, zone outlines and courtyards drawn as polygons with arc segments are read whole; a board outline made only of arcs no longer reads as empty. (kf/A11-F9)
- A double quote inside an unquoted word (a KiCad 5 board value such as `0.96"_OLED`) no longer swallows the rest of the board; four corpus boards regain their footprints and copper. A `#` mid-line is part of a word, a quoted `"private"` or `"hide"` is a string and not the keyword, `(hide)` with no value reads as hidden, and quoted `\x41`, octal and `\a`/`\t` escapes decode as KiCad reads them. (kf/A1-F2, kf/A1-F3, kf/A1-F4, kf/A1-F5, kf/A1-F6)
- A quoted `(` or `)` in a text or property value no longer swallows the rest of the file: the schematic and PCB parsers read it as a string. Components, tracks, zones and board outlines that followed such a value now appear in the analysis. (KH-510)
- The fab release gate reports missing gerber layers (including inner copper) and active EMC errors; it read keys no analyzer writes and passed both. (KH-563)
- Gerber completeness requires the inner copper layers the stackup implies (from X2 copper positions, drill spans or the job file), and uppercase `.GL<n>` inner copper files are found. Inner copper files without X2 attributes (`.GL<n>`, `.G<n>L`) count toward those layers without being mapped to a layer number, so only the shortfall is reported missing. A 4-layer set missing an inner layer was reported complete. (KH-564)
- GR-005 checks whether the board outline closes: round and arc-closed outlines no longer get "open outline", and open outlines with four or more draws now do. A closed outline with extra Edge.Cuts lines gets no finding. (KH-565)
- X2 pin entries in `analyze_gerbers.py --full` connectivity carry the net declared with the pin; they took whatever net was active before the pin (usually none). (KH-591)
- CC-001, EG-001, DA-001 and TW-001 read the keys the analyzers write; they emitted nothing on any real project. CC-001 and TW-001 take the current from the regulator output-capacitance estimate (heuristic). EG-001 is reported as info and ignores sheet-qualified grounds and power rails (`/USB/VBUS`, `/Power/+5V`). TW-001's width table interpolates below 0.5 A instead of requiring 0.25 mm at any current. DP-005 pairs `...DP`/`...DM` nets. (KH-566, KH-567)
- Thermal no longer costs a current-sense resistor at its full-scale current (a misread capacitor reported 2e9 W); it is listed as skipped until an operating current is known (KH-568).
- MSOP and VSSOP (one body, 200 °C/W) and TSSOP (by pin count) footprints get their own junction-to-ambient resistance instead of the SOIC/SOP value. SOIC-14, SSOP and QSOP footprints no longer take the 8-pin SOIC value from an `8` elsewhere in the name and get the generic SOP value; exposed-pad variants keep the generic value (KH-569).
- The thermal text report shows the component table and severity counts and no longer crashes on summary-only findings; `cross_verify` thermal-via checks read the same keys (KH-570).
- The Action report's Top Risks section appears: it scored only uppercase severities and never rendered with current severity names. `summarize_findings` counts and filters `datasheet-backed` findings and accepts every evidence source; the schematic severity histogram built before finalization counts `error` findings (KH-582).
- Regulator inductor and output-rail picks (and the thermal and TW-001 values computed from them), clock-buffer consumers, op-amp feedback parts, the CP-001 description, EMC ML-001 victims and test-plan protocols, datasheet decoupling lists, lifecycle sources, `what_if` trace parasitics and merged config order no longer depend on Python's hash seed. Candidates are visited in sorted name order, so the same design always gives the same pick; a connector carrying several pair types is ranked by its riskiest protocol, ties going to the alphabetically last protocol name (KH-509, KH-584, KH-607, KH-620, KH-581, KH-579, KH-421).
- De Morgan symbols carry only the placed body's pins: a part drawn with its normal body no longer also carries the alternate body's pins (each pin appeared twice, the second copy at the alternate body's position, where it could join an unrelated wire), and a part placed with the alternate body (`(convert 2)`, `(body_style 2)`, legacy `U unit 2`) gets the alternate pins. KiCad 5 hidden power pins (`VCC`, `GND` on a 74xx part) join the net of their name, as KiCad connects them; legacy pins carry `hidden: true` like KiCad 6+ pins (KH-515, KH-512).
- A KiCad 5 project's `sym-lib-table` libraries are read even when a `<project>-cache.lib` exists; a component `nick:Name` takes its pins from the project library (ahead of the cache's copy) instead of the built-in `R`/`C`/`L` table. Relative library paths start at the project directory, and entries whose path holds an unresolved variable other than `${KIPRJMOD}` are skipped. (KH-662)
- LB-001 counts one alias per drawn label name: a net that reaches the same hierarchical label through several sheet instances (`/A/SIG`, `/B/SIG`) is no longer reported as having multiple labels, and `aliases` lists each drawn name once. (KH-668)
- A global bus label (`D[0..7]` as a `global_label` on a bus) names global member nets, as KiCad does: the same member under a global bus on several sheets is now one net, and a global label or power symbol named after a member (`D3`) joins it. Each sheet's members used to stay separate, so cross-sheet buses showed many single-pin nets (NT-001) and their member nets lost their other pins. (KH-514)
- A bus entry onto a net that an earlier entry had already joined to its bus member is no longer reported as an unlabelled tap in `bus_topology.unresolved`, and now joins its member as well. (KH-670)
- Capacitor values with an explicit uppercase `F` unit or a bare exponent are read as farads: `1F`, `120F 2.3v`, `1 F` and `10e-12` were scaled as picofarads or microfarads, so supercapacitors were missed (SC-001 now sees them) and PDN and RC results used the wrong capacitance. Bare plain numbers (`100`, `0.1`) and a lowercase `f` keep the legacy picofarad / microfarad reading; E-series snapping picks the nearest value by log distance and knows 10 as the top of each decade, so 9.9 kΩ snaps to 10 kΩ rather than 8.2 kΩ and EMC anti-resonance recommendations read 1 nF where they said 820 pF. (KH-516, KH-517)
- KiCad 5 board-outline arcs (`gr_arc` with the centre in `start`, the first point in `end` and a sweep `angle`) are read the way KiCad converts them, so the outline edges, bounding box and board size no longer include the arc centre; an outline arc that sweeps far from its endpoints no longer inflates the board (a keyboard plate once measured 2312 mm wide). Boards drawn in KiCad 5 report different `board_outline` edges, board dimensions and the findings that use them. (KH-575)
- Circular and arc footprint courtyards (including KiCad 5 `fp_arc`) are real shapes: a round courtyard gets its full bounding box instead of a zero-height line, and `courtyard_poly` is reported for mixed line and arc outlines, so PM-001 placement overlaps and PM-002 edge clearances follow the shape rather than a box. A courtyard outline that draws a segment twice on one side (F.CrtYd or B.CrtYd) is malformed in KiCad (`malformed_courtyard`): it is ignored, as KiCad ignores it, with one `diagnostics` record per footprint. The same outline drawn on both sides is not malformed and counts as one shape. Boards with round or arc courtyards report different courtyard boxes and PM-001/PM-002 findings. (KH-575)
- Silkscreen reference, value and footprint-text visibility reads the `hide` flag where KiCad writes it (bare `hide` or `(hide yes)` next to the text; `(hide no)` is visible), so hidden references and values are no longer counted as visible on the silkscreen. Boards report fewer `refs_visible_on_silk`, more `hidden_refs`, and different `values_visible_on_silk`, `user_silk_texts` and `silkscreen_completeness`. A revision marking that exists only in hidden footprint text now raises the `missing_revision` entry in the silkscreen `documentation_warnings`, and with it the fab release gate's revision-marking check. (KH-576)
- Board-edge via clearance (BV-001, `--full`) measures arcs, circles, polygons and curves as well as lines and rectangles, so vias near a round or curved outline are reported. An outline arc without a mid point is skipped rather than measured as its chord. (KH-575)
- The `--full` copper connectivity graph joins copper that overlaps: a pad or via joins every track it touches (including a track that runs through it, not only the nearest track end), arc tracks are copper, tracks that overlap without sharing an end point are one conductor, and a via inside a pad joins it. Contact uses the real pad shape (circle, oval, rectangle, rounded rectangle from `roundrect_rratio`), so a long thin pad no longer reaches a track 0.7 mm away. `F&B.Cu` pads have copper on both outer layers and NPTH pads are not copper. Boards report fewer `connectivity_graph` islands and different, mostly fewer, PS-002 / RP-002 findings. (KH-574, KH-364)
- Schematic points join only at KiCad's exact coordinates (its 100 nm grid): a wire end 0.001 mm off a pin, or a label 0.03 mm off a wire, was joined and is not any more; a label still joins a wire it lies on (within 100 nm), a junction joins the wires it lies exactly on, and a power symbol joins a wire only at a wire end, as KiCad connects them. A point left unjoined within 0.01 mm of another point, or within 0.05 mm of a wire, is listed in `diagnostics` (`CoordinateNearMiss`, at most 20 per run plus one summary) instead of being joined. Almost no real project changes. (KH-560)
- Hierarchical buses map their members as KiCad does: vectors by position after reading the range ascending and up to the narrower bus, groups by member name; group members may be separated by commas and keep their markup (`I2C{SDA,SCL}`, `CTL{~{OE} WE}`); `D[3..3]` is not a bus; a junction joins buses that cross through it; sheet pins that share a bus wire with no label map through the pin KiCad picks to drive it, so `X[2..5]` beside `X[0..5]` joins its X2 to X0 instead of chaining X0, X2 and X4 into one net. (kf/A3-F2, kf/A3-N2, kf/A3-F3, kf/A3-F6)
- PWR_FLAG and other power-output symbols no longer join nets by name: only a power symbol with a power-input pin names its net, as in KiCad. Boards whose PWR_FLAGs had an empty Value were collapsed into one net; a PWR_FLAG-only symbol still marks its net `has_pwr_flag`. (KH-403, KH-404)
- A net that a power symbol names `0` (the SPICE ground symbol, now named as KiCad names it) is ground in the schematic analysis: it no longer drew a missing-ground-pin CG-AUD finding or missing CC pull-down UC-003 findings. A connector pin or label named `0` stays a signal. (kf/A3-F7)
- Library symbols whose own name ends in `_<n>_<n>` (e.g. `Connector:Raspberry_Pi_2_3`) are no longer mistaken for sub-units; their placements get their pins and connect. A placed unit that has no pins of its own no longer borrows the other units' pins (it has only the common unit-0 pins, as in KiCad), and KiCad 10 body styles beyond the De Morgan pair use their own pins. (kf/A2-F1, kf/A2-F4, kf/A2-F5)
- KiCad 10 stacked pin numbers (`[1-5]`, `[6,7,9-11]`) expand to one pin per number, and KiCad 10 jumper symbols (`jumper_pin_groups`, `duplicate_pin_numbers_are_jumpers yes`) connect their linked pins. (kf/A2-F6, kf/A3-F5)
- KiCad 5 schematics: quoted fields, sheet pins and library datasheets that contain `\"` or `\\` (a value `1.3"-128x64`, a Windows datasheet path) are read as KiCad reads them, and a wire whose header carries `width`/`style` tokens is kept. (kf/A5-F4, A5-F6)
- KiCad 5 schematics: a `sym-lib-table` without a cache resolves `nick:symbol` through the library named `nick` (not whichever table library defines the symbol last); `~` in a symbol's library id reads as a space; `$(KIPRJMOD)` library paths resolve like `${KIPRJMOD}`; the power-input pins of a `DEF … P` library symbol join by pin name even when visible. Placed symbols whose library the analyzer cannot load, and placed symbols whose cache copy differs from the copy in a `.pro` library (the cache copy is still used, as KiCad 10's rescue step keeps it), are reported in `diagnostics` instead of falling back silently. (kf/A5-F1, A5-F3, A5-F5; KH-662)
- Symbol fields that use KiCad text variables (`${MPN}`, `${REVISION}`, `${SHEETNAME}`, project `text_variables`, cross references such as `${U1:VALUE}`) are read with the variables resolved, as KiCad shows them; they were taken literally, so a value like `${MPN}` reached the BOM and the detectors as written. Pin and net functions (`${SHORT_NET_NAME(1)}`), page numbers (`${#}`) and `@{…}` arithmetic stay as written. (kf/A4-F3)
- A multi-unit part's line in `analyze_schematic`'s BOM takes each field from the lowest unit that sets it, as KiCad's netlist does (the lowest unit wins when units disagree); a blank first unit no longer leaves the part without a footprint or MPN. (kf/A4-F2)
- Symbols on a sheet marked 'exclude from BOM', 'do not populate' or 'exclude from board' (KiCad 9+) inherit those marks, through nested sheets, in the BOM, statistics and sourcing audits. A BOM line no longer mixes fitted and DNP parts. (kf/A4-F4, hb-N1)
- KiCad 10 projects with several top-level sheets are analysed as one schematic: every declared sheet is read, each with its own instance references, even when one of them has sub-sheets; a declared top-level sheet is no longer reported as a sub-sheet, and a project or directory input opens the declared root sheet (a missing declared file falls back to `<project>.kicad_sch`, as KiCad repairs it) (kf/A4-F5, A6-F7).
- KiCad 5 boards whose copper layers were renamed (`Top`/`Bottom`, `Front`/`Back`, …) are read the way KiCad maps them, by their position in the layer table, so their SMD pads, sides, tracks and zones are no longer lost; a layer's `hide` flag is no longer reported as its alias. CP-001 checks a pad against the zones on the copper side the pad is on, not its footprint's side. (kf/A8-F1)
- Tracks saved with a solder-mask opening (KiCad 9+ `(layers "F.Cu" "F.Mask")` form) keep their copper layer. Copper drawn as board graphics with a net (KiCad 8+ copper shapes) now connects pads in the `--full` graph, as in KiCad, and nets routed only by such shapes are no longer reported unrouted (RT-001). (kf/A9-F1, kf/A9-F3)
- Custom pads connect through their drawn primitives, not only their anchor, in the `--full` graph; a circle anchor has the diameter of the pad size's x and a `rect` anchor is the size box, as in KiCad. (kf/A7-F1)
- KiCad 5 zone fills are read at their real width (the fill outline grown by half its minimum thickness, as KiCad loads a fill saved before 20250210 without `(filled_areas_thickness no)`); fill areas and copper-presence checks on those boards change. (kf/A9-F2)
- NPTH pads whose copper is larger than their hole (a mounting hole with a copper ring) carry copper, as in KiCad: in the `--full` graph such a pad with a net joins the copper it touches on its first copper layer, and copper-presence checks no longer treat a bare NPTH hole (hole as large as the pad) as copper. (KH-417)
- The recursive BOM (`bom_manager --recursive`) and the datasheet-URL sync follow KiCad 6 sub-sheets (`"Sheet file"`); they were skipped. All three BOM scripts see symbols that start with `(lib_name …)`. `bom_manager` reports each sheet instance's own reference and unit (repeated sheets, KiCad 6 root `symbol_instances` incl. their value and footprint, renamed roots); it listed the first instance only. It drops symbols under a sheet excluded from the BOM and marks symbols under a DNP sheet as DNP (KiCad 9+ sheet attributes, inherited by nested sheets), reads `~` as empty in files older than 20250318, and lists each schematic file once. (kf/A13-X1, kf/A13-F6)
- Properties added to a KiCad 6 or 7 schematic (`edit_properties.py`, `sync_datasheet_urls.py`) are written with the bare `hide` those versions read; `(hide yes)` is used from format 20231120 (KiCad 8). Before, an insert made the file unloadable in KiCad 6/7. (kf/A13-F5)

---

## v3.0.0 — unreleased

**Theme: the v3 refactor — the same analyzers, CLIs and rule IDs on a restructured codebase: a stdlib-only shared core (`kicad_core/`), `schematic/` and `pcb/` packages with named pipeline phases, and one datasheet sync driver over four provider adapters. Output is unchanged except for the items under Changed. Python scripts that imported the analyzers' internals need the new import paths listed under Removed.**

### Changed

- Every analyzer envelope and the SPICE report carry a `diagnostics` list: one `{source, exception, message, effect}` record per guarded step that failed, `[]` when nothing degraded. These failures used to be swallowed silently; each one now also prints one `Warning:` line on stderr.
- EMC findings use the same key set and key order as every other analyzer's findings (`make_finding`); the duplicate `title` key is gone and its text is in `summary`. `finding_id` is unchanged. The same applies to `audience_summary.*.top_issues`.
- Findings of 40 detectors carry `schema_era: "v3.0"`: the 18 EMC categories (`emc_board_edge`, `emc_clock_routing`, `emc_crosstalk`, `emc_decoupling`, `emc_diff_pair`, `emc_emi_filter`, `emc_emission_estimate`, `emc_esd_path`, `emc_ground_plane`, `emc_inductor_leakage`, `emc_io_filtering`, `emc_pdn`, `emc_return_path`, `emc_shielding`, `emc_stackup`, `emc_switching_emc`, `emc_thermal_emc`, `emc_via_stitching`) and `analyze_usb_compliance`, `analyze_voltage_derating`, `audit_power_pin_dc_paths`, `audit_rail_sources`, `check_connector_current`, `check_critical_net_routing`, `check_cross_validation`, `check_decoupling_adequacy`, `check_diff_pair_quality`, `check_esd_coverage_gaps`, `check_plane_splits`, `check_return_path_enhanced`, `check_trace_width_power`, `check_via_stitching_density`, `detect_i2c_address_conflicts`, `detect_shorted_two_pin_components`, `format_version_gate`, `validate_can_bus`, `validate_i2c_bus`, `validate_power_sequencing`, `validate_spi_bus`, `validate_usb_bus`.
- `datasheet_verify`, `cross_verify.py` and `summarize_findings` use one severity vocabulary, `error` / `warning` / `info` (`summarize_findings` reports `high` as `error`). Legacy names (`CRITICAL`, `HIGH`, `MEDIUM`, ...) are still accepted on input.
- RS-001 no longer fires on a net whose only `power_in` pins are gate-driver bootstrap pins. (KH-454)
- PP-001 deduplicates on `(ref, pin_number, net_name)`, so a board with duplicate or unannotated references keeps every power pin. (KH-455)
- `.kicad-happy.json` `analysis.retention`, `diff_threshold` and `output_dir` are honoured; they were documented but never read. The `retention` default is 0 (keep every run), which is what every run already did. An invalid value prints a warning and falls back to the default.
- EMC and SPICE write their `analysis/` runs through the same code path as the kicad analyzers; their `--analysis-dir` stderr lines now use the same wording.
- SPICE simulations run inside their work directory and reference their files by bare name; the work directory and the simulator binaries (`NGSPICE_PATH`, `LTSPICE_PATH`, `XYCE_PATH` or a `PATH` hit) resolve to absolute paths. (KH-463)

### Added

- `skills/kicad/scripts/kicad_core/`, a stdlib-only shared core: `sexp`, `fields`, `values`, `classify`, `netnames`, `passives`, `parts`, `project`, `netquery`, `model`, `render`, `cli`, `diagnostics`. `output_io.py` sits beside it and owns the `analysis/` write paths.
- `skills/kicad/scripts/schematic/` and `skills/kicad/scripts/pcb/` packages hold the analyzers, each with named pipeline phases (`schematic.pipeline`, `pcb.pipeline`: read, run analyses, assemble the result). `analyze_schematic.py` and `analyze_pcb.py` are thin CLIs over them.
- `skills/datasheets/distributor_core/` (inputs, manifest, download, verify, and the one `sync` driver) and a `provider_<p>.py` adapter for each of DigiKey, Mouser, LCSC and element14. The eight sync and fetch CLIs keep their names and flags.
- `tools/check_refactor.py`, the refactor checker run in CI: import direction, the literal `detector`/`rule_id`/`schema_era` tag scan, an install smoke from an unrelated directory, determinism, and JSON and text output oracles.
- `ARCHITECTURE.md`: frozen contracts, dependency rules and module ownership.
- `simulate_subcircuits.py --model-cache-dir DIR` keeps cached SPICE part models under `DIR/spice/models/` instead of beside the schematic the analysis JSON names (`file` or `inputs.source_files[0]`), and `--offline` resolves part models from the project cache and the built-in lookup table only, with no distributor or datasheet queries.

### Fixed

- EMC SPICE testbenches run inside their temporary work directory with bare filenames, so a `TMPDIR` containing a space no longer silently skips every EMC SPICE measurement. (KH-472)
- `lifecycle_audit.py` gives a usage error (exit 2), not a traceback, when its input is missing, a directory or not JSON. (KH-464)
- `analyze_gerbers.py` exits 2 with a usage error on a nonexistent directory, instead of a clean report with exit 0. (KH-466)
- Monte-Carlo SPICE trials print each model fallback once instead of once per trial; a fallback seen only in a trial is now also recorded in `diagnostics`. (KH-475)
- The SPICE model cache no longer falls back to one machine-wide temp directory: by default it is `spice/models/` beside the schematic the analysis JSON names (`file` or `inputs.source_files[0]`), only an analysis that names no source file caches under its run's workdir, and the manifest is written atomically, so parallel runs can no longer read a half-written manifest or serve another project's model. (KH-477)
- `run_distributed_pdn_spice` renders its `.meas` lines (it never produced a result before) and removes its temp directory. (KH-478)
- An `analysis/manifest.json` run id or output name can no longer point a write, copy or delete outside the analysis directory; such an entry prints a warning and is ignored.
- The schematic CLI skips a recursive or empty sub-sheet with a diagnostic, and the schematic and PCB CLIs give a usage error for an empty root input and resolve a KiCad 5 `.pro` input to its sibling schematic or board.
- A wrong-typed `.kicad-happy.json` key prints a warning and uses its default, and a string `components` or `nets` suppression is read as one pattern instead of matching every component.
- A read-only current directory no longer fails a run, and `--text` output survives a stdout that cannot encode UTF-8.
- `what_if` recomputes a regulator's `estimated_vout` after a feedback-resistor change, and an impossible `--fix` target now exits 1 with one message; this is a behaviour change, it used to print a header and exit 0.
- `analyze_thermal`, `cross_analysis` and `analyze_emc` give a usage error when their schematic and PCB inputs are swapped or are not analyzer envelopes.
- `analyze_emc --severity` filters correctly; `high` used to return no findings.
- Datasheet downloads never delete an existing PDF, and an outage, a rate limit (429) or an auth failure (401/403) is stored as `error` and retried on the next sync instead of being recorded as `not_found`.
- `bom_manager` reads CSVs that start with a byte-order mark, `edit_properties` keeps backslashes in values, and `translate_bom_pnp` reads cp1252 files and refuses `.xlsx` input.
- SPICE testbenches are written as UTF-8, and simulator logs are read as UTF-8 with replacement, so a non-ASCII part value or a UTF-16 LTspice log no longer crashes a run.
- The GitHub Action report reads the keys the analyzers emit (DFM tier, board dimensions, divider and filter rows), and its `diff-base` run extracts the base revision's sub-sheets and project config instead of only the root schematic.
- `gen_output_schema_md.py --help` no longer rewrites `output-schema.md`.
- KH-454 and KH-455 (see Changed) were found while adjudicating the v2.3.2 corpus gate.
- `capability_mode.json` `schema_versions` is filled in regardless of the current directory; it was `{}` when an analyzer ran from outside the repository root.
- The `emc_formulas.trace_resistance_ohm` equation comment was re-numbered from `EQ-042`, which another formula already used, to `EQ-108`. (KH-445)
- Two refactor regressions were caught in review before any release and are listed for completeness: a non-dict `analysis` value in `.kicad-happy.json` made the schematic CLI exit 1, and PP-001 lost its last-wins handling of duplicate references.

### Removed

Python import paths only; every CLI and flag from 2.3.2 still exists (output changes are under Changed, the two new SPICE flags under Added). A script that imported one of these names imports it from the new owner. Private (`_name`) helpers moved with the public names of the same module.

| Removed | New owner |
|---|---|
| `kicad_utils`: `classify_component`, `classify_connector`, `classify_ic_function`, `classify_jumper_default_state` | `kicad_core.classify` |
| `kicad_utils`: `DIGIKEY_FIELD_ALIASES`, `MPN_FIELD_ALIASES`, `MPN_FIELD_ALIASES_GENERIC`, `MPN_FIELD_ALIASES_PRIMARY`, `get_mpn_property`, `get_property_ci`, `normalize_field_name`, `pick_field`, `pick_mpn` | `kicad_core.fields` |
| `kicad_utils`: `USB_DATA_NET_MARKERS`, `is_ground_name`, `is_power_net_name`, `is_usb_data_net_name`, `parse_voltage_from_net_name` | `kicad_core.netnames` |
| `kicad_utils`: `build_net_id_map`, `get_two_pin_nets` | `kicad_core.netquery` |
| `kicad_utils`: `lookup_regulator_vref`, `lookup_switching_freq`, `match_known_switching` | `kicad_core.parts` |
| `kicad_utils`: `classify_dielectric`, `classify_inductor_shielding`, `estimate_cap_esl`, `estimate_cap_esr`, `estimate_dc_bias_derating`, `extract_cap_package` | `kicad_core.passives` |
| `kicad_utils`: `discover_root_schematic`, `extract_pro_design_rules`, `extract_pro_net_classes`, `extract_pro_text_variables`, `find_project_settings_file`, `is_referenced_as_child`, `load_kicad_dru`, `load_kicad_pro`, `load_lib_tables`, `resolve_project_input` | `kicad_core.project` |
| `kicad_utils`: `COORD_EPSILON`, `E12_DECADE`, `E24_DECADE`, `E96_DECADE`, `format_frequency`, `parse_rated_voltage`, `parse_tolerance`, `parse_value`, `snap_to_e_series`, `snap_to_mil_grid` | `kicad_core.values` |
| `sexp_parser`: `find_all`, `find_deep`, `find_first`, `get_at`, `get_properties`, `get_property`, `get_value`, `get_xy`, `has_flag`, `parse`, `parse_file` | `kicad_core.sexp` |
| `analyze_schematic`: `build_pin_to_net_map` | `kicad_core.netquery` |
| `analyze_schematic`: `analyze_bus_topology`, `analyze_wire_geometry`, `audit_datasheet_coverage`, `audit_dnp_rate`, `audit_property_patterns`, `audit_pwr_flags`, `audit_sourcing_fields`, `audit_sourcing_gate`, `check_annotation_completeness`, `check_generic_transistor_symbols`, `check_instance_consistency`, `check_simulation_readiness`, `classify_ground_domains`, `spatial_clustering`, `summarize_alternate_pins`, `validate_footprint_filters`, `validate_hierarchical_labels`, `validate_label_shapes`, `verify_pin_coverage` | `schematic.audits` |
| `analyze_schematic`: `compute_statistics`, `generate_bom` | `schematic.bom_stats` |
| `analyze_schematic`: `BusGraph`, `build_net_map`, `expand_bus_name`, `get_net_neighbors`, `match_ports` | `schematic.connectivity` |
| `analyze_schematic`: `merge_top_level_sheets`, `parse_all_sheets` | `schematic.hierarchy` |
| `analyze_schematic`: `analyze_ic_pinouts`, `identify_subcircuits` | `schematic.ic_analysis` |
| `analyze_schematic`: `analyze_connectivity`, `analyze_design_rules` | `schematic.net_analysis` |
| `analyze_schematic`: `ANALYZER_SOURCE`, `MAX_TESTED_FORMAT_VERSION`, `analyze_legacy_schematic`, `analyze_signal_paths` | `schematic.pipeline` |
| `analyze_schematic`: `compute_pin_positions`, `detect_sub_sheet`, `extract_bus_elements`, `extract_components`, `extract_junctions`, `extract_labels`, `extract_lib_symbols`, `extract_no_connects`, `extract_power_symbols`, `extract_symbol_instances`, `extract_text_annotations`, `extract_title_block`, `extract_wires`, `parse_single_sheet` | `schematic.reader` |
| `analyze_schematic`: `SLEEP_PULL_MIN_OHM`, `analyze_assembly_complexity`, `analyze_bom_optimization`, `analyze_inrush_current`, `analyze_pdn_impedance`, `analyze_power_budget`, `analyze_power_sequencing`, `analyze_protocol_compliance`, `analyze_sleep_current`, `analyze_test_coverage`, `analyze_usb_compliance`, `analyze_voltage_derating` | `schematic.system_analyses` |
| `bus_resolver`: `BusGraph`, `expand_bus_name`, `match_ports` | `schematic.connectivity` |
| `analyze_pcb`: `parse_file` | `kicad_core.sexp` |
| `analyze_pcb`: `analyze_decoupling_placement`, `analyze_fiducials`, `analyze_keepout_violations`, `analyze_orientation_consistency`, `analyze_placement`, `analyze_silkscreen_pad_overlaps`, `analyze_test_point_coverage`, `analyze_tombstoning_risk` | `pcb.assembly` |
| `analyze_pcb`: `build_connectivity_graph` | `pcb.connectivity` |
| `analyze_pcb`: `analyze_board_edge_via_clearance`, `analyze_copper_presence`, `analyze_thermal_pad_vias`, `analyze_thermal_vias`, `analyze_via_in_pad`, `analyze_vias` | `pcb.copper` |
| `analyze_pcb`: `MIN_REAL_DRILL_MM`, `analyze_design_rule_compliance`, `analyze_dfm` | `pcb.dfm` |
| `analyze_pcb`: `CopperPresence`, `ZoneFills`, `copper_connected` | `pcb.geometry` |
| `analyze_pcb`: `ANALYZER_SOURCE`, `MAX_TESTED_FORMAT_VERSION` | `pcb.pipeline` |
| `analyze_pcb`: `compute_statistics`, `group_components` | `pcb.presentation` |
| `analyze_pcb`: `extract_board_metadata`, `extract_board_outline`, `extract_dimensions`, `extract_footprints`, `extract_groups`, `extract_layers`, `extract_net_classes`, `extract_nets`, `extract_setup`, `extract_silkscreen`, `extract_tracks`, `extract_vias`, `extract_zones` | `pcb.reader` |
| `analyze_pcb`: `analyze_connectivity`, `analyze_current_capacity`, `analyze_ground_domains`, `analyze_layer_transitions`, `analyze_net_lengths`, `analyze_pad_to_pad_distances`, `analyze_power_nets`, `analyze_return_path_continuity`, `analyze_trace_proximity` | `pcb.routing` |
| `pcb_connectivity`: `UnionFind`, `build_connectivity_graph` | `pcb.connectivity` |
| `analyze_schematic._classify_ic_function` | `schematic.ic_analysis.classify_ic_pinout_role` |
| `schematic.pipeline.parse_legacy_schematic` | `schematic.pipeline.analyze_legacy_schematic` |
| `signal_detectors.detect_led_drivers` | `signal_detectors.enrich_transistor_led_drivers` (the emitted `detector` string `detect_led_drivers` is unchanged) |
| `finding_schema.normalize_severity`, `finding_schema._SEVERITY_NORMALIZE` | `kicad_core.render.normalize_severity`, `kicad_core.render.SEVERITY_ALIASES` |
| `output_filters._severity_bucket` | `kicad_core.render.severity_bucket` |
| `project_config._strip_jsonc` | `kicad_core.project._strip_jsonc` |
| `diff_analysis`: `validate_signal_registry`, `diff_assessments`, `classify_severity` | `diff_engine` |
| `make_finding(design_context=...)` keyword | none; drop the argument |
| `AnalysisContext.design_context`, `AnalysisContext.hierarchy_context`, and the index derivation on direct construction | `kicad_types.build_analysis_context(...)` |
| `lookup_helpers.read_design_context` | none |
| `datasheet_lookup`: `lookup`, `cache_path_for`, `sanitize_mpn`, `CacheContext`, `STALE_PDF_HASH_MISMATCH`, `STALE_PDF_MISSING` | `datasheet_types.cache_reader` |
| `sync_datasheets_<p>`: `MANIFEST_FILENAME`, `LEGACY_MANIFEST_FILENAME`, `friendly_filename`, `load_index`, `save_index`, `sanitize_filename` | `distributor_core.manifest` |
| `sync_datasheets_<p>`: `extract_parts`, `load_mpn_list`, `get_analyzer_output`, `is_real_mpn` | `distributor_core.inputs` (`extract_parts` / `load_mpn_list` take `id_keys=provider_<p>.ID_KEYS`) |
| `sync_datasheets_<p>`: `ID_KEYS`, `sync_one_part`; DigiKey also `get_oauth_token`, `search_digikey_with_token` | `provider_<p>` |
| `fetch_datasheet_<p>`: `normalize_url` (DigiKey, Mouser) | `distributor_core.download` |
| `fetch_datasheet_<p>`: `normalize_url` (LCSC, element14) | `provider_<p>` |
| `build_hierarchy_context`, `enrich_from_hierarchy`, `apply_rotation`, `_pick`, `_spec_min`, `_extract_page_text`, `_extract_package`, `_pct_delta`, `DrillTool`, `check_one` | none (dead code); use `pick_field` in place of `_pick` |

### Migration

- GitHub Action: use `uses: aklofas/kicad-happy@v3`. `@v2` stays on v2.3.2.
- Analysis JSON written by earlier versions stays readable by every reader (`diff_analysis`, `what_if`, `summarize_findings`, the Action's report renderer).
- A `.kicad-happy.json` that already sets `analysis.retention: N` has its oldest unpinned runs beyond N deleted on the first 3.0.0 run, because the key is now read.
- `make_finding(design_context=...)`: the keyword is gone. `make_finding` merges unknown keywords into the finding through `**extra`, so a caller that still passes it gets a `design_context` key in its finding; drop the argument.
- `AnalysisContext`: build it with `kicad_types.build_analysis_context(...)`. A directly constructed context no longer derives its indexes, so detectors that need `nq` fail on it, and `known_power_rails=set()` now means the board has no power rails.
- Python scripts that imported the removed paths: follow the Removed table.

---

## v2.3.2 — 2026-10-22

**Theme: backport — six small analyzer fixes from two contributors, landed on the 2.x line while the v3 refactor continues on its own branch. One change is not purely additive: RS-001 drops to `heuristic` confidence on rails it recognises only by name.**

### Fixed

- AM-001 absolute-maximum checks resolve the `<domain>_max` keys that datasheet extractions actually carry (`VIN_max`, `VDD_max`, …) before falling back to the bare domain; the rule had been structurally silent on schema-conformant extractions (an LM2596 with `VIN_max` 45 V on a 50 V rail: no finding before, one after). (#51 — imrcly)
- Every text I/O site in the datasheets scripts reads and writes UTF-8, so unit strings such as `°C` and `Ω` survive a cp1252 Windows locale. No POSIX behaviour change. (#51 — imrcly)
- `cross_analysis.py` exits with an argparse usage error instead of a traceback when `--schematic` or `--pcb` names a directory or a file that is not JSON. (#52 — EldarPolitkin; KH-450)
- PU-001 no longer asks for a pull-up on a pin that carries a no-connect marker and touches nothing else. (#53 — EldarPolitkin; KH-451)
- RS-001 on a rail it recognises only by name (no `power_in` pin on the net) now says so: `confidence` and provenance drop to `heuristic`, the description reads "is named like a power rail (no power_in pin on it)", and `pins` is empty. Rails with a `power_in` pin are unchanged, and `finding_id` is stable either way. (#54 — EldarPolitkin; KH-452)
- PP-001 skips gate-driver bootstrap pins (`BST`, `BOOT`, `BOOTSTRAP`, `CBST`, with `_x` or digit suffixes); the bootstrap capacitor is the intended DC break, not a missing supply path. (#55 — EldarPolitkin; KH-453)

**Validation:** one budgeted corpus gate over the whole range (`6a91aaa` → `4701c26`: 149,629 unit pairs, zero downgrades, zero budget violations — 25,466 RS-001 confidence flips, 4,894 PU-001 and 135 PP-001 disappearances, every one attributed; cross-analysis, EMC, thermal, PCB and Gerber outputs byte-identical), a 300-project `--full` chain A/A, contract suite 707 passed, eleven new harness tests adopted from the PRs.

**Thanks:** imrcly (#51), EldarPolitkin (#52–#55 — four issues, each with a minimal repro sheet and a drop-in test, and PRs #56–#59 that fixed them).

---

## v2.3.1 — 2026-10-06

**Theme: maintenance — one field-recognition gap from the field, six v2.3.0 follow-ups, two regressions the corpus gate caught before the tag, and three defects a fresh-eyes soak found on a real board. Every change gated over the full corpus; the one output change that is not additive is the MPN re-ranking.**

### Added

- Shared part-number field aliases (`kicad_utils.MPN_FIELD_ALIASES` / `DIGIKEY_FIELD_ALIASES`): `Manufacturer P/N`, `Mfr P/N`, `Mfg P/N`, `Manufacturer Part Number`, `Manf#`, `Digikey P/N`, `Digi-Key P/N` are recognised by the schematic analyzer, the PCB analyzer and the BOM manager, case- and whitespace-insensitively. (#46 — reported by jlecoeur; KH-414)
- PCB `vias.via_analysis.degenerate_drills[]` — pad/via drills below 0.05 mm (file artefacts such as `(drill 0.00001)`) are listed here instead of becoming the board minimum. (KH-412)
- Design-rule `min_via_drill` / `.kicad_dru` `hole_size` violations gain `drill_source` (`via` | `pad`) and, for pads, `source_ref`. (KH-412)
- Thermal `skipped_components[].reason` gains `no_pdiss_estimate` for regulators whose dissipation was never estimated upstream. (KH-411)
- Part-number aliases are tiered: manufacturer-specific names (`MPN`, `Manufacturer P/N`, `Mfr Part Number`, …) always outrank generic part-number names (`Part Number`, `Part#`, `PartNo`); file order breaks ties only within a tier, and whitespace-only values never win. The BOM manager's convention-majority field is authoritative among manufacturer-specific names. (KH-418)

### Fixed

- Thermal-via-under-pad counting rotated vias by footprint + pad angle; KiCad pad angles are absolute, so rotated QFNs under-counted their vias. (KH-408)
- CP-003 touch-pad clearance measured from the footprint origin for through-hole touch pads (`*.Cu` layer wildcard was not matched). (KH-413)
- DFM-001 / design-rule drill violations whose minimum came from a footprint pad now say `pad_drill` / `drill_source: "pad"` instead of `via_drill`, and name the pad's reference in `message`/`description` (the `summary` text is unchanged, so `finding_id` stays stable). (KH-412)
- RP-001 on a capacitive-touch net no longer recommends stitching vias inside the intentional void. (KH-410)
- A malformed `capability_mode.json` in the analysis directory (anything that is not a record with a `run_id`) no longer crashes every analyzer at startup; it is warned about on stderr, left untouched, and a fresh in-memory run id is used. (KH-415)
- Altium-flat / hybrid projects: a bus-tapped member wire on a peer sheet now resolves on its own sheet; phantom pinless bus-name nets (`<name>[a..b]`) and false `unlabeled_entry_tap` markers from untagged peer buses disappear, so `statistics.total_nets` may drop. (KH-409)
- MPN pick is deterministic when a symbol carries two alias fields (file order, not hash order). (KH-414)
- A generic `Part#` holding an LCSC code no longer outranks an explicit `MPN` on the same symbol — the corpus gate caught this on El-Luhb's NVMe carriers after the file-order pick landed. (KH-418)
- CP-003 touch-pad sampling on dense boards: `ZoneFills.min_edge_distance` uses a per-fill segment grid (exact, byte-identical output). A 10×12 capacitive-touch keyboard went from 109 s to 8.5 s; v2.3.0 had been 9.8 s. (KH-420)
- CP-003 samples the real outline of circle and oval pads instead of their bounding box — on a Ø15 mm round touch pad the box corners sat 3 mm outside the copper and read an unrelated fill cutout as the clearance (0.45 mm reported, 1.00 mm true). The via-analysis `via_in_pad` list uses the pad outline and the pad's absolute rotation the same way; vias inside 90°/270°-rotated pads were previously missed. (KH-419)
- VM-001 no longer reports a 3.3 V GPIO driving a boost converter's EN pin as a "5.0 V / 3.3 V domain crossing" when a trusted datasheet extraction exists but carries no EN threshold; the regulator-EN heuristic runs whenever the datasheet cannot decide, and the finding's provenance now says `heuristic` like its confidence. (KH-424)
- `diff_analysis.py --text` no longer crashes on EMC diffs whose risk score changed (float delta formatted as an integer). (KH-425)

**Validation:** three budgeted corpus gates over the release range (170,014 units each, zero downgrades, every moved unit attributed), a 300-project `--full` chain A/B per gate, a fresh-eyes soak on a real board (SacMap rev2 run 8), harness unit tree 1,551 passed, contract suite 707 passed.

**Thanks:** jlecoeur (#46 — the `Manufacturer P/N` report with the exact three-list table).

---

## v2.3.0 — 2026-10-04

**Theme: correctness batch — 18 tracker defects fixed at the root plus three community contributions, every one gated over the full corpus. The loudest false-positive class in PCB analysis (CP-003 touch-pad clearance) is measured for real now, decoupling association means what it says, power accounting stops dropping loads, and a new SP-001 rule catches the one wiring mistake ERC cannot see.**

### Added

- **SP-001** — two-pin passive or diode with both pins on one net (the part is shorted out; ERC and DRC pass because the netlist is internally consistent). Jumpers, net ties, 0 Ω links and DNP parts are excluded; five or more hits on one net collapse into a single net-level finding, which on the corpus almost always means the net map merged two rails. (#43 — contributed by danielboston38.)
- `skills/lcsc/scripts/search_lcsc.py` — stdlib-only LCSC/JLCPCB parts search by keyword, MPN or `Cxxxxx`, with `--basic`/`--in-stock`/`--package` filters, `--category` parametric mode, `--details` enriched from LCSC's product-detail endpoint, and `--json`; 21 offline tests wired into CI. (#42 — contributed by AlanRosenthal.)
- Thermal output: `summary.components_skipped` and a `skipped_components[]` list with reasons (`no_load_estimate`, `no_vout`, `below_min_pdiss`) — a regulator that could not be assessed is named instead of silently vanishing from a 97/100 report. (KH-386)
- `power_budget.rails[*].other_loads[]` — LED loads (5 mA each), including LEDs one series-resistor hop from the rail, with the resistor named in `via`. (KH-375)
- PCB `decoupling_placement[].gnd_only_caps` (caps within 10 mm rejected for sharing only ground with the IC); CP-003 findings carry `nets` and `measurement_basis: "filled_polygon"`. (KH-379, KH-373)
- Via facts `min_pad_drill_mm`; DFM min-drill and `.kicad_pro`/`.kicad_dru` design-rule checks now include footprint pad drills (oval drills use the smaller dimension), so a 0.2 mm thermal via under a QFN trips a 0.3 mm project rule. (KH-383)
- EMC PD-001 carries `transient_a`, `transient_source` (`config` / `power_budget` / `default`), `peaks_total`, `peaks_shown` and `out_of_band_peaks`; new `.kicad-happy.json` key `project.pdn_transient_current_a` overrides the transient-current assumption. (KH-377)
- GP-001 reports capacitive-touch-pad nets at INFO with `is_touch_net: true` — the pour clearance under a touch pad is intentional. (KH-378)
- CI determinism guard gains a second schematic fixture (USB connector with two ESD ICs) so the `differential_pairs[].esd_protection` class stays dead. (KH-406)

### Fixed

- **#44** — PP-001 walks through fuses and polyfuses (connector → fuse → decoupled rail → IC no longer reports "no DC path"), and `is_power_net_name` recognises plain `5V`/`12V`, letter-suffixed rails (`5VSB`, `12VIN`, `5VUSB`), descriptive rails (`USB_5V`, `RAW_5V`, `SERVO_VCC`, `USB_VBUS`, `SYS_VOUT`) while keeping control lines (`5VEN`, `PWM_5V`, `ADC_VBUS`) and op-amp outputs (`OPAMP1_VOUT`) as signals. `0V`, `0VA`, `0VANA` are ground; `0V9`/`0V85` stay rails. (Contributed by danielboston38; KH-407.)
- CP-003 touch-pad GND clearance is measured from the pad outline to the nearest filled-polygon edge instead of footprint origin to zone bounding box — the old number was 0.0 mm on 78% of emitting boards and labelled deterministic. Touch pads now need positive evidence (library/value naming touch/capacitive, or a `TOUCH`/`TCH` reference); a bare `TP` prefix no longer qualifies, because 95% of CP-003 findings were test points. Pad sampling uses KiCad's absolute pad orientation. (KH-373)
- DC-001 decoupling distance only associates capacitors that share a non-ground net with the IC, so a ground-only cap nearby no longer fires a spurious DC-001 or suppresses the correct DC-002; boards whose only ICs are ESD parts get their bypass analysis. (KH-379)
- GP-001 via-antipad credit checks that the via physically spans the probed reference layer — a blind via can no longer mask a real plane gap on a layer it does not reach. (KH-397)
- The datasheet-authority gates in PS-001, VM-001, PR-004, the regulator VIN rail estimate and the EMC USB-speed classifier receive the project directory and can find `datasheets/extracted/` — they were permanently inert before. (KH-376)
- Thermal TH-DET assessments from the package table carry heuristic confidence (the finding-level twin was fixed in v2.2.1). (KH-398)
- BE-001 measures distance to circular board-outline edges as a circle instead of a bogus origin-anchored segment. (KH-399)
- `power_budget` evaluates the pin it is iterating instead of the first pin of that component on the net (an IC whose `~{SRCLR}` or EN pin sorted first was dropped from its rail), counts regulator-output rails whose names fail the power-name test, and feeds LDO dissipation from the rail's total load. (KH-375)
- Sleep-current audit consults power-sequencing EN connectivity (a regulator whose EN is tied to its input is always-on, not "disableable"), resolves `+BATT`/`VBAT` voltages from regulator data or a 3.7 V default instead of dropping the battery divider, and ignores sub-100 Ω shunts that read as 740 A "pull-ups". (KH-374)
- PD-001 no longer models feedback-divider feedforward caps as decouplers (the sole cause of one soak board's +5 V error), defaults the transient assumption to 0.5 A instead of a doubled fallback, demotes anti-resonance peaks above 200 MHz to INFO, prints capacitances in engineering units, and reports "showing N of M". (KH-377)
- `cross_analysis.py` no longer crashes on `"bounding_box": null` (VS-002 is skipped with a reason); every producer read tolerates explicit nulls. (KH-401)
- JSONC trailing-comma stripping in `.kicad-happy.json` is string-aware — a value ending in `,}` or `,]` no longer loses its comma. (KH-400)
- lcsc fetch/sync fall through to LCSC's product-detail endpoint when a jlcsearch hit lacks a datasheet URL (jlcsearch dropped its `extra` block); SKILL.md documents the live API shapes. (KH-405)
- Output byte-stability: `differential_pairs[].esd_protection`, RF `component_roles` and EMC CK-001 clock-net order no longer depend on the hash seed. (KH-406, KH-396)
- An `F`-referenced logic IC (a 74LS32 as `F1`) classifies as an IC, not a fuse, so PP-001 does not walk through it; fuse current ratings like `4000mA` still classify as fuses.
- SPICE runner summary tolerates reports without `total_elapsed_s`.
- **#47** — every datasheet sync script (DigiKey, Mouser, LCSC, element14) and the extraction cache wrote `manifest.tmp` then `Path.rename()`d it over the live manifest, which raises `WinError 183` on Windows once the target exists — the second save of any sync run crashed. All six sites use `Path.replace()` (atomic on POSIX, overwrites on Windows). (Reported by dev-nul1, fixed by UfukGuler34 in #48.)

### Changed

- **PD-001 field rename:** `transient_amps` → `transient_a` (the only non-additive output change in this release).
- **CP-003 semantics:** touch pads require positive evidence; expect the finding count to drop by roughly 96% corpus-wide and the survivors to report real clearances.
- `decoupling_placement[].nearby_caps` lists only caps sharing a non-ground net with the IC — DC-001/DC-002/DC-003 move accordingly.
- Bus aliases stay project-wide: a proposed per-file scoping (KH-395) was implemented, refuted against `kicad-cli`'s netlist on a real project (KiCad resolves `{SPI}` with an alias declared in another sheet), and reverted before release.

**Validation:** full budgeted corpus gate over the whole range (170,014 units, zero downgrades, every moved unit attributed), a 300-project `--full` PCB→EMC→thermal chain A/B (0 crashes), three-seed determinism on every analyzer, contract suite 707 passed, harness unit tree 1,453 passed.

**Thanks:** danielboston38 (#43 SP-001 and #44 fuse/power-rail fixes — both reworked within hours and verified with `kicad-cli` ground truth), Alan Rosenthal (#42 `search_lcsc.py`), dev-nul1 (#47 Windows manifest-save diagnosis, down to the line numbers) and UfukGuler34 (#48 the fix).

## v2.2.1 — 2026-09-01

**Theme: maintenance batch — 25 verified analyzer fixes. Field-reported false positives killed at the root, a whole class of output nondeterminism eliminated with a CI guard to keep it dead, and new observability surfaces so skipped or degraded analysis is visible instead of silent.**

### Added

- `power_net_resolution` block on PCB output: which nets classified as power/ground and under which resolution (`cli` / `schematic` / `heuristic`). New `--power-rails` flag; rails auto-read from `--schematic analysis/<run_id>/schematic.json` when provided. (KH-393, #40 — reported by curtisgalloway.)
- `checks_run` manifest on cross-analysis output: every check reports whether it ran, why it was skipped, and how much it examined — no more silently absent checks. (KH-381)
- `connectivity_graph_error` on PCB output when `--full` connectivity-graph construction fails — previously a silent `except: pass`. (audit KHPA-005 subset)
- **FV-001** info finding when a file's format version is newer than the analyzer's tested maximum — analysis proceeds best-effort but says so. (audit KHPA-002)
- `conditional_rules_skipped` note in `design_rule_compliance`: conditional `.kicad_dru` rules are skipped and counted instead of being wrongly applied board-wide. (KH-361)
- Deep-review gate: quotes with `…` elision verify segment-wise, quarantine reasons include a nearest-match snippet, and computation-script paths anchor to the analysis directory regardless of cwd. (KH-384, KH-385)

### Fixed

- **#39** — GP-001 no longer counts a via's own antipad as a reference-plane gap; any via ≥ ~0.7 mm (including KiCad's 0.8 mm default) previously read as a return-path hole. (KH-392 — reported by curtisgalloway)
- **#40** — Schematic-declared power rails are now threaded into all five PCB net-classification sites; per-port rails like `P1_VBUS` no longer silently read as signal in both directions. (KH-393 — reported by curtisgalloway)
- **#41** — No-connect markers no longer create connectivity with wires passing mid-span beneath them; NC'd pins stay on their own net exactly as `kicad-cli` reports, and absorbing nets no longer inherit a false `no_connect` tag. Corpus impact was real: one board had eight I2C pairs falsely shorted. (Contributed by danielboston38.)
- **#33** — ICs whose Description mentions an internal oscillator ("Internal Reference, Oscillator, …") are no longer reclassified as oscillators, and the clock-distribution fallback no longer invents clock outputs from the first non-power pin. (KH-370 — reported by William Leismer)
- **#31** — BE-001 board-edge distance now measures to a `gr_rect` outline's four sides instead of its diagonal. (KH-357 — reported by Erik Norfelt)
- Output byte-stability: eliminated a class of hash-order nondeterminism (RC-DET candidate pick, DO-DET rail lists, power-sequencing EN-net pick, XV-002 ordering, connectivity pad-pair ordering and ~20 sibling sites), and CI now runs every analyzer twice with an unpinned hash seed to keep the class dead. (KH-366, KH-367, KH-382, KH-394)
- VP-001 reads the via `tenting` field actually written by the parser — tented vias-in-pad were always reported untented. (KH-358)
- Duplicate voltage-divider findings sharing one `finding_id` are deduplicated at flatten, with a consumer-side belt in SPICE subcircuit collection. (KH-388)
- PM-002 never renders negative "mm from board edge" distances, and parts placed entirely off-board are classified distinctly at warning severity instead of "overhangs board edge" at error. (KH-389)
- DS-003 datasheet coverage counts unique BOM lines with the same denominator as SS-002, and both summaries name the basis. (KH-390)
- `summarize_findings.py` renders deep-review rows honestly: `dr:<category>` rule labels, no column overflow, deep-review confidence vocabulary in its own bucket. (KH-391)
- JSONC comment stripping in `.kicad-happy.json` is string-aware — config values containing `//` (URLs) or `/*` no longer corrupt the file and silently drop suppression layers. (KH-368)
- `.kicad_pro` / `.kicad_dru` discovery matches by board stem instead of taking the first file in the directory, and `project_settings.source` names the file actually loaded. (KH-362)
- Lifecycle: LC-ACT findings carry `confidence`/`evidence_source` (no more forced-low trust), LCSC-only unknowns report "unknown" instead of "active", and LC-005 single-source accounting distinguishes attempted vs responded sources with `status: None` never counted as active. Validated against live DigiKey/Mouser APIs. (KH-371, KH-372)
- Thermal package-table estimates carry heuristic confidence in `_thermal_confidence`. (KH-387)
- NR-001 critical-net edge routing reads `board_outline.edges` — the check was structurally unable to fire before. (KH-380)
- Net-ID map resets before footprint extraction (latent cross-call state leak). (KH-363)
- `bus_topology.unresolved` reasons are normalized snake_case tokens (documented in `net-tracing.md`), and repeated cluster ambiguity notes are deduplicated. 

### Changed

- **GitHub Action — behavior change:** project auto-detection is now deterministic. Repos with exactly one project auto-select as before; repos with multiple (or zero) KiCad projects **must set the `schematic`/`pcb` inputs explicitly** — the Action fails with a candidate list instead of silently analyzing an arbitrary project. PCB-only invocations (explicit `pcb` input) are unaffected. (KH-369)
- DS-003's `bom_size` field now counts unique BOM lines (was per-component count) — consumers keying on it should note the basis change. (KH-390)
- SKILL.md documents the flatpak-sandboxed `kicad-cli` `/tmp` restriction.

**Validation:** full budgeted corpus regression gate over the entire release range (170,014 units, zero downgrades) plus incremental gates for late folds; contract suite 707 passed; per-analyzer determinism verified with unpinned hash seed; lifecycle fixes validated against live distributor APIs.

**Thanks:** Erik Norfelt (#31), William Leismer (#33), Curtis Galloway (#39, #40 — two exemplary reports with exact line references), and danielboston38 (#41 — fix contributed with `kicad-cli` ground-truth verification).

## v2.2.0 — 2026-08-20

**Theme: schematic connectivity correctness — hierarchical bus resolution, net identity, and provenance honesty. "Brick one" of the correctness-floor direction: analyzer connectivity is validated against KiCad's own netlist export as ground truth.**

### Added

- **#25** — Hierarchical bus connectivity: bus definitions (`D[0..7]`, `{...}` groups, bus aliases) expand into member nets, bus wires and bus entries join the net graph, and hierarchical bus pins connect positionally per sheet instance. New `skills/kicad/scripts/bus_resolver.py` (`expand_bus_name` / `BusGraph` / `match_ports`) bridged into `build_net_map`. Kills the phantom single-pin nets on bus-heavy hierarchical designs. (Reported by Reid-n0rc.)
- Unresolvable bus connections are surfaced honestly in a new `bus_topology.unresolved` list instead of silently guessed.
- Hierarchical and local labels with the same name on the same sheet now join (KiCad-verified behavior; also applies on non-bus boards).
- Antigravity plugin support: root `plugin.json` manifest + `agy plugin install` docs, replacing the deprecated Gemini CLI path. (Contributed by ademuri.)
- OSHWA certification-readiness guidance in the kicad skill. (Contributed by Daniel Gleason.)

### Fixed

- **KH-359** — Same-name local labels on different sheets no longer merge into one net entry. On bare-name collisions the global net keeps the bare key and locals get KiCad-style `/<sheet>/<name>` keys; every net entry now carries a `display_name`.
- **KH-360** — Wire union joins every overlapping wire instead of stopping at the first (order-dependent disconnections at mid-segment junction taps).
- Findings no longer claim datasheet provenance they don't have: thermal TH-DET / TS-001/002/003/005 package-table estimates and lifecycle LC-005/LC-006 API-derived findings now carry `heuristic_rule` / `api_lookup`; LT-001 upgrades genuine extraction-cache data to `datasheet`. `trust_summary.by_evidence_source` shifts accordingly. (Contributed by fl4p.)
- **#38** — Removed the dangling `.agents/skills/kidoc` symlink that broke GitHub Action downloads for all v2 consumers; added the missing `datasheets` symlink. (Reported by orthdron; fix landed via #36.)
- DigiKey FastAdd doc example no longer suggests `&newcart=true`, which silently empties the current cart. (Contributed by fl4p.)

### Changed

- **Suppression matching widened:** bare net-name suppression patterns now also match the tails of hierarchical `/uuid/Name` keys AND the new `/<sheet>/<name>` qualified keys. Existing suppression configs may match more nets than before — review bare net-name patterns on multi-sheet projects.
- Envelope additions (all additive): `NetEntry.display_name`, typed `NetLabel`, `BusTopology.unresolved`.

### Validation

- kicad-cli netlist oracle (ground truth): strict pass on 5 golden boards — 80 / 221 / 1,220 / 486 / 70 nets, including an m68k homebrew computer and a KiCad-6-era design.
- Full budgeted corpus regression gate CLEAN over the entire v2.1.0 → v2.2.0 range (170,014 units); bus-free boards byte-identical by invariant.
- Contract suite: 706 passed / 8 skipped / 4 xfailed.

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
