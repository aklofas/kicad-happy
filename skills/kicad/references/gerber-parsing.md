# Gerber and Drill File Parsing

This reference covers parsing Gerber (RS-274X) and Excellon drill files for analysis, verification, and cross-referencing with KiCad source files.

## Table of Contents

1. [Gerber RS-274X Format](#gerber-rs-274x-format)
2. [Aperture Definitions](#aperture-definitions)
3. [Draw and Flash Commands](#draw-and-flash-commands)
4. [Layer Identification](#layer-identification)
5. [Gerber Attributes (X2)](#gerber-attributes-x2)
6. [Excellon Drill Format](#excellon-drill-format)
7. [Gerber Job File](#gerber-job-file-gbrjob--kicad-6-only)
8. [Analysis Techniques](#analysis-techniques)

---

## Gerber RS-274X Format

Gerber files are plain text. Each file represents one layer. The format uses single-character commands and coordinate data.

### Basic Structure

```gerber
G04 Layer: F.Cu*                    ; Comment
G04 KiCad-generated file*
%FSLAX46Y46*%                       ; Format specification
%MOMM*%                             ; Units: MM (millimeters) — most KiCad exports
                                    ; Alternative: %MOIN*% for inches
%LNFRONT*%                          ; Layer name

; Aperture definitions
%ADD10C,0.200000*%                  ; Define aperture 10 as circle, 0.2mm diameter
%ADD11R,1.000000X0.600000*%         ; Define aperture 11 as rectangle, 1.0 x 0.6mm

; Drawing commands
D10*                                ; Select aperture 10
X150000000Y100000000D03*            ; Flash pad at (150, 100)mm
X150000000Y100000000D02*            ; Move to (150, 100)mm, pen up
X160000000Y100000000D01*            ; Draw to (160, 100)mm, pen down

M02*                                ; End of file
```

### Format Specification (%FS)

```
%FSLAX46Y46*%
```
- `L` = Leading zeros omitted (most common), `T` = Trailing zeros omitted
- `A` = Absolute coordinates (most common), `I` = Incremental
- `X46` = X has 4 integer digits, 6 decimal digits
- `Y46` = same for Y
- With `%FSLAX46Y46*%` and `%MOMM*%`: coordinate 150000000 = 150.000000mm

### Units

```
%MOMM*%    ; Millimeters (KiCad default)
%MOIN*%    ; Inches
```

### Coordinate Conversion

To convert raw coordinates to real units:
- With format `X46Y46` and `MOMM`: divide by 10^6 to get mm
- With format `X46Y46` and `MOIN`: divide by 10^6 to get inches, multiply by 25.4 for mm
- With format `X24Y24` and `MOIN`: divide by 10^4 to get inches

Example: `X150000000Y100000000` with `FSLAX46Y46` and `MOMM` = (150.0mm, 100.0mm)

---

## Aperture Definitions

Apertures define the shape of the "pen" used for drawing and flashing. Defined in the header with `%AD` commands.

### Standard Apertures

```gerber
%ADD10C,0.250000*%                  ; Circle: diameter 0.25mm
%ADD11C,0.200000X0.100000*%         ; Circle with hole: 0.2mm dia, 0.1mm hole
%ADD12R,1.000000X0.600000*%         ; Rectangle: 1.0mm x 0.6mm
%ADD13O,1.200000X0.800000*%         ; Obround (oval): 1.2mm x 0.8mm
%ADD14P,1.000000X6X0.0*%            ; Polygon: 1.0mm dia, 6 vertices, 0 deg rotation
```

| Code | Shape | Parameters |
|------|-------|-----------|
| `C` | Circle | diameter[X hole_diameter] |
| `R` | Rectangle | width X height[X hole_diameter] |
| `O` | Obround (oval) | width X height[X hole_diameter] |
| `P` | Regular polygon | outer_dia X n_vertices X rotation[X hole_diameter] |

### Aperture Macros

Complex pad shapes use macros defined with `%AM`:

```gerber
%AMROUNDRECT*
0 Rectangle with rounded corners*
21,1,$1,$2,0,0,0*
21,1,$3,$4,0,0,0*
1,1,$5,$6,$7*
1,1,$5,$8,$9*
1,1,$5,$10,$11*
1,1,$5,$12,$13*
%
%ADD15ROUNDRECT,0.250000X-0.262500X-0.450000X0.262500X...*%
```

Aperture macros are complex — for analysis, focus on the overall bounding box rather than trying to parse the macro primitives.

### Aperture Numbering

- Apertures are numbered D10 and above (D01-D09 are reserved for operation codes)
- KiCad typically assigns: D10+ for pads and traces
- The aperture number is referenced in draw/flash commands

---

## Draw and Flash Commands

### Operation Codes

| Code | Action | Description |
|------|--------|-------------|
| `D01` | Draw (interpolate) | Draw from current position to new position with current aperture |
| `D02` | Move | Move to position without drawing (pen up) |
| `D03` | Flash | Stamp the current aperture shape at the position |
| `D10+` | Select aperture | Switch to aperture N for subsequent operations |

### Command Format

```gerber
D11*                                ; Select aperture 11
X150000000Y100000000D03*            ; Flash aperture 11 at (150, 100)
X150000000Y100000000D02*            ; Move to (150, 100) — no draw
X160000000Y100000000D01*            ; Draw line from current pos to (160, 100)
X160000000Y110000000D01*            ; Continue drawing to (160, 110)
```

### Interpolation Modes

```gerber
G01*            ; Linear interpolation (straight lines) — default
G02*            ; Clockwise circular interpolation (arcs)
G03*            ; Counter-clockwise circular interpolation (arcs)
G74*            ; Single quadrant arc mode
G75*            ; Multi-quadrant arc mode (most common)
```

### Arc Commands

```gerber
G75*                                 ; Multi-quadrant mode
G02*                                 ; Clockwise arc
X160000000Y100000000I5000000J0D01*   ; Draw arc to (160,100) with center offset (I=5, J=0)
```
- `I` and `J` are the offset from the current position to the arc center
- Arc radius = sqrt(I^2 + J^2)

### Region Fill (Copper Pour Outlines)

```gerber
G36*                                ; Start region (polygon fill)
X100000000Y80000000D02*             ; Move to start point
X180000000Y80000000D01*             ; Draw boundary
X180000000Y140000000D01*
X100000000Y140000000D01*
X100000000Y80000000D01*             ; Close polygon
G37*                                ; End region
```

Region fills (G36/G37) represent filled copper areas — zones, pads with custom shapes, etc.

---

## Layer Identification

### KiCad Gerber Filenames

KiCad uses predictable filename suffixes. The naming changed between KiCad 5 and KiCad 6:

| KiCad 6+ Suffix | KiCad 5 Suffix | KiCad Layer | Description |
|----------------|----------------|-------------|-------------|
| `-F_Cu.gbr` | `-F_Cu.gbr` | F.Cu | Front copper |
| `-B_Cu.gbr` | `-B_Cu.gbr` | B.Cu | Back copper |
| `-In1_Cu.gbr` | `-In1_Cu.gbr` | In1.Cu | Inner copper layer 1 |
| `-In2_Cu.gbr` | `-In2_Cu.gbr` | In2.Cu | Inner copper layer 2 |
| `-F_Paste.gbr` | `-F_Paste.gbr` | F.Paste | Front solder paste (stencil) |
| `-B_Paste.gbr` | `-B_Paste.gbr` | B.Paste | Back solder paste |
| `-F_Silkscreen.gbr` | `-F_SilkS.gbr` | F.SilkS | Front silkscreen |
| `-B_Silkscreen.gbr` | `-B_SilkS.gbr` | B.SilkS | Back silkscreen |
| `-F_Mask.gbr` | `-F_Mask.gbr` | F.Mask | Front solder mask |
| `-B_Mask.gbr` | `-B_Mask.gbr` | B.Mask | Back solder mask |
| `-Edge_Cuts.gbr` | `-Edge_Cuts.gbr` | Edge.Cuts | Board outline |
| `-F_Courtyard.gbr` | `-F_CrtYd.gbr` | F.CrtYd | Front courtyard (not for manufacturing) |
| `-F_Fab.gbr` | `-F_Fab.gbr` | F.Fab | Front fabrication (not for manufacturing) |

**Version detection from filenames:** If gerber files use `_SilkS` instead of `_Silkscreen`, they were generated by KiCad 5 (the rename happened in KiCad 6). Detect both patterns when building a file inventory.

With Protel extensions enabled:

| Extension | Layer |
|-----------|-------|
| `.GTL` | Front copper |
| `.GBL` | Back copper |
| `.G2` / `.G3` | Inner layers |
| `.GTP` | Front paste |
| `.GBP` | Back paste |
| `.GTO` | Front silkscreen |
| `.GBO` | Back silkscreen |
| `.GTS` | Front mask |
| `.GBS` | Back mask |
| `.GKO` | Board outline |

### Gerber X2 File Attributes

KiCad writes X2 attributes that identify the layer, but the **format differs by version**:

**KiCad 6+ (X2 directives):**
```gerber
%TF.GenerationSoftware,KiCad,Pcbnew,9.0.0*%
%TF.CreationDate,2025-01-15T10:30:00-06:00*%
%TF.ProjectId,myproject,<uuid>,rev1*%
%TF.SameCoordinates,Original*%
%TF.FileFunction,Copper,L1,Top*%     ; <-- Layer identification
%TF.FilePolarity,Positive*%
```

**KiCad 5 (X2 in G04 comments):**
```gerber
G04 #@! TF.GenerationSoftware,KiCad,Pcbnew,5.1.5-52549c5~84~ubuntu18.04.1*
G04 #@! TF.CreationDate,2020-03-09T10:29:23-07:00*
G04 #@! TF.ProjectId,myproject,6d797072-6f6a-4563-9400-000000000000,rev?*
G04 #@! TF.SameCoordinates,Original*
G04 #@! TF.FileFunction,Copper,L1,Top*
G04 #@! TF.FilePolarity,Positive*
```

KiCad 5 embeds X2 attributes as structured comments (`G04 #@!`) rather than native `%TF.*%` directives. The attribute names and values are identical — only the container syntax differs. When parsing, check for both patterns:
- `%TF.FileFunction,(.*)\\*%` (KiCad 6+)
- `G04 #@! TF.FileFunction,(.*)\\*` (KiCad 5)

### FileFunction Values

| FileFunction | Layer |
|-------------|-------|
| `Copper,L1,Top` | Front copper |
| `Copper,L2,Bot` | Back copper (2-layer) |
| `Copper,L2,Inr` | Inner layer 2 (4+ layer) |
| `Copper,L4,Bot` | Back copper (4-layer) |
| `Soldermask,Top` | Front solder mask |
| `Soldermask,Bot` | Back solder mask |
| `Legend,Top` | Front silkscreen |
| `Legend,Bot` | Back silkscreen |
| `Paste,Top` | Front paste |
| `Paste,Bot` | Back paste |
| `Profile,NP` | Board outline (non-plated) |

---

## Gerber Attributes (X2)

Gerber X2 attributes provide machine-readable metadata. KiCad 5.1+ writes file (`TF`), aperture (`TA`) and object (`TO`) attributes. With X2 output on they are native `%T…*%` commands; with X2 off (`kicad-cli … --no-x2`) KiCad writes the same commands as `G04 #@! T…*` structured comments. Both forms carry the same data, and the analyzer reads both. Object attribute fields escape `\ % * ,` and (in non-UTF-8 output) non-ASCII characters as `\uXXXX`; the analyzer decodes these as KiCad does (the older `\XXXX` form is left as written). KiCad writes `%TO.P` with the reference on outer-copper pads and no `%TO.C`; a pad that connects to nothing gets an empty net (`%TO.N,*%`), which is not counted as a net.

### Version Compatibility Matrix

| Attribute Type | KiCad 5.1 | KiCad 6+ | Format (X2 off) | Format (X2 on) |
|---------------|---------|----------|-------------------|-------------------|
| File attributes (`TF`) | Yes | Yes | `G04 #@! TF.*` | `%TF.*%` |
| Aperture attributes (`TA`) | Yes | Yes | `G04 #@! TA.*` | `%TA.*%` |
| Object attributes (`TO`) | Yes | Yes | `G04 #@! TO.*` | `%TO.*%` |

Gerbers without these attributes (older KiCad versions, other tools) cannot be mapped back to components or nets from the gerber files alone — you need the source files for that information.

### File Attributes (%TF)

```gerber
%TF.GenerationSoftware,KiCad,Pcbnew,9.0.0*%
%TF.CreationDate,2025-01-15T10:30:00-06:00*%
%TF.ProjectId,project_name,<uuid>,rev1*%
%TF.FileFunction,Copper,L1,Top*%
%TF.FilePolarity,Positive*%
```

### Aperture Attributes (%TA) — KiCad 5.1+

```gerber
%TA.AperFunction,SMDPad,CuDef*%     ; This aperture is an SMD pad
%ADD10C,0.200000*%                    ; Aperture definition follows
%TD*%                                 ; Delete attribute (reset for next aperture)

%TA.AperFunction,Conductor*%          ; This aperture is a track/trace
%TA.AperFunction,ViaPad*%             ; This aperture is a via pad
%TA.AperFunction,ComponentPad*%       ; This aperture is a component pad
%TA.AperFunction,NonConductor*%       ; Non-copper feature
```

Without aperture attributes (older KiCad, other tools), you can still classify apertures heuristically:
- Small circular apertures used with D01 (draw) commands → traces (diameter = trace width)
- Apertures used only with D03 (flash) commands → pads or vias
- Distinguish via vs component pads by cross-referencing drill file positions

### Object Attributes (%TO) — KiCad 5.1+

```gerber
%TO.C,R1*%                           ; This object belongs to component R1
%TO.N,GND*%                          ; This object is on net GND
%TO.P,R1,1*%                         ; This is pin 1 of R1
```

These are extremely useful for analysis — they let you map gerber features back to schematic components and nets without needing the KiCad source files. When these attributes are absent (older KiCad, other tools), component/net analysis requires parsing the `.kicad_pcb` source file instead.

---

## Excellon Drill Format

Drill files define hole positions and sizes. KiCad exports Excellon format.

### Basic Structure

```excellon
M48                                  ; Header start
; DRILL file {project.kicad_pcb} date 2025-01-15
; FORMAT={-:-:metric}
; #@! TF.GenerationSoftware,KiCad,Pcbnew,9.0.0
; #@! TF.CreationDate,2025-01-15
; #@! TF.FileFunction,Plated,1,2,PTH    ; Plated through holes, layer 1 to 2
FMAT,2                               ; Format 2 (most common)
METRIC,TZ                            ; Metric units, trailing zeros
; #@! TA.AperFunction,Plated,PTH,ViaDrill
T1C0.300                            ; Tool 1: 0.3mm drill
; #@! TA.AperFunction,Plated,PTH,ComponentDrill
T2C0.800                            ; Tool 2: 0.8mm drill
T3C1.000                            ; Tool 3: 1.0mm drill
%                                    ; End of header

T1                                   ; Select tool 1 (0.3mm via drill)
X150000Y100000                       ; Drill at (150, 100)mm
X155000Y100000                       ; Drill at (155, 100)mm
X160000Y105000

T2                                   ; Select tool 2 (0.8mm component drill)
X120000Y90000
X125000Y90000

T3                                   ; Select tool 3 (1.0mm)
X110000Y110000

M30                                  ; End of file
```

### Coordinate Format

Two distinct formats depending on KiCad version:

**KiCad 6+ (metric, integer coordinates):**
- Header: `METRIC,TZ` or `METRIC,LZ`
- Format hint: `; FORMAT={-:-:metric}`
- Coordinates in microns (divide by 1000 for mm)
- Example: `X150000Y100000` = (150.0mm, 100.0mm)

**KiCad 5 (imperial, decimal coordinates):**
- Header: `INCH` (no TZ/LZ suffix)
- Format hint: `; FORMAT={-:-/ absolute / inch / decimal}`
- Coordinates are decimal inches — parse as float, multiply by 25.4 for mm
- Example: `X1.3875Y-2.77` = (1.3875in, -2.77in) = (35.2425mm, -70.358mm)
- Tool sizes also in inches: `T1C0.0157` = 0.0157in = 0.399mm

**Important:** KiCad 5 drill coordinates may have negative Y values (KiCad 5 used inverted Y-axis). KiCad 6+ always uses positive coordinates.

### Tool Definitions

```
T1C0.300     ; Tool 1, Circle 0.3mm diameter
T2C0.800     ; Tool 2, Circle 0.8mm diameter
```

### Drill File Types

KiCad can export:
- **PTH** (Plated Through Holes): vias and through-hole component pads
- **NPTH** (Non-Plated Through Holes): mounting holes, mechanical features
- **Merged**: both PTH and NPTH in one file (JLCPCB preference)

Check the `TF.FileFunction` attribute:
```
; #@! TF.FileFunction,Plated,1,2,PTH       ; Plated, from layer 1 to 2 (2-layer board)
; #@! TF.FileFunction,Plated,1,4,PTH       ; Plated, from layer 1 to 4 (4-layer board)
; #@! TF.FileFunction,NonPlated,1,2,NPTH   ; Non-plated
; #@! TF.FileFunction,MixedPlating,1,2     ; Merged PTH+NPTH
```

The layer span (e.g., `1,4`) indicates the board layer count — `Plated,1,4,PTH` means through-holes spanning all 4 layers.

### Drill Tool Attributes — KiCad 6+ Only

```
; #@! TA.AperFunction,Plated,PTH,ViaDrill         ; Via
; #@! TA.AperFunction,Plated,PTH,ComponentDrill    ; Through-hole component
; #@! TA.AperFunction,NonPlated,NPTH,BoardEdge     ; Board cutout
; #@! TA.AperFunction,Plated,Buried,ViaDrill       ; Buried via
```

KiCad 5 drill files have no tool attributes. Without them, you cannot distinguish via drills from component drills by the drill file alone. Heuristics:
- Smallest drill diameter → likely via drill (typical: 0.3-0.4mm)
- Larger drill diameters → likely component drills (typical: 0.8-1.0mm+)
- Cross-reference drill positions with copper pad flashes for definitive classification

### Routed Slots

Oval or non-round holes use routing commands:

```
T2C1.000
G85X120000Y90000X125000Y90000       ; Route (slot) from (120,90) to (125,90)
```

Or in route mode (KiCad's default oval format in the GUI drill dialog):
```
G00X120.0Y90.0                       ; Move to the start of the slot
M15                                  ; Plunge (router down)
G01X125.0Y90.0                       ; Cut to the end of the slot
M16                                  ; Retract
G05                                  ; Back to drill mode
```

Either form is one hole of its tool, as in KiCad's drill report. KiCad's Gerber-format drill files (`-PTH-drl.gbr`, `-NPTH-drl.gbr`, `%TF.FileFunction,Plated|NonPlated,…`) flash round holes and draw a slot as one segment; they are drill files, not layers.

---

## Gerber Job File (`.gbrjob`) — KiCad 5.1+

KiCad 5.1+ exports a JSON job file alongside gerbers with board-level metadata. Without a job file, board dimensions and stackup must be extracted from the gerber/drill files directly or from the `.kicad_pcb` source.

```json
{
  "GeneralSpecs": {
    "Size": {"X": 203.05, "Y": 153.05},
    "LayerNumber": 2,
    "BoardThickness": 1.6,
    "Finish": "None"
  },
  "DesignRules": [{
    "Layers": "Outer",
    "PadToPad": 0.2, "PadToTrack": 0.2, "TrackToTrack": 0.2,
    "MinLineWidth": 0.18, "TrackToRegion": 0.5, "RegionToRegion": 0.5
  }],
  "MaterialStackup": [
    {"Type": "Copper", "Thickness": 0.035, "Name": "F.Cu"},
    {"Type": "Dielectric", "Thickness": 1.51, "Material": "FR4", "Name": "F.Cu/B.Cu"},
    {"Type": "Copper", "Thickness": 0.035, "Name": "B.Cu"}
  ]
}
```

The job file is the most reliable source for board dimensions, stackup, design rules, and copper weight (0.035mm = 1oz). Parse this first before extracting from individual gerbers.

---

## Analysis Techniques

### Full Gerber Analysis Methodology

A comprehensive gerber analysis covers these areas. For each, parse the relevant files and cross-reference where possible.

#### 1. File Inventory and Validation

Check that all required files are present and consistent:
- **Required layers**: F_Cu, B_Cu, F_Mask, B_Mask, F_Paste, B_Paste, F_Silkscreen (or F_SilkS), B_Silkscreen (or B_SilkS), Edge_Cuts
- **Inner layers** (4+ layer boards): In1_Cu, In2_Cu, etc.
- **Drill files**: At least PTH.drl; NPTH.drl if board has mounting/mechanical holes
- **Coordinate alignment**: All files should have `TF.SameCoordinates,Original` (check both `%TF.*%` and `G04 #@! TF.*` formats)
- **Date consistency**: All `TF.CreationDate` values should match — different dates mean files were regenerated at different times, risking misalignment
- **Software version**: All `TF.GenerationSoftware` should match
- **Job file**: `.gbrjob` present for complete metadata (KiCad 5.1+)
- **Filename prefix**: Auto-detect from the gerber files (project name varies — don't hardcode)

#### 2. X2 Attribute Analysis (Component/Net/Pin Mapping) — KiCad 5.1+

KiCad 5.1+ gerbers contain X2 object attributes (native or as `G04 #@!` comments) that map every copper feature back to schematic. Gerbers without them — skip this section and rely on the `.kicad_pcb` source file for component/net mapping.

```gerber
%TO.P,U2,1,FB*%      ; Pin: component U2, pin 1, name "FB"
%TO.N,Net-(U2-FB)*%   ; Net: this feature is on net "Net-(U2-FB)"
X76687500Y-150250000D03*  ; Flash pad at this position
%TD*%                  ; Clear attributes for next feature
```

To build a complete component→pin→net map from gerber alone:
1. Track `%TO.P,ref,pin,name*%` — set current component, pin number, pin name
2. Track `%TO.N,netname*%` — set current net
3. On `D03*` (flash) — record pad position with current component/pin/net
4. On `%TD*%` — reset all attributes

This produces the same information as the PCB netlist without needing the KiCad source file. Useful for verifying gerbers against schematic or reverse-engineering a board from manufacturing files.

#### 3. Aperture Function Classification

**KiCad 6+:** Aperture attributes categorize copper features:

| AperFunction | Description | What to count |
|-------------|-------------|---------------|
| `SMDPad,CuDef` | SMD pad copper definition | Pad shape count |
| `ViaPad` | Via pad | Single aperture, count flashes |
| `ComponentPad` | Through-hole component pad | Similar to SMDPad |
| `HeatsinkPad` | Thermal/exposed pad (QFN ground slug) | Usually 1-2 per IC |
| `Conductor` | Traces — circle aperture = trace width | Width distribution |
| `NonConductor` | Non-electrical copper (fiducials, logos) | — |
| `Profile` | Board outline (Edge_Cuts only) | — |

Conductor aperture diameters directly give you the trace widths used in the design. A typical design has 3-5 conductor apertures.

**KiCad 5:** No aperture function attributes. Classify heuristically:
- Parse all `%ADD<N><shape>,<params>*%` definitions
- Circular apertures (`C`) used with D01 draws → trace widths
- Rectangular/obround apertures (`R`/`O`) used with D03 flashes → pads
- Count apertures by shape type and size to understand the design's pad library

#### 4. Draw/Flash Command Statistics

Count D01 (draw), D02 (move), D03 (flash), G36/G37 (regions) per layer:

| Layer | Flashes (D03) | Interpretation |
|-------|--------------|----------------|
| F_Cu | N | Total pad count on front |
| B_Cu | N | Via pads + any back-side component pads |
| F_Mask | N | Pad openings in solder mask — should be ≥ F_Cu flashes |
| F_Paste | N | Paste stencil openings — should be ≤ F_Mask flashes |

**Key sanity checks (KiCad 6+):**
- `F_Paste flashes ≤ F_Mask flashes` — paste only on SMD pads, not on vias. The difference = via pad count (mask opening but no paste). Good sanity check against drill file via count.
- `B_Paste flashes == 0` for single-side assembly — correct if all SMD on front
- `B_Cu flashes ≈ PTH drill via count` — back via pads should match via drills
- Region count (G36/G37 pairs) on copper = number of zone fill polygons

**KiCad 5 differences:** Mask and paste layers may use **regions (G36/G37)** instead of flashes (D03) for pad openings. This means D03 flash counts can be 0 on mask/paste layers even when pads exist. Count regions instead:
- F_Mask regions ≈ total front pad + via count
- F_Paste regions ≈ SMD pad count (no via openings)
- F_Paste may have a mix of both flashes AND regions
- The flash-vs-mask delta sanity check doesn't apply — use region counts instead

#### 5. Solder Mask Polarity

Solder mask files should have **Negative polarity** (`%TF.FilePolarity,Negative*%`). This means:
- Dark areas = mask present (solder resist covers the copper)
- Clear areas = mask openings (copper exposed for soldering)

A very large B_Mask file (often 10-100x larger than B_Cu) is **normal** when there's a back-side ground plane — the mask must define the tenting pattern over the entire zone fill, which requires many polygon vertices.

#### 6. Copper Balance

Compare front and back copper layers:
- **File size ratio** gives a rough density comparison
- **Draw command count** indicates routing complexity per layer
- **Region count** = zone fills per layer
- **Net count** (from X2 attributes) — back copper typically has far fewer nets (just GND plane + vias)
- Heavily imbalanced copper can cause board warping during manufacturing

#### 7. Drill Cross-Reference

Compare drill files against copper layers:
- Via drill count (T with `ViaDrill` attribute) should match B_Cu via pad flash count
- Component drill count should match through-hole pad count
- Each drill position should have a corresponding pad flash in both F_Cu and B_Cu at the same coordinates
- Flag drills below manufacturer minimums (JLCPCB: PTH ≥ 0.2mm, NPTH ≥ 0.5mm)

#### 8. Board Outline Verification

From the Edge_Cuts gerber:
1. Parse all D01 (line) and G02/G03 (arc) commands
2. Extract coordinate bounding box
3. Verify dimensions match `.gbrjob` `Size` field
4. Count primitives: N lines + N arcs (4 arcs = rounded rectangle)
5. Verify closed polygon — last endpoint should connect back to first startpoint

### Cross-Referencing Gerber with KiCad Source

**KiCad 6+ (full X2 attributes available):**
1. **Component count**: Gerber X2 component count vs PCB footprint count. Difference = non-electrical footprints (logos, mounting holes, test points without copper pads)
2. **Net count**: Gerber X2 unique `%TO.N,...*%` values should match PCB `(net N "name")` count
3. **Pad count**: F_Cu D03 flash count vs total pad count in PCB footprints
4. **Board dimensions**: Edge_Cuts gerber bounding box vs `.gbrjob` Size vs PCB Edge.Cuts primitives — all three should agree
5. **Drill count**: PTH via drills should equal PCB `(via ...)` count; component drills should equal through-hole pad count
6. **Paste vs mask delta**: F_Paste flashes fewer than F_Mask flashes by exactly the via count (vias get mask openings but not paste)

**KiCad 5 (no object attributes):**
1. **Pad count**: Compare F_Cu flash + region count against PCB footprint pad count
2. **Board dimensions**: Edge_Cuts bounding box vs PCB Edge.Cuts primitives (no `.gbrjob` available)
3. **Drill count**: Total PTH drill count vs PCB via + through-hole pad count
4. **Layer count**: Verify inner copper files match PCB layer count; check drill span (e.g., `Plated,1,4,PTH` for 4-layer)
5. **Component/net mapping**: Must come from `.kicad_pcb` — not available in gerber files

### Gerber Verification Checklist

Pre-submission check before sending to manufacturer:

1. **Layer completeness**: All required gerber layers + drill files present (check both `_Silkscreen` and `_SilkS` naming)
2. **Inner layers**: For 4+ layer boards, verify In1_Cu, In2_Cu, etc. are present
3. **FileFunction attributes**: Each file's `TF.FileFunction` matches its layer (check both `%TF.*%` and `G04 #@!` formats)
4. **Board outline closed**: Edge.Cuts forms a closed polygon
5. **Solder mask polarity**: `Negative` (KiCad default)
6. **Paste count ≤ mask count**: No paste on vias or non-SMD pads (KiCad 6+ flash-based; KiCad 5 use region counts)
7. **Empty B_Paste**: Correct if single-side assembly
8. **Coordinate alignment**: All files use `SameCoordinates: Original`
9. **Date consistency**: All files generated on the same date
10. **Drill minimums**: PTH ≥ 0.2mm, NPTH ≥ 0.5mm (JLCPCB). Convert from inches if KiCad 5 INCH format.
11. **Drill units**: Verify METRIC vs INCH — coordinate parsing differs completely
12. **Board size**: Note if exceeds 100x100mm (JLCPCB pricing threshold)
13. **Job file**: `.gbrjob` present with correct stackup and design rules (KiCad 5.1+)

### KiCad Version Detection

Quickly determine the KiCad version from gerber files:

| Indicator | KiCad 5 | KiCad 6+ |
|-----------|---------|----------|
| X2 attribute format | `G04 #@! TF.*` (X2 off) | `%TF.*%` |
| Aperture attributes | `G04 #@! TA.*` (5.1) or native | `%TA.AperFunction,...*%` |
| Object attributes | `G04 #@! TO.*` (5.1) or native | `%TO.P,...*%`, `%TO.N,...*%`, `%TO.C,...*%` |
| Silkscreen suffix | `_SilkS` | `_Silkscreen` |
| Drill units | `INCH` (decimal) | `METRIC` (integer microns) |
| Job file | `.gbrjob` from 5.1 | `.gbrjob` present |
| Mask/paste pad openings | Regions (G36/G37) | Flashes (D03) |
| Software string | `Pcbnew,5.x.x` | `Pcbnew,6.x.x` / `7.x.x` / `8.x.x` / `9.x.x` |

---

## Writing Gerber Analysis Scripts

For a complete fallback methodology when `analyze_gerbers.py` fails — including step-by-step X2 attribute state machine parsing, coordinate conversion, drill classification, and cross-reference procedures — see `manual-gerber-parsing.md`.

Gerber and Excellon files are line-oriented text formats — simpler to parse than KiCad S-expressions but with their own quirks.

### Gerber Parsing Approach

**Line-by-line state machine:** Gerber is a sequential command format. Parse line by line, maintaining state:

```python
current_aperture = None
current_x, current_y = 0, 0
current_attrs = {}  # TO.P, TO.N, TO.C attributes
apertures = {}      # D-code → shape definition

for line in gerber_lines:
    line = line.strip()

    # Aperture definitions: %ADD10C,0.200000*%
    m = re.match(r'%ADD(\d+)(\w+),?(.*?)\*%', line)
    if m:
        apertures[int(m.group(1))] = (m.group(2), m.group(3))
        continue

    # Aperture attributes: %TA.AperFunction,Conductor*%
    m = re.match(r'%TA\.(\w+),(.*?)\*%', line)
    if m:
        # Associate with next aperture definition
        continue

    # Object attributes: %TO.P,U2,1,FB*% or %TO.N,NetName*%
    m = re.match(r'%TO\.(\w+),(.*?)\*%', line)
    if m:
        current_attrs[m.group(1)] = m.group(2)
        continue

    # Clear attributes: %TD*%
    if line == '%TD*%':
        current_attrs.clear()
        continue

    # Aperture select: D10*
    m = re.match(r'D(\d+)\*$', line)
    if m and int(m.group(1)) >= 10:
        current_aperture = int(m.group(1))
        continue

    # Coordinate + operation: X76687500Y-150250000D03*
    m = re.match(r'(?:X(-?\d+))?(?:Y(-?\d+))?D0([123])\*', line)
    if m:
        if m.group(1): current_x = int(m.group(1))
        if m.group(2): current_y = int(m.group(2))
        op = int(m.group(3))
        # D01=draw, D02=move, D03=flash
```

**Coordinate format:** KiCad gerbers use `%FSLAX46Y46*%` — 4 digits integer, 6 digits decimal, in mm. So `X76687500` = 76.687500 mm. Divide by 1,000,000 to get mm.

### Drill File Parsing

Excellon drill files have a header section (tool definitions) and a body (drill hits):

```python
tools = {}       # T-code → diameter
current_tool = None
drill_hits = []  # (x, y, tool, diameter)
units_mm = True  # False for INCH

for line in drill_lines:
    # Tool definition: T1C0.300 or T01C0.300000
    m = re.match(r'T(\d+)C([\d.]+)', line)
    if m:
        tools[int(m.group(1))] = float(m.group(2))
        continue

    # Tool select: T1 or T01
    m = re.match(r'T(\d+)$', line)
    if m:
        current_tool = int(m.group(1))
        continue

    # Drill hit: X156100Y148800 (METRIC) or X5.4075Y3.0591 (INCH)
    m = re.match(r'X(-?[\d.]+)Y(-?[\d.]+)', line)
    if m:
        x, y = float(m.group(1)), float(m.group(2))
        if not units_mm:
            x, y = x * 25.4, y * 25.4  # Convert inches to mm
        elif x > 1000:
            x, y = x / 1000, y / 1000  # METRIC integer microns
        drill_hits.append((x, y, current_tool, tools.get(current_tool, 0)))
```

**METRIC vs INCH:** KiCad 5 uses `INCH` with decimal coordinates (e.g., `X5.4075`). KiCad 6+ uses `METRIC` with integer micron coordinates (e.g., `X156100` = 156.100 mm). Check for `METRIC` or `INCH` in the header. If coordinates have decimal points, they're inches; if integer-only, divide by 1000 for mm.

### Script Output

Format analysis results as structured data for clear reporting:
- Print summary statistics first (counts, min/max/avg)
- Group findings by severity (critical → warning → info)
- Include specific coordinates and net names so findings can be located in KiCad
- When cross-referencing gerber vs PCB, print both values side-by-side for easy comparison
