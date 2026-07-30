# kidoc Scripts — Developer Reference

Engineering documentation generation scripts.

## Top-level scripts

| Script | Input | Purpose | Deps |
|--------|-------|---------|------|
| `kidoc_scaffold.py` | project dir + config | Markdown scaffold with GENERATED markers and NARRATIVE placeholders | zero-dep |
| `kidoc_generate.py` | markdown | Orchestrator — dispatches to venv for PDF/DOCX/ODT | zero-dep |
| `kidoc_orchestrator.py` | analysis JSON + project | Figure generation coordinator — augments analysis, calls run_all() | zero-dep |
| `kidoc_diagrams.py` | analysis JSON | Figure generation CLI — runs all registered generators | venv (matplotlib) |
| `kidoc_narrative.py` | analysis JSON | LLM narrative context builder | zero-dep |
| `kidoc_narrative_extractors.py` | — | 12 section data extractors + registry | zero-dep |
| `kidoc_narrative_augment.py` | — | Datasheet, SPICE, cross-reference augmentation | zero-dep |
| `kidoc_narrative_config.py` | — | Section titles, writing guidance, questions (pure data) | zero-dep |
| `kidoc_pdf.py` | markdown | PDF via ReportLab + svglib (vector SVG embedding) | venv |
| `kidoc_html.py` | markdown | Self-contained HTML with inline SVGs | zero-dep |
| `kidoc_docx.py` | markdown | DOCX via python-docx + Pillow | venv |
| `kidoc_odt.py` | markdown | ODT via odfpy + Pillow | venv |
| `kidoc_raster.py` | — | Shared SVG→PNG rasterization utility | Pillow |
| `kidoc_md_parser.py` | — | Shared markdown to element list parser | zero-dep |
| `kidoc_spec.py` | — | Document spec loading, validation, expansion (8 built-in types) | zero-dep |
| `kidoc_sections.py` | — | Section content generators for scaffold | zero-dep |
| `kidoc_tables.py` | — | Markdown table formatting + unit formatters | zero-dep |
| `kidoc_templates.py` | — | Document type section list definitions | zero-dep |
| `kidoc_venv.py` | — | Project-local venv bootstrap | zero-dep |
| `kidoc_datasheet.py` | — | Datasheet extraction + comparison tables | zero-dep |
| `kicad_cli.py` | — | kicad-cli auto-detection (PATH, flatpak, macOS, Windows) | zero-dep |
| `requirements.txt` | — | Pinned deps for reports/.venv/ | — |

## Figure engine (`figures/`)

```
figures/
├── __init__.py                    # Exports run_all(), FigureTheme
├── registry.py                    # @register decorator + GeneratorEntry dataclass
├── runner.py                      # prepare → hash-check → render pipeline
│
├── lib/                           # Shared rendering library
│   ├── svg_builder.py             # SVG element builder with gradient support
│   ├── styles.py                  # Drawing helpers (gradient_box, shadow_box, etc.)
│   ├── theme.py                   # FigureTheme dataclass + color math
│   ├── color_theme.py             # KiCad schematic/PCB color palettes
│   ├── layer_presets.py           # PCB layer visibility presets
│   ├── schematic_constants.py     # Named KiCad rendering constants
│   ├── analysis_helpers.py        # Shared data extraction (build_pin_nets)
│   ├── svg_embed.py               # SVG→ReportLab converter (3-tier fallback)
│   └── svg_to_png.py              # SVG→PNG rasterizer (Pillow-based)
│
├── renderers/                     # Schematic + PCB SVG renderers
│   ├── _path_setup.py             # Cross-skill sys.path setup for sexp_parser
│   ├── schematic.py               # render_schematic() — full sheets, crops, overlays
│   ├── pcb.py                     # render_pcb() — layer presets, net highlighting
│   ├── sch_graphics.py            # Symbol body graphics extraction
│   └── pcb_graphics.py            # Footprint/track/via extraction
│
└── generators/                    # One folder per figure type (auto-discovered)
    ├── _mpl_common.py             # Shared matplotlib theme bridge
    ├── power_tree/                # Power distribution tree diagram
    ├── architecture/              # System block diagram
    ├── bus_topology/              # I2C/SPI/UART/CAN bus diagram
    ├── pinout/                    # Connector pinout diagrams (multi-output)
    ├── schematic_overview/        # Full-sheet schematic SVGs
    ├── schematic_crop/            # Subsystem crop SVGs (multi-output)
    ├── pcb_views/                 # PCB layer preset renders (multi-output)
    ├── thermal_margin/            # Thermal margin bar chart (matplotlib)
    ├── emc_severity/              # EMC findings stacked bars (matplotlib)
    ├── spice_validation/          # SPICE scatter plot (matplotlib)
    └── monte_carlo/               # Monte Carlo histogram (matplotlib)
```

Each generator provides `prepare(analysis, config) → dict | None` and `render(data, output_path, theme) → str | None`. The runner writes each prepared dict to a `.json` file (cache key) and skips rendering if the JSON hasn't changed.

## Rendering pipeline

1. Parse `.kicad_sch` via `sexp_parser.parse_file()` (from kicad skill)
2. Extract symbol graphics (body shapes, pins) via `sch_graphics.extract_symbol_graphics()`
3. Extract connectivity (wires, labels, junctions) from the schematic
4. Render all elements to SVG in back-to-front order
5. Optionally crop to bounding box or add analysis overlays

### Coordinate system

- KiCad schematic placement: millimetres, Y-down
- Symbol library internals: millimetres, Y-up (math convention)
- SVG output: millimetres, Y-down
- Transform: mirror → rotate → translate with Y-axis flip (`abs_y = cy - rpy`)
