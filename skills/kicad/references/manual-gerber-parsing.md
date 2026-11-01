# Manual Gerber & Drill Parsing (Script Fallback)

When `analyze_gerbers.py` fails (unsupported format, newer KiCad version, non-KiCad gerbers), fall back to direct file parsing. Gerber and Excellon are simpler line-oriented text formats compared to KiCad S-expressions, but correct coordinate handling and X2 attribute state tracking require care.

## Table of Contents

1. [When to Use Manual Parsing](#when-to-use-manual-parsing)
2. [Gerber RS-274X Parsing](#gerber-rs-274x-parsing)
3. [X2 Attribute Extraction](#x2-attribute-extraction)
4. [Excellon Drill Parsing](#excellon-drill-parsing)
5. [Layer Identification](#layer-identification)
6. [Gerber Job File (.gbrjob)](#gerber-job-file-gbrjob)
7. [Cross-Reference with KiCad Source](#cross-reference-with-kicad-source)
8. [Validation Methodology](#validation-methodology)

---

## When to Use Manual Parsing

Use manual parsing when:
- `analyze_gerbers.py` crashes or returns unexpected results
- The gerbers are from non-KiCad EDA tools (Altium, Eagle, OrCAD)
- You need to validate script output against raw file data
- You need specific data the script doesn't extract (arc geometry, region vertices)
- The file is partially corrupt but still readable

Always try the script first — it handles coordinate conversion, X2 attribute state tracking, drill classification, and layer identification automatically.

---

## Gerber RS-274X Parsing

Gerber files are line-oriented text. Each file represents one PCB layer. Parse line by line maintaining state.

### Step 1: Extract Format and Units

These appear in the file header and are required for coordinate conversion.

```python
import re

with open(gerber_path) as f:
    content = f.read()
    lines = content.splitlines()

# Format specification: %FSLAX46Y46*%
fs_match = re.search(r'%FS([LT])([AI])X(\d)(\d)Y(\d)(\d)\*%', content)
if fs_match:
    x_decimals = int(fs_match.group(4))  # typically 6
    y_decimals = int(fs_match.group(6))

# Units: %MOMM*% or %MOIN*%
units_mm = '%MOMM*%' in content  # True for mm, False for inch
```

**Coordinate conversion:** Raw integer coordinates divide by `10^decimals` to get the value in the declared unit. With `%FSLAX46Y46*%` and `%MOMM*%`:
- `X150000000` = 150000000 / 10^6 = 150.0 mm
- `X76687500Y-150250000` = (76.6875 mm, -150.25 mm)

With `%MOIN*%`, divide by 10^decimals to get inches, then multiply by 25.4 for mm.

### Step 2: Parse Aperture Definitions

Apertures define the "pen" shape for drawing and flashing. They appear in the header as `%AD` commands.

```python
apertures = {}
for line in lines:
    s = line.strip()
    m = re.match(r'%AD(D\d+)(\w+),?([^*]*)\*%', s)
    if m:
        d_code = m.group(1)      # e.g., "D10"
        shape = m.group(2)       # C (circle), R (rect), O (obround), RoundRect (macro)
        params = m.group(3)      # e.g., "0.200000" or "1.000000X0.600000"
        apertures[d_code] = {'shape': shape, 'params': params}
```

**Aperture shapes and dimensions:**

| Shape | Params | Dimension extraction |
|-------|--------|---------------------|
| `C` | `diameter` | Trace width = diameter |
| `R` | `widthXheight` | Pad size (split on X) |
| `O` | `widthXheight` | Obround pad size |
| `RoundRect` | `radiusX...coords...` | Complex — 2x radius is a lower bound |

For trace width analysis, focus on `C` (circle) apertures used with D01 (draw) commands — the diameter directly gives the trace width.

### Step 3: Stateful Command Parsing

Parse draw/flash/move operations maintaining current position and aperture state.

```python
current_aperture = None
current_x, current_y = 0, 0
flash_count = 0
draw_count = 0
region_count = 0
x_min = y_min = float('inf')
x_max = y_max = float('-inf')

x_div = 10 ** x_decimals
y_div = 10 ** y_decimals

for line in lines:
    s = line.strip()

    # Aperture select: D10*
    m = re.match(r'D(\d+)\*$', s)
    if m and int(m.group(1)) >= 10:
        current_aperture = f"D{m.group(1)}"
        continue

    # Region start/end
    if s == 'G36*':
        region_count += 1

    # Coordinate + operation
    m = re.match(r'(?:X(-?\d+))?(?:Y(-?\d+))?D0([123])\*', s)
    if m:
        if m.group(1):
            current_x = int(m.group(1)) / x_div
        if m.group(2):
            current_y = int(m.group(2)) / y_div
        op = int(m.group(3))

        if op == 3:  # Flash
            flash_count += 1
        elif op == 1:  # Draw
            draw_count += 1
        # op == 2 is move (pen up)

        # Track extents
        x_min = min(x_min, current_x)
        x_max = max(x_max, current_x)
        y_min = min(y_min, current_y)
        y_max = max(y_max, current_y)
```

**Key operation codes:**

| Code | Name | Action |
|------|------|--------|
| `D01` | Draw | Draw line from current position to coordinates |
| `D02` | Move | Move without drawing (pen up) |
| `D03` | Flash | Stamp aperture shape at coordinates |
| `D10+` | Select | Switch to aperture N |
| `G01` | Linear | Straight line interpolation (default) |
| `G02` | CW arc | Clockwise circular arc |
| `G03` | CCW arc | Counter-clockwise circular arc |
| `G36` | Region start | Begin filled polygon |
| `G37` | Region end | End filled polygon |
| `G75` | Multi-quadrant | Arc mode (usually set once) |

**Coordinates may omit X or Y** if unchanged from the previous command. `Y-150250000D03*` means flash at (previous_X, -150.25).

### Step 4: Arc Parsing

Arc commands use I/J offsets from the current position to the arc center:

```
G75*                         ; Multi-quadrant mode
G02*                         ; Clockwise
X160000000Y100000000I5000000J0D01*  ; Arc to (160,100) with center offset (5,0)
```

- `I` and `J` are offsets (not absolute coords) — arc center = (current_x + I, current_y + J)
- Arc radius = sqrt(I^2 + J^2)
- Arc appears in Edge.Cuts for rounded board corners and occasionally in copper for curved traces

For board outline analysis, you mainly need arc endpoints for bounding box calculation. For precise geometry (closed polygon verification), compute the arc center and trace the path.

---

## X2 Attribute Extraction

X2 attributes are the most valuable data in modern gerber files. They come in three levels: file (`TF`), aperture (`TA`), and object (`TO`).

### File Attributes (TF) — All KiCad Versions

File attributes identify the layer and provide metadata. **KiCad 5 and 6+ both emit them**, but in different syntax:

```python
x2_attrs = {}

# Modern format (KiCad 6+): %TF.Key,Value*%
for m in re.finditer(r'%TF\.(\w+),([^*]*)\*%', content):
    x2_attrs[m.group(1)] = m.group(2)

# KiCad 5 comment format: G04 #@! TF.Key,Value*
for m in re.finditer(r'G04 #@! TF\.(\w+),([^*]*)\*', content):
    key = m.group(1)
    if key not in x2_attrs:  # Don't override modern format
        x2_attrs[key] = m.group(2)
```

**Critical TF attributes:**

| Attribute | Example | Purpose |
|-----------|---------|---------|
| `FileFunction` | `Copper,L1,Top` | Layer identification |
| `FilePolarity` | `Positive` / `Negative` | Mask layers are Negative |
| `GenerationSoftware` | `KiCad,Pcbnew,9.0.7` | KiCad version detection |
| `CreationDate` | `2026-02-24T01:31:01-08:00` | File generation timestamp |
| `SameCoordinates` | `Original` | Alignment verification |

### Aperture Attributes (TA) — KiCad 6+ Only

Aperture attributes classify aperture function. They appear **before** the `%AD` definition they apply to:

```python
pending_aper_function = None
aperture_functions = {}  # D-code -> function string

for line in lines:
    s = line.strip()

    # TA sets pending function
    m = re.match(r'%TA\.AperFunction,([^*]*)\*%', s)
    if m:
        pending_aper_function = m.group(1)
        continue

    # AD consumes pending function
    m = re.match(r'%AD(D\d+)', s)
    if m and pending_aper_function:
        aperture_functions[m.group(1)] = pending_aper_function
        continue

    # TD clears pending
    if s == '%TD*%':
        pending_aper_function = None
```

**TA.AperFunction values and meaning:**

| AperFunction | Description | Analysis use |
|-------------|-------------|-------------|
| `SMDPad,CuDef` | SMD pad copper | Count unique apertures = pad variety |
| `ViaPad` | Via pad | Usually 1-2 apertures; count flashes = via count |
| `ComponentPad` | Through-hole pad | Cross-ref with drill ComponentDrill |
| `HeatsinkPad` | Thermal/exposed pad | QFN ground slugs, power pads |
| `Conductor` | Traces | Circle diameter = trace width |
| `NonConductor` | Non-electrical | Fiducials, logos |

**KiCad 5 has no TA attributes.** Classify heuristically: small circle apertures used with D01 = traces; apertures used with D03 only = pads.

### Object Attributes (TO) — KiCad 6+ Only

Object attributes map copper features to schematic components and nets. This is the most powerful X2 feature — it enables reverse-engineering the netlist from gerber files alone.

**TO attributes are stateful:** once set, they apply to all subsequent D01/D02/D03 commands until cleared by `%TD*%` or overwritten by a new `%TO*%`.

```python
current_component = None
current_net = None
components = {}       # ref -> {pads, nets}
pin_mappings = []     # [{ref, pin, pin_name, net}]

for line in lines:
    s = line.strip()

    # TO.C sets current component reference
    m = re.match(r'%TO\.C,([^*]*)\*%', s)
    if m:
        current_component = m.group(1)
        if current_component not in components:
            components[current_component] = {'pads': 0, 'nets': set()}
        continue

    # TO.N sets current net name
    m = re.match(r'%TO\.N,([^*]*)\*%', s)
    if m:
        current_net = m.group(1)
        if current_component and current_component in components:
            components[current_component]['nets'].add(current_net)
        continue

    # TO.P records pin mapping (ref, pin_number, pin_name)
    m = re.match(r'%TO\.P,([^,]*),([^,*]*)(?:,([^*]*))?\*%', s)
    if m:
        pin_mappings.append({
            'ref': m.group(1),
            'pin': m.group(2),
            'pin_name': m.group(3) or '',
            'net': current_net or '',
        })
        continue

    # TD clears all object attributes
    if s == '%TD*%':
        current_component = None
        current_net = None
        continue

    # On flash (D03), count pad for current component
    if 'D03' in s and current_component and current_component in components:
        components[current_component]['pads'] += 1
```

**Important state management rules:**
- `%TO.C,R1*%` sets component context — all subsequent features belong to R1
- `%TO.N,GND*%` sets net context — often changes within the same component
- `%TO.P,R1,1,PAD*%` records a pin mapping — pin 1 of R1 is named "PAD"
- `%TD*%` clears ALL TO attributes — resets component, net, and pin
- The same component may appear multiple times (e.g., different pads on different draw passes)
- TO attributes appear on **copper layers only** — mask/paste/silk layers don't have them

**KiCad 5 has no TO attributes.** Component and net mapping requires the `.kicad_pcb` source file.

### Component Side Detection

Components that appear only on B.Cu (back copper) TO.C attributes but not F.Cu are back-side components. Those appearing on F.Cu are front-side. Through-hole components appear on both layers (front pad + back pad).

```python
front_components = set()
back_components = set()

for gerber in parsed_gerbers:
    layer = gerber['layer_type']
    to_components = gerber.get('x2_objects', {}).get('component_refs', [])
    if layer == 'F.Cu':
        front_components.update(to_components)
    elif layer == 'B.Cu':
        back_components.update(to_components)

back_only = back_components - front_components  # True back-side SMD
```

---

## Excellon Drill Parsing

Drill files have a header (tool definitions) and body (drill hits). How to read a coordinate is declared in the header, not by the KiCad version.

### Step 1: Read Units, Zero Suppression and Precision

```python
units_mm = True              # METRIC unless the header says INCH
zeros = None                 # 'TZ', 'LZ', or None (decimal or keep zeros)
int_digits = dec_digits = None

for line in lines:
    s = line.strip()
    m = re.match(r'(METRIC|INCH)(?:,(LZ|TZ))?', s)
    if m:
        units_mm = m.group(1) == 'METRIC'
        zeros = m.group(2)
    m = re.match(r';\s*FORMAT=\{(\d+):(\d+)/', s)
    if m:
        int_digits, dec_digits = int(m.group(1)), int(m.group(2))
    if s == '%':
        break                # end of header
if int_digits is None:       # minimal header: KiCad's precision
    int_digits, dec_digits = (3, 3) if units_mm else (2, 4)
```

### Step 2: Parse Tool Definitions

Tools are defined in the header section (before `%` end-of-header marker):

```python
tools = {}
pending_aper_function = None

for line in lines:
    s = line.strip()

    # Per-tool TA function (KiCad 6+ only)
    ta_match = re.match(r';\s*#@!\s*TA\.AperFunction,(.*)', s)
    if ta_match:
        pending_aper_function = ta_match.group(1).strip()
        continue

    # Tool definition: T1C0.300 or T01C0.800000
    m = re.match(r'T(\d+)C([\d.]+)', s)
    if m:
        tool_num = int(m.group(1))
        diameter = float(m.group(2))
        if not units_mm:
            diameter *= 25.4  # Convert inches to mm
        tools[tool_num] = {
            'diameter_mm': diameter,
            'function': pending_aper_function,  # None for KiCad 5
            'hits': [],
        }
        pending_aper_function = None
```

### Step 3: Parse Drill Hits

```python
def to_mm(text):
    if '.' in text:
        value = float(text)
    else:
        sign = -1 if text.startswith('-') else 1
        digits = text.lstrip('+-')
        if zeros == 'LZ':    # trailing zeros omitted: digits are left-aligned
            digits = digits.ljust(int_digits + dec_digits, '0')
        value = sign * int(digits) / 10 ** dec_digits
    return value if units_mm else value * 25.4

current_tool = None

for line in lines:
    s = line.strip()

    # Tool select: T1 or T01
    m = re.match(r'^T(\d+)$', s)
    if m:
        current_tool = int(m.group(1))
        continue

    # Drill hit coordinate
    m = re.match(r'X(-?[\d.]+)Y(-?[\d.]+)', s)
    if m and current_tool:
        tools[current_tool]['hits'].append((to_mm(m.group(1)), to_mm(m.group(2))))
```

### Units and Precision Come from the Header

Every KiCad version can write mm or inch in any zeros format, so neither the KiCad version nor the size of the numbers tells you how to read a coordinate. Read the units line (`METRIC`/`INCH`, with `,TZ` or `,LZ`) and the `; FORMAT={integer:decimal/...}` comment as in Step 1. A decimal point means the value is already in the file's units. KiCad negates Y (relative to the drill/place origin when that option is used) unless the file was exported with mirror-Y. `gerber-parsing.md` "Coordinate Format" shows one hole in every format.

### Drill Classification

**With TA.AperFunction (KiCad 6+):**
- `Plated,PTH,ViaDrill` — via
- `Plated,PTH,ComponentDrill` — through-hole component pad
- `NonPlated,NPTH,BoardEdge` — board cutout or slot

**Without TA.AperFunction (KiCad 5) — use heuristics:**

| Diameter | Likely function |
|----------|----------------|
| <= 0.45mm | Via drill |
| 0.45 - 1.3mm | Component hole (THT pads) |
| > 1.3mm | Mounting hole or connector |
| NPTH file | All holes are mounting/mechanical |

**Layer span** from `TF.FileFunction`:
- `Plated,1,2,PTH` — 2-layer board, holes span layers 1-2
- `Plated,1,4,PTH` — 4-layer board, through-holes span all layers

---

## Layer Identification

### From X2 FileFunction (Preferred)

Parse `TF.FileFunction` from file attributes (works for both KiCad 5 and 6+):

```python
file_function = x2_attrs.get('FileFunction', '').lower()

if 'copper' in file_function:
    if 'top' in file_function:
        layer = 'F.Cu'
    elif 'bot' in file_function:
        layer = 'B.Cu'
    else:
        # Inner copper: "copper,l2,inr" → In1.Cu
        m = re.search(r'copper,l(\d+),inr', file_function)
        if m:
            abs_pos = int(m.group(1))
            inner_idx = abs_pos - 1  # L2→In1, L3→In2
            layer = f'In{inner_idx}.Cu'
```

**Inner layer naming pitfall:** X2 FileFunction uses absolute copper position (`L2` = second copper layer from top), but KiCad names inner layers starting from `In1.Cu`. For a 4-layer board: L1=F.Cu, **L2=In1.Cu**, **L3=In2.Cu**, L4=B.Cu. Subtract 1 from the absolute position to get the KiCad inner layer index.

### From Filename Patterns (Fallback)

When X2 attributes are missing or unparseable:

```python
name = filename.lower()

# Check inner layers first (avoid false positive on "in" substring)
m = re.search(r'in(\d+)[_.]cu', name)
if m:
    layer = f'In{m.group(1)}.Cu'

# Outer layers and non-copper
patterns = {
    'f_cu': 'F.Cu', 'f.cu': 'F.Cu',
    'b_cu': 'B.Cu', 'b.cu': 'B.Cu',
    'f_mask': 'F.Mask', 'b_mask': 'B.Mask',
    'f_paste': 'F.Paste', 'b_paste': 'B.Paste',
    'f_silkscreen': 'F.SilkS', 'f_silks': 'F.SilkS',
    'b_silkscreen': 'B.SilkS', 'b_silks': 'B.SilkS',
    'edge_cuts': 'Edge.Cuts',
}
```

**KiCad version from filenames:** `_SilkS` suffix = KiCad 5, `_Silkscreen` suffix = KiCad 6+.

### Protel Extension Mapping

Some fabs prefer Protel-style extensions:

| Extension | Layer |
|-----------|-------|
| `.GTL` | F.Cu |
| `.GBL` | B.Cu |
| `.G1`-`.G4` | Inner layers |
| `.GTS` | F.Mask |
| `.GBS` | B.Mask |
| `.GTP` | F.Paste |
| `.GBP` | B.Paste |
| `.GTO` | F.SilkS |
| `.GBO` | B.SilkS |
| `.GKO` / `.GM1` | Edge.Cuts |

---

## Gerber Job File (.gbrjob)

**KiCad 6+ only.** JSON format with board metadata. Parse before individual gerbers — it's the most reliable source for board dimensions, layer count, and design rules.

```python
import json

with open(gbrjob_path) as f:
    job = json.load(f)

specs = job.get('GeneralSpecs', {})
size = specs.get('Size', {})
board_width = size.get('X', 0)   # mm
board_height = size.get('Y', 0)  # mm
layer_count = specs.get('LayerNumber', 0)
thickness = specs.get('BoardThickness', 0)  # mm

# Design rules
for rule in job.get('DesignRules', []):
    min_trace = rule.get('MinLineWidth', 0)     # mm
    min_clearance = rule.get('PadToPad', 0)      # mm

# Expected files list
for f_attr in job.get('FilesAttributes', []):
    path = f_attr.get('Path', '')
    function = f_attr.get('FileFunction', '')
    polarity = f_attr.get('FilePolarity', '')

# Stackup
for layer in job.get('MaterialStackup', []):
    layer_type = layer.get('Type', '')      # "Copper" or "Dielectric"
    thickness = layer.get('Thickness', 0)   # mm (0.035 = 1oz copper)
    material = layer.get('Material', '')    # "FR4", etc.
```

**When .gbrjob is absent (KiCad 5):**
- Board dimensions: compute from Edge.Cuts gerber coordinate bounding box
- Layer count: count inner copper gerber files + 2 (F.Cu + B.Cu), or check drill `TF.FileFunction` layer span
- Design rules: not available from gerber files; check `.kicad_pro` source

---

## Cross-Reference with KiCad Source

### What Can Be Verified from Gerbers Alone

| Check | KiCad 5 | KiCad 6+ |
|-------|---------|----------|
| Board dimensions | Edge.Cuts extents | .gbrjob or Edge.Cuts |
| Layer count | Inner copper file count + drill span | .gbrjob or same |
| Layer completeness | Filename matching | .gbrjob expected list |
| Drill sizes | Tool definitions | Same + TA classification |
| Trace widths | Aperture dimensions (heuristic) | TA.AperFunction Conductor |
| Component list | Not available | TO.C attributes |
| Net list | Not available | TO.N attributes |
| Pin-to-net map | Not available | TO.P + TO.N attributes |
| Pad count | Flash count (heuristic) | TA.AperFunction classification |

### Cross-Reference Against PCB Analyzer

When both gerber and PCB analysis outputs are available:

1. **Component count**: Gerber `component_analysis.total_unique` vs PCB footprint count. Difference = non-electrical footprints (logos, mounting holes without copper)
2. **Net count**: Gerber `net_analysis.total_unique` vs PCB net count. Should match closely (gerber may miss nets that are zone-only with no pads/traces)
3. **Via count**: Gerber drill `vias.count` vs PCB via count
4. **Trace widths**: Gerber `trace_widths.unique_widths_mm` vs PCB track width distribution
5. **Board dimensions**: Gerber `board_dimensions` vs PCB Edge.Cuts extents
6. **THT vs SMD ratio**: Gerber `pad_summary.smd_ratio` vs PCB component `attr` counts

### Cross-Reference Against Schematic Analyzer

1. **Component list**: Gerber component refs (from TO.C) should be a subset of schematic BOM. Missing = DNP components or power symbols (expected). Extra = fabrication-only components
2. **Net names**: Named nets from gerber TO.N should match schematic net names. Unnamed gerber nets (`Net-(...)`) are auto-generated and may differ
3. **Pin count per component**: Gerber pad count should match schematic pin count for each reference designator

---

## Validation Methodology

### Quick Sanity Checks

1. **File count**: Typical 2-layer board = 9 gerbers + 2 drills + 1 gbrjob. 4-layer = 11 gerbers + 2 drills + 1 gbrjob
2. **Coordinate alignment**: All `TF.SameCoordinates` values should be `Original`
3. **Date consistency**: All `TF.CreationDate` values should match — different dates = risk of misaligned files
4. **Software consistency**: All `TF.GenerationSoftware` should match
5. **Solder mask polarity**: Must be `Negative` (`TF.FilePolarity,Negative`)

### Layer Consistency Checks

- **Paste <= Mask**: F.Paste flash count should be <= F.Mask flash count (no paste on vias)
- **Empty B.Paste**: Correct for single-side assembly
- **B.Cu flashes ~ via count**: Back copper pad flashes should roughly equal PTH via drill count (plus any back-side SMD)
- **Copper balance**: F.Cu and B.Cu draw counts within ~10x of each other (extreme imbalance = potential warping)
- **Edge.Cuts non-empty**: Must have draws (board outline)

### Drill Verification

- **PTH minimum**: >= 0.2mm (JLCPCB standard)
- **NPTH minimum**: >= 0.5mm (JLCPCB standard)
- **Via count cross-check**: Drill via count should match B.Cu via pad flash count (when TA.AperFunction is available)
- **Layer span**: Drill `TF.FileFunction` span should match copper layer count (e.g., `Plated,1,4,PTH` for 4-layer)

### Known Edge Cases

- **KiCad 5 mask/paste uses regions**: D03 flash count may be 0 on mask/paste layers — count G36/G37 region pairs instead
- **Large B.Mask file size**: Normal when back has ground plane — mask must define tenting pattern over entire zone fill
- **Negative Y in drills**: KiCad writes drill Y negated (board Y 100 mm is `Y-100`, measured from the drill/place origin when that option is used) unless the file was exported with mirror-Y
- **Non-KiCad gerbers**: May lack X2 attributes entirely; rely on filename patterns for layer identification
- **Merged drill files**: Some workflows produce a single drill file with both PTH and NPTH — check `TF.FileFunction` for `MixedPlating`
- **Protel extensions**: Some fabs require `.GTL`/`.GBL` extensions instead of KiCad's `-F_Cu.gbr` naming
- **Inner layer L2 != In2.Cu**: X2 FileFunction uses absolute position (L2 = second physical copper), KiCad uses inner-relative naming (In1.Cu = first inner copper). L2 maps to In1.Cu, L3 maps to In2.Cu
