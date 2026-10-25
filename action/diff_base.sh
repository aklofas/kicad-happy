# action/diff_base.sh
#
# Base-branch copy of the project for the `diff-base` re-run. Sourced by
# entrypoint.sh (not executed directly).
#
# kh_extract_base REF DEST SCHEMATIC PCB CONFIG
#   Extracts, as they are at REF, every .kicad_sch / .kicad_pro / .kicad_dru
#   under the schematic's directory (so hierarchical sub-sheets come from
#   the same commit as the root), the PCB and the project config, into
#   DEST/<repo-relative path>. Empty arguments and files absent at REF are
#   skipped. The working tree is not touched. Returns 1 when nothing was
#   extracted.
#
# kh_base_path DEST PATH
#   Prints where PATH lives inside DEST (empty PATH prints nothing).

kh_repo_rel() {
    python3 -c 'import os, sys; print(os.path.relpath(os.path.abspath(sys.argv[1]), sys.argv[2]))' \
        "$1" "$(git rev-parse --show-toplevel)"
}

kh_base_path() {
    [ -n "$2" ] || return 0
    printf '%s/%s\n' "$1" "$(kh_repo_rel "$2")"
}

kh_extract_base() {
    local ref="$1" dest="$2" sch="$3" pcb="$4" cfg="$5"
    local top rel files=()
    top=$(git rev-parse --show-toplevel)
    if [ -n "$sch" ]; then
        rel=$(dirname "$(kh_repo_rel "$sch")")
        while IFS= read -r f; do
            files+=("$f")
        done < <(git -C "$top" ls-tree -r --name-only "$ref" -- "$rel" \
                    | grep -E '\.(kicad_sch|kicad_pro|kicad_dru)$' || true)
    fi
    for f in "$pcb" "$cfg"; do
        [ -n "$f" ] || continue
        rel=$(kh_repo_rel "$f")
        git -C "$top" cat-file -e "$ref:$rel" 2>/dev/null && files+=("$rel")
    done
    [ "${#files[@]}" -gt 0 ] || return 1
    mkdir -p "$dest"
    git -C "$top" archive "$ref" -- "${files[@]}" | tar -x -C "$dest"
}
