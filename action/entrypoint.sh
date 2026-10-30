#!/bin/bash
# kicad-happy GitHub Action entrypoint
# Orchestrates: detect files → run analyzers → format report → set outputs
set -euo pipefail

SCRIPTS="$ACTION_PATH/skills/kicad/scripts"
SPICE_SCRIPTS="$ACTION_PATH/skills/spice/scripts"
OUTDIR=$(mktemp -d)

# ---------------------------------------------------------------------------
# Auto-detect KiCad files if not specified
# ---------------------------------------------------------------------------

SCHEMATIC="${INPUT_SCHEMATIC:-}"
PCB="${INPUT_PCB:-}"

# Deterministic project detection: exactly one project auto-selects,
# otherwise fail loudly listing candidates (KH-369). See detect_project.sh.
. "$ACTION_PATH/action/detect_project.sh"
# kh_extract_base / kh_base_path for the diff-base re-run.
. "$ACTION_PATH/action/diff_base.sh"

echo "::group::File Detection"
echo "Schematic: ${SCHEMATIC:-not found}"
echo "PCB: ${PCB:-not found}"

# Discover project config (.kicad-happy.json)
CONFIG_PATH=""
if [ -n "$SCHEMATIC" ]; then
    SEARCH_DIR=$(dirname "$SCHEMATIC")
elif [ -n "$PCB" ]; then
    SEARCH_DIR=$(dirname "$PCB")
else
    SEARCH_DIR="."
fi
# Walk upward to find .kicad-happy.json
_D="$SEARCH_DIR"
for _ in $(seq 1 10); do
    if [ -f "$_D/.kicad-happy.json" ]; then
        CONFIG_PATH="$_D/.kicad-happy.json"
        break
    fi
    _PARENT=$(dirname "$_D")
    [ "$_PARENT" = "$_D" ] && break
    _D="$_PARENT"
done
if [ -n "$CONFIG_PATH" ]; then
    echo "Config: $CONFIG_PATH"
else
    echo "Config: none found (using defaults)"
fi
echo "::endgroup::"

if [ -z "$SCHEMATIC" ] && [ -z "$PCB" ]; then
    echo "::warning::No KiCad files found in repository"
    echo "findings-count=0" >> "$GITHUB_OUTPUT"
    echo "has-critical=false" >> "$GITHUB_OUTPUT"
    exit 0
fi

# ---------------------------------------------------------------------------
# Detect and optionally download datasheets
# ---------------------------------------------------------------------------

DS_DIR="${INPUT_DATASHEETS_DIR:-}"
if [ -z "$DS_DIR" ] && [ -n "$SCHEMATIC" ]; then
    SCH_DIR=$(dirname "$SCHEMATIC")
    # Check common datasheet locations
    for candidate in "$SCH_DIR/datasheets" "$SCH_DIR/docs" "$SCH_DIR/documentation" "$SCH_DIR/../datasheets"; do
        if [ -d "$candidate" ]; then
            DS_DIR="$candidate"
            break
        fi
    done
fi

echo "::group::Datasheets"
if [ -n "$DS_DIR" ] && [ -d "$DS_DIR" ]; then
    PDF_COUNT=$(find "$DS_DIR" -name "*.pdf" -type f 2>/dev/null | wc -l)
    echo "Found datasheets directory: $DS_DIR ($PDF_COUNT PDFs)"
    if [ -f "$DS_DIR/manifest.json" ]; then
        echo "Datasheet manifest (manifest.json) present"
    elif [ -f "$DS_DIR/index.json" ]; then
        echo "Datasheet manifest (legacy index.json) present"
    fi
    if [ -d "$DS_DIR/extracted" ]; then
        EXTRACT_COUNT=$(find "$DS_DIR/extracted" -name "*.json" \
            -not -name "manifest.json" -not -name "index.json" \
            -type f 2>/dev/null | wc -l)
        echo "Pre-extracted specs: $EXTRACT_COUNT components"
    fi
else
    echo "No datasheets directory found"
fi

