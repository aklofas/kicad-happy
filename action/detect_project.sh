# action/detect_project.sh
#
# Auto-detects SCHEMATIC and PCB when INPUT_SCHEMATIC / INPUT_PCB were
# not provided. Sourced by entrypoint.sh (not executed directly) so it
# shares the caller's SCHEMATIC/PCB variables and shell options
# (set -euo pipefail).
#
# Detection ladder (must stay deterministic, never silently
# pick an arbitrary project/child-sheet in a multi-project repo):
#   1. Explicit INPUT_SCHEMATIC (already in SCHEMATIC) wins as-is.
#   2. Exactly one .kicad_pro anywhere -> its sibling <stem>.kicad_sch.
#   3. Else exactly one .kicad_sch anywhere -> that file.
#   4. Else, if PCB was also not explicitly given: fail loudly, listing
#      every .kicad_sch candidate on stderr. If PCB WAS explicitly
#      given, don't fail — leave SCHEMATIC empty and let the caller
#      proceed PCB-only (a PCB-only invocation with zero/ambiguous
#      schematics is a legitimate, previously-working case; only note
#      it on stderr).
# PCB mirrors the same project-stem preference, falling back to the
# single .kicad_pcb next to the chosen schematic.

if [ -z "$SCHEMATIC" ]; then
    PRO_COUNT=$(find . -name "*.kicad_pro" -not -path "./.git/*" \
        -not -path "*/backup/*" -not -path "*/backups/*" 2>/dev/null | wc -l) || true
    if [ "$PRO_COUNT" -eq 1 ]; then
        PRO_FILE=$(find . -name "*.kicad_pro" -not -path "./.git/*" \
            -not -path "*/backup/*" -not -path "*/backups/*" 2>/dev/null) || true
        PRO_STEM="${PRO_FILE%.kicad_pro}"
        [ -f "$PRO_STEM.kicad_sch" ] && SCHEMATIC="$PRO_STEM.kicad_sch"
    fi
    if [ -z "$SCHEMATIC" ]; then
        # Fall back: exactly one schematic anywhere is unambiguous even
        # with zero (or an unmatched) .kicad_pro.
        SCH_COUNT=$(find . -name "*.kicad_sch" -not -path "./.git/*" -not -path "*/backup/*" \
            -not -path "*/backups/*" -not -name "_autosave-*" 2>/dev/null | wc -l) || true
        if [ "$SCH_COUNT" -eq 1 ]; then
            SCHEMATIC=$(find . -name "*.kicad_sch" -not -path "./.git/*" -not -path "*/backup/*" \
                -not -path "*/backups/*" -not -name "_autosave-*" 2>/dev/null) || true
        fi
    fi
    if [ -z "$SCHEMATIC" ]; then
        if [ -z "$PCB" ]; then
            echo "::error::Multiple (or zero) KiCad projects found; set the 'schematic' input explicitly. Candidates:" >&2
            find . -name "*.kicad_sch" -not -path "./.git/*" -not -path "*/backup/*" \
                -not -path "*/backups/*" -not -name "_autosave-*" >&2 2>/dev/null
            exit 1
        else
            echo "::notice::Could not auto-detect a unique schematic (none or multiple found); proceeding PCB-only. Set the 'schematic' input to include schematic analysis." >&2
        fi
    fi
fi

if [ -z "$PCB" ] && [ -n "$SCHEMATIC" ]; then
    if [ -n "${PRO_STEM:-}" ] && [ "$SCHEMATIC" = "$PRO_STEM.kicad_sch" ] && [ -f "$PRO_STEM.kicad_pcb" ]; then
        PCB="$PRO_STEM.kicad_pcb"
    else
        PCB_DIR=$(dirname "$SCHEMATIC")
        PCB=$(find "$PCB_DIR" -maxdepth 1 -name "*.kicad_pcb" -not -path "*/node_modules/*" 2>/dev/null | sort | head -1 || true)
    fi
fi
