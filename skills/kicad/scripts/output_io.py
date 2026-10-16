"""Output mechanics shared by the kicad-owned CLIs (v3 round 4, spec §5.2 / C1).

write_primary_run: the analysis-cache write path for a primary analyzer (schematic now;
pcb in round 5). Each CLI keeps its own --output / --analysis-dir precedence and calls
this only on the --analysis-dir branch. Lives beside analysis_cache (which depends on
diff_engine), so it is not part of the stdlib-only kicad_core package.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from analysis_cache import (GITIGNORE_CONTENT, MANIFEST_FILENAME, CANONICAL_OUTPUTS, _empty_manifest,
                            create_run, get_current_run, hash_source_file, overwrite_current, resolve_analysis_dir,
                            save_manifest, should_create_new_run)


def write_primary_run(analysis_dir_arg: str, output_text: str, *, analyzer: str, source_path: str,
                      script_name: str, track_in_git: bool = False) -> None:
    """Write one analyzer's canonical JSON into the analysis cache (new run or current overwrite)."""
    project_dir = str(Path(source_path).parent)
    analysis_dir = resolve_analysis_dir(analysis_dir_arg)

    # Find .kicad_pro for manifest
    pro_file = ""
    try:
        for f in os.listdir(project_dir):
            if f.endswith(".kicad_pro"):
                pro_file = f
                break
    except OSError:
        pass

    # Ensure the target directory exists with manifest
    os.makedirs(analysis_dir, exist_ok=True)
    manifest_path = os.path.join(analysis_dir, MANIFEST_FILENAME)
    if not os.path.isfile(manifest_path):
        manifest = _empty_manifest()
        manifest['project'] = pro_file
        save_manifest(analysis_dir, manifest)
    # Respect track_in_git config — skip .gitignore if user wants git tracking
    gitignore_path = os.path.join(analysis_dir, '.gitignore')
    if not track_in_git and not os.path.isfile(gitignore_path):
        with open(gitignore_path, 'w', encoding='utf-8') as f:
            f.write(GITIGNORE_CONTENT)

    source_hashes = {os.path.basename(source_path): hash_source_file(source_path)}

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_file = os.path.join(tmp_dir, CANONICAL_OUTPUTS.get(analyzer, f"{analyzer}.json"))
        Path(out_file).write_text(output_text, encoding='utf-8')

        if should_create_new_run(analysis_dir, tmp_dir):
            run_id = create_run(
                analysis_dir=analysis_dir,
                outputs_dir=tmp_dir,
                source_hashes=source_hashes,
                scripts={analyzer: f"{script_name} {os.path.basename(source_path)}"},
            )
            print(f"Analysis cached: {os.path.join(analysis_dir, run_id, os.path.basename(out_file))}", file=sys.stderr)
        else:
            overwrite_current(analysis_dir, tmp_dir, source_hashes=source_hashes)
            print(f"Analysis cache updated (current run)", file=sys.stderr)


def write_derived_output(analysis_dir_arg: str, output_text: str, *, analyzer: str) -> str:
    """Overwrite one derived analyzer's canonical JSON in the CURRENT run; return the path written.

    Derived analyzers (gerber, thermal, cross_analysis) never create a run and carry no source
    hashes; when nothing is tracked yet the file lands at the analysis-dir root (today's fallback).
    """
    analysis_dir = resolve_analysis_dir(analysis_dir_arg)
    filename = CANONICAL_OUTPUTS.get(analyzer, f"{analyzer}.json")
    with tempfile.TemporaryDirectory() as tmp_dir:
        Path(os.path.join(tmp_dir, filename)).write_text(output_text, encoding='utf-8')
        overwrite_current(analysis_dir, tmp_dir, source_hashes=None)
    current = get_current_run(analysis_dir)
    if current:
        return os.path.join(current[0], filename)
    return os.path.join(analysis_dir, filename)