# Download missing datasheets from available distributor APIs
# Each sync script shares the same datasheets/ directory and skips already-downloaded files
if [ -n "$SCHEMATIC" ]; then
    DOWNLOADED=false

    # DigiKey (best source — direct PDF URLs)
    if [ -n "$DIGIKEY_CLIENT_ID" ] && [ -n "$DIGIKEY_CLIENT_SECRET" ]; then
        DK_SCRIPT="$ACTION_PATH/skills/digikey/scripts/sync_datasheets_digikey.py"
        if [ -f "$DK_SCRIPT" ]; then
            echo "Downloading datasheets from DigiKey..."
            python3 "$DK_SCRIPT" "$SCHEMATIC" 2>&1 | tail -5 || echo "::notice::DigiKey download had some failures (non-blocking)"
            DOWNLOADED=true
        fi
    fi

    # LCSC (no auth needed — free community API)
    LCSC_SCRIPT="$ACTION_PATH/skills/lcsc/scripts/sync_datasheets_lcsc.py"
    if [ -f "$LCSC_SCRIPT" ]; then
        echo "Downloading datasheets from LCSC..."
        python3 "$LCSC_SCRIPT" "$SCHEMATIC" 2>&1 | tail -3 || echo "::notice::LCSC download had some failures (non-blocking)"
        DOWNLOADED=true
    fi

    # element14/Newark/Farnell (reliable, no bot protection)
    if [ -n "$ELEMENT14_API_KEY" ]; then
        E14_SCRIPT="$ACTION_PATH/skills/element14/scripts/sync_datasheets_element14.py"
        if [ -f "$E14_SCRIPT" ]; then
            echo "Downloading datasheets from element14..."
            python3 "$E14_SCRIPT" "$SCHEMATIC" 2>&1 | tail -3 || echo "::notice::element14 download had some failures (non-blocking)"
            DOWNLOADED=true
        fi
    fi

    # Mouser (last resort — often blocks downloads)
    if [ -n "$MOUSER_SEARCH_API_KEY" ]; then
        MO_SCRIPT="$ACTION_PATH/skills/mouser/scripts/sync_datasheets_mouser.py"
        if [ -f "$MO_SCRIPT" ]; then
            echo "Downloading datasheets from Mouser..."
            python3 "$MO_SCRIPT" "$SCHEMATIC" 2>&1 | tail -3 || echo "::notice::Mouser download had some failures (non-blocking)"
            DOWNLOADED=true
        fi
    fi

    # Update DS_DIR after downloads
    if [ "$DOWNLOADED" = true ]; then
        SCH_DIR=$(dirname "$SCHEMATIC")
        if [ -d "$SCH_DIR/datasheets" ]; then
            DS_DIR="$SCH_DIR/datasheets"
            PDF_COUNT=$(find "$DS_DIR" -name "*.pdf" -type f 2>/dev/null | wc -l)
            echo "After download: $PDF_COUNT PDFs in $DS_DIR"
        fi
    fi
fi
echo "::endgroup::"

# ---------------------------------------------------------------------------
# Run schematic analysis
# ---------------------------------------------------------------------------

SCH_JSON=""
if [ -n "$SCHEMATIC" ] && [ -f "$SCHEMATIC" ]; then
    echo "::group::Schematic Analysis"
    SCH_JSON="$OUTDIR/schematic.json"
    echo "Analyzing: $SCHEMATIC"
    SCH_CMD=("$SCRIPTS/analyze_schematic.py" "$SCHEMATIC" -o "$SCH_JSON")
    [ -n "$CONFIG_PATH" ] && SCH_CMD+=(--config "$CONFIG_PATH")
    if python3 "${SCH_CMD[@]}" 2>"$OUTDIR/schematic.err"; then
        echo "schematic-json=$SCH_JSON" >> "$GITHUB_OUTPUT"
        COMP_COUNT=$(python3 -c "import json; d=json.load(open('$SCH_JSON')); print(d.get('statistics',{}).get('total_components',0))" 2>/dev/null || echo "?")
        NET_COUNT=$(python3 -c "import json; d=json.load(open('$SCH_JSON')); print(d.get('statistics',{}).get('total_nets',0))" 2>/dev/null || echo "?")
        echo "Components: $COMP_COUNT, Nets: $NET_COUNT"
    else
        echo "::error::Schematic analysis failed"
        cat "$OUTDIR/schematic.err" >&2 || true
        SCH_JSON=""
    fi
    echo "::endgroup::"
fi

# ---------------------------------------------------------------------------
# Run PCB analysis
# ---------------------------------------------------------------------------

PCB_JSON=""
if [ -n "$PCB" ] && [ -f "$PCB" ]; then
    echo "::group::PCB Analysis"
    PCB_JSON="$OUTDIR/pcb.json"
    echo "Analyzing: $PCB"
    PCB_CMD=("$SCRIPTS/analyze_pcb.py" "$PCB" -o "$PCB_JSON")
    [ -n "$CONFIG_PATH" ] && PCB_CMD+=(--config "$CONFIG_PATH")
    if python3 "${PCB_CMD[@]}" 2>"$OUTDIR/pcb.err"; then
        echo "pcb-json=$PCB_JSON" >> "$GITHUB_OUTPUT"
    else
        echo "::warning::PCB analysis failed"
        cat "$OUTDIR/pcb.err" >&2 || true
        PCB_JSON=""
    fi
    echo "::endgroup::"
fi

# ---------------------------------------------------------------------------
# Run SPICE simulation (optional, best-effort)
# ---------------------------------------------------------------------------

SPICE_JSON=""
if [ "${INPUT_SPICE:-true}" = "true" ] && [ -n "$SCH_JSON" ]; then
    if command -v ngspice &>/dev/null; then
        echo "::group::SPICE Simulation"
        SPICE_JSON="$OUTDIR/spice.json"
        if python3 "$SPICE_SCRIPTS/simulate_subcircuits.py" "$SCH_JSON" --compact -o "$SPICE_JSON" 2>"$OUTDIR/spice.err"; then
            SUMMARY=$(python3 -c "import json; d=json.load(open('$SPICE_JSON')); s=d.get('summary',{}); print(f\"{s.get('pass',0)} pass, {s.get('warn',0)} warn, {s.get('fail',0)} fail, {s.get('skip',0)} skip, {s.get('info',0)} info\")" 2>/dev/null || echo "?")
            echo "SPICE: $SUMMARY"
        else
            echo "::notice::SPICE simulation failed (non-blocking)"
            SPICE_JSON=""
        fi
        echo "::endgroup::"
    fi
fi

# ---------------------------------------------------------------------------
# Run EMC analysis (optional, best-effort)
# ---------------------------------------------------------------------------

EMC_JSON=""
if [ -n "$SCH_JSON" ] || [ -n "$PCB_JSON" ]; then
    echo "::group::EMC Analysis"
    EMC_JSON="$OUTDIR/emc.json"
    EMC_ARGS=()
    [ -n "$SCH_JSON" ] && [ -f "$SCH_JSON" ] && EMC_ARGS+=(--schematic "$SCH_JSON")
    [ -n "$PCB_JSON" ] && [ -f "$PCB_JSON" ] && EMC_ARGS+=(--pcb "$PCB_JSON")
    EMC_ARGS+=(--output "$EMC_JSON")
    [ -n "$CONFIG_PATH" ] && EMC_ARGS+=(--config "$CONFIG_PATH")
    if command -v ngspice &>/dev/null; then
        EMC_ARGS+=(--spice-enhanced)
    fi
    if python3 "$ACTION_PATH/skills/emc/scripts/analyze_emc.py" "${EMC_ARGS[@]}" 2>"$OUTDIR/emc.err"; then
        SUMMARY=$(python3 -c "import json; d=json.load(open('$EMC_JSON')); s=d.get('summary',{}); bs=s.get('by_severity',{}); print(f\"score {s.get('emc_risk_score',0)}/100, {bs.get('error',s.get('critical',0))} error, {bs.get('warning',s.get('high',0))} warning, {bs.get('info',s.get('medium',0))} info\")" 2>/dev/null || echo "?")
        echo "EMC: $SUMMARY"
    else
        # EMC exits nonzero when blocking findings detected. Distinguish that
        # (valid JSON, surface to report) from a true crash (no/malformed JSON,
        # clear and warn). Audit B2 — without this, the Action silently drops
        # exactly the runs that found release-blocking issues.
        if [ -f "$EMC_JSON" ] && python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$EMC_JSON" >/dev/null 2>&1; then
            SUMMARY=$(python3 -c "import json; d=json.load(open('$EMC_JSON')); s=d.get('summary',{}); bs=s.get('by_severity',{}); print(f\"score {s.get('emc_risk_score',0)}/100, {bs.get('error',s.get('critical',0))} error, {bs.get('warning',s.get('high',0))} warning, {bs.get('info',s.get('medium',0))} info\")" 2>/dev/null || echo "?")
            echo "::notice::EMC analyzer reported blocking findings (exit nonzero, JSON valid)"
            echo "EMC: $SUMMARY"
        else
            echo "::notice::EMC analysis failed (non-blocking)"
            EMC_JSON=""
        fi
    fi
    echo "::endgroup::"
fi

# ---------------------------------------------------------------------------
# Run thermal analysis (optional, requires both schematic and PCB)
# ---------------------------------------------------------------------------

THERMAL_JSON=""
if [ -n "$SCH_JSON" ] && [ -n "$PCB_JSON" ]; then
    echo "::group::Thermal Analysis"
    THERMAL_JSON="$OUTDIR/thermal.json"
    THERMAL_ARGS=(--schematic "$SCH_JSON" --pcb "$PCB_JSON" --output "$THERMAL_JSON")
    [ -n "$CONFIG_PATH" ] && THERMAL_ARGS+=(--config "$CONFIG_PATH")
    if [ -n "$DS_DIR" ] && [ -d "$DS_DIR/extracted" ]; then
        THERMAL_ARGS+=(--datasheets "$DS_DIR/extracted")
    fi
    if python3 "$SCRIPTS/analyze_thermal.py" "${THERMAL_ARGS[@]}" 2>"$OUTDIR/thermal.err"; then
        SUMMARY=$(python3 -c "import json; d=json.load(open('$THERMAL_JSON')); s=d.get('summary',{}); bs=s.get('by_severity',{}); print(f\"score {s.get('thermal_score',0)}/100, {bs.get('error',s.get('critical',0))} error, {bs.get('warning',s.get('high',0))} warning, {s.get('components_analyzed',0)} components\")" 2>/dev/null || echo "?")
        echo "Thermal: $SUMMARY"
    else
        # Mirror the EMC block above: preserve valid JSON on nonzero exit
        # because thermal can exit nonzero on blocking findings. Only clear
        # when the file is missing or malformed.
        if [ -f "$THERMAL_JSON" ] && python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$THERMAL_JSON" >/dev/null 2>&1; then
            SUMMARY=$(python3 -c "import json; d=json.load(open('$THERMAL_JSON')); s=d.get('summary',{}); bs=s.get('by_severity',{}); print(f\"score {s.get('thermal_score',0)}/100, {bs.get('error',s.get('critical',0))} error, {bs.get('warning',s.get('high',0))} warning, {s.get('components_analyzed',0)} components\")" 2>/dev/null || echo "?")
            echo "::notice::Thermal analyzer reported blocking findings (exit nonzero, JSON valid)"
            echo "Thermal: $SUMMARY"
        else
            echo "::notice::Thermal analysis failed (non-blocking)"
            THERMAL_JSON=""
        fi
    fi
    echo "::endgroup::"
fi

# ---------------------------------------------------------------------------
# Diff against base branch (PR only, opt-in)
# ---------------------------------------------------------------------------

DIFF_JSON=""    # first diff produced (the harness driver reads it); DIFF_JSONS carries all
DIFF_JSONS=()
if [ "${INPUT_DIFF_BASE:-false}" = "true" ] && [ -n "${GITHUB_BASE_REF:-}" ]; then
    echo "::group::Diff Analysis"
    # Save HEAD outputs
    mkdir -p "$OUTDIR/head"
    [ -n "$SCH_JSON" ] && [ -f "$SCH_JSON" ] && cp "$SCH_JSON" "$OUTDIR/head/schematic.json"
    [ -n "$PCB_JSON" ] && [ -f "$PCB_JSON" ] && cp "$PCB_JSON" "$OUTDIR/head/pcb.json"

    # Fetch the base branch; its KiCad files are extracted below, the working tree is untouched
    mkdir -p "$OUTDIR/base"
    BASE_OK=true
    git fetch origin "$GITHUB_BASE_REF" --depth=1 2>/dev/null || BASE_OK=false
    BASE_TREE="$OUTDIR/base-tree"
    if [ "$BASE_OK" = "true" ]; then
        # Extract the base project (sub-sheets, PCB, config) into a separate tree
        kh_extract_base FETCH_HEAD "$BASE_TREE" "$SCHEMATIC" "$PCB" "${CONFIG_PATH:-}" 2>/dev/null || BASE_OK=false
    fi

    if [ "$BASE_OK" = "true" ]; then
        # Re-run analyzers on base versions, with the base config as head uses its own
        BASE_SCH=$(kh_base_path "$BASE_TREE" "$SCHEMATIC")
        BASE_PCB=$(kh_base_path "$BASE_TREE" "$PCB")
        BASE_CFG=$(kh_base_path "$BASE_TREE" "${CONFIG_PATH:-}")
        BASE_CFG_ARGS=()
        [ -n "$BASE_CFG" ] && [ -f "$BASE_CFG" ] && BASE_CFG_ARGS=(--config "$BASE_CFG")
        if [ -n "$BASE_SCH" ] && [ -f "$BASE_SCH" ]; then
            python3 "$SCRIPTS/analyze_schematic.py" "$BASE_SCH" -o "$OUTDIR/base/schematic.json" \
                ${BASE_CFG_ARGS[@]+"${BASE_CFG_ARGS[@]}"} 2>/dev/null || true
        fi
        if [ -n "$BASE_PCB" ] && [ -f "$BASE_PCB" ]; then
            python3 "$SCRIPTS/analyze_pcb.py" "$BASE_PCB" -o "$OUTDIR/base/pcb.json" \
                ${BASE_CFG_ARGS[@]+"${BASE_CFG_ARGS[@]}"} 2>/dev/null || true
        fi

        # Diff each analyzer pair that exists on both sides; the comment carries every diff
        # (base EMC and SPICE are never re-run, so only schematic and PCB pair up)
        for dtype in schematic pcb; do
            if [ -f "$OUTDIR/base/$dtype.json" ] && [ -f "$OUTDIR/head/$dtype.json" ]; then
                python3 "$SCRIPTS/diff_analysis.py" \
                    "$OUTDIR/base/$dtype.json" "$OUTDIR/head/$dtype.json" \
                    -o "$OUTDIR/diff_$dtype.json" 2>/dev/null || true
                if [ -f "$OUTDIR/diff_$dtype.json" ]; then
                    DIFF_JSONS+=("$OUTDIR/diff_$dtype.json")
                    [ -n "$DIFF_JSON" ] || DIFF_JSON="$OUTDIR/diff_$dtype.json"
                fi
            fi
        done
        echo "Diff analysis complete"
    else
        echo "::notice::Could not fetch base branch for diff (non-blocking)"
    fi
    echo "::endgroup::"
fi

# ---------------------------------------------------------------------------
# Format markdown report
# ---------------------------------------------------------------------------

echo "::group::Report Generation"
REPORT="$OUTDIR/report.md"
FULL_REPORT="$OUTDIR/full-report.md"
SUMMARY_JSON="$OUTDIR/summary.json"

ARGS=()
[ -n "$SCH_JSON" ] && [ -f "$SCH_JSON" ] && ARGS+=(--schematic "$SCH_JSON")
[ -n "$PCB_JSON" ] && [ -f "$PCB_JSON" ] && ARGS+=(--pcb "$PCB_JSON")
[ -n "$SPICE_JSON" ] && [ -f "$SPICE_JSON" ] && ARGS+=(--spice "$SPICE_JSON")
[ -n "$EMC_JSON" ] && [ -f "$EMC_JSON" ] && ARGS+=(--emc "$EMC_JSON")
for _diff in ${DIFF_JSONS[@]+"${DIFF_JSONS[@]}"}; do
    [ -f "$_diff" ] && ARGS+=(--diff "$_diff")
done
[ -n "$THERMAL_JSON" ] && [ -f "$THERMAL_JSON" ] && ARGS+=(--thermal "$THERMAL_JSON")
ARGS+=(--severity "${INPUT_SEVERITY:-all}")
ARGS+=(--derating-profile "${INPUT_DERATING_PROFILE:-commercial}")
ARGS+=(--output "$REPORT")
ARGS+=(--output-full "$FULL_REPORT")
ARGS+=(--output-summary "$SUMMARY_JSON")

# Build run URL for "Full report" link in PR comment
if [ -n "${GITHUB_SERVER_URL:-}" ] && [ -n "${GITHUB_REPOSITORY:-}" ] && [ -n "${GITHUB_RUN_ID:-}" ]; then
    ARGS+=(--run-url "${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}")
fi

python3 "$ACTION_PATH/action/format-report.py" "${ARGS[@]}"

echo "report-path=$REPORT" >> "$GITHUB_OUTPUT"
echo "REPORT_PATH=$REPORT" >> "$GITHUB_ENV"

# Write full report to GitHub step summary (visible on the Actions run page)
if [ -n "${GITHUB_STEP_SUMMARY:-}" ] && [ -f "$FULL_REPORT" ]; then
    cat "$FULL_REPORT" >> "$GITHUB_STEP_SUMMARY"
fi

# Set finding outputs
if [ -f "$SUMMARY_JSON" ]; then
    FINDINGS_COUNT=$(python3 -c "import json; print(json.load(open('$SUMMARY_JSON')).get('findings_count',0))")
    HAS_CRITICAL=$(python3 -c "import json; print(str(json.load(open('$SUMMARY_JSON')).get('has_critical',False)).lower())")
    VERIFIED_COUNT=$(python3 -c "import json; print(json.load(open('$SUMMARY_JSON')).get('verified_count',0))")
    echo "findings-count=$FINDINGS_COUNT" >> "$GITHUB_OUTPUT"
    echo "has-critical=$HAS_CRITICAL" >> "$GITHUB_OUTPUT"
else
    FINDINGS_COUNT=0
    HAS_CRITICAL=false
    VERIFIED_COUNT=0
    echo "findings-count=0" >> "$GITHUB_OUTPUT"
    echo "has-critical=false" >> "$GITHUB_OUTPUT"
fi

# Post commit status check (works on both push and PR events)
if [ -n "${GITHUB_TOKEN:-}" ] && [ -n "${GITHUB_REPOSITORY:-}" ] && [ -n "${GITHUB_SHA:-}" ]; then
    if [ "$HAS_CRITICAL" = "true" ]; then
        STATUS_STATE="failure"
        STATUS_DESC="$FINDINGS_COUNT finding(s), including critical issues"
    elif [ "$FINDINGS_COUNT" -gt 0 ] 2>/dev/null; then
        STATUS_STATE="success"
        STATUS_DESC="$FINDINGS_COUNT warning(s), $VERIFIED_COUNT verified"
    else
        STATUS_STATE="success"
        STATUS_DESC="No issues found, $VERIFIED_COUNT verified"
    fi

    # Build target URL (link to the Actions run page with full report)
    TARGET_URL=""
    if [ -n "${GITHUB_SERVER_URL:-}" ] && [ -n "${GITHUB_RUN_ID:-}" ]; then
        TARGET_URL="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"
    fi

    curl -s -X POST \
        -H "Authorization: token ${GITHUB_TOKEN}" \
        -H "Accept: application/vnd.github.v3+json" \
        "https://api.github.com/repos/${GITHUB_REPOSITORY}/statuses/${GITHUB_SHA}" \
        -d "{\"state\":\"${STATUS_STATE}\",\"description\":\"${STATUS_DESC}\",\"context\":\"kicad-happy\",\"target_url\":\"${TARGET_URL}\"}" \
        > /dev/null 2>&1 || echo "::notice::Could not post commit status (non-blocking)"
fi

echo "::endgroup::"
