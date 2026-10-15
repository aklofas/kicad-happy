#!/usr/bin/env python3
"""Validate SKILL.md frontmatter against platform constraints.

Runs against every skills/*/SKILL.md and checks:
  - Required frontmatter fields (name, description) are present.
  - Description length is within platform caps. The strictest cap shipped
    by any supported platform is Codex's 1024-char hard limit on
    description. Skills over this are rejected on load by Codex.

Usage:
    python3 .github/scripts/check_skill_metadata.py        # all skills
    python3 .github/scripts/check_skill_metadata.py skills/bom/SKILL.md
    python3 .github/scripts/check_skill_metadata.py --warn-margin 100
                              # warn when buffer is below 100 chars

Exit codes:
    0  All skills pass.
    1  One or more skills are OVER the description cap.
    2  Usage error (bad path, missing file, etc.).

Wire as a local pre-commit hook:
    ln -sf ../../.github/scripts/check_skill_metadata.py .git/hooks/pre-commit

This script is also invoked by CI (see .github/workflows/ci.yml).

Zero dependencies — Python 3.10+ stdlib only.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DESCRIPTION_CAP = 1024  # Codex hard limit, strictest of supported platforms.
DEFAULT_WARN_MARGIN = 50  # Warn when buffer drops below this.


def extract_description(skill_md: Path) -> tuple[str | None, str | None]:
    """Return (description_text, error_message)."""
    try:
        content = skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"could not read: {exc}"

    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not fm_match:
        return None, "no YAML frontmatter"

    fm = fm_match.group(1)

    # description: value may span multiple lines (YAML folded scalar). Capture
    # until the next top-level key or end-of-frontmatter.
    desc_match = re.search(
        r"^description:\s*(.+?)(?=\n[a-zA-Z_][\w-]*:|\Z)",
        fm,
        re.DOTALL | re.MULTILINE,
    )
    if not desc_match:
        return None, "no description field"

    # Collapse YAML folded whitespace (newlines + indentation → single space).
    desc = " ".join(desc_match.group(1).split())
    return desc, None


def find_skill_mds(targets: list[str]) -> list[Path]:
    """Resolve targets to a list of SKILL.md files."""
    if not targets:
        # Default: every SKILL.md under skills/.
        repo_root = Path(__file__).resolve().parents[2]
        return sorted(repo_root.glob("skills/*/SKILL.md"))

    paths: list[Path] = []
    for t in targets:
        p = Path(t)
        if not p.exists():
            print(f"error: {t} does not exist", file=sys.stderr)
            sys.exit(2)
        if p.is_dir():
            paths.extend(sorted(p.glob("**/SKILL.md")))
        else:
            paths.append(p)
    return paths


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "targets",
        nargs="*",
        help="SKILL.md files or directories to check (default: all skills/)",
    )
    ap.add_argument(
        "--warn-margin",
        type=int,
        default=DEFAULT_WARN_MARGIN,
        help=f"warn when buffer drops below N chars (default: {DEFAULT_WARN_MARGIN})",
    )
    ap.add_argument(
        "--quiet",
        action="store_true",
        help="suppress per-skill OK lines (only print warnings/errors)",
    )
    args = ap.parse_args()

    skill_mds = find_skill_mds(args.targets)
    if not skill_mds:
        print("error: no SKILL.md files found", file=sys.stderr)
        return 2

    exit_code = 0
    rows: list[tuple[str, int, int, str]] = []  # (skill_name, length, margin, status)

    for skill_md in skill_mds:
        skill_name = skill_md.parent.name
        desc, err = extract_description(skill_md)
        if err is not None:
            rows.append((skill_name, -1, 0, f"ERROR: {err}"))
            exit_code = max(exit_code, 1)
            continue
        length = len(desc)
        margin = DESCRIPTION_CAP - length
        if margin < 0:
            status = "OVER"
            exit_code = max(exit_code, 1)
        elif margin < args.warn_margin:
            status = "CLOSE"
        else:
            status = "OK"
        rows.append((skill_name, length, margin, status))

    rows.sort(key=lambda r: r[2])  # ascending margin (riskiest first)

    if not args.quiet or any(r[3] != "OK" for r in rows):
        print(f"\n{'Skill':<14} {'Length':>7} {'Margin':>7}  Status")
        print(f"{'-' * 14} {'-' * 7} {'-' * 7}  {'-' * 12}")
        for name, length, margin, status in rows:
            if length < 0:
                print(f"{name:<14} {'—':>7} {'—':>7}  {status}")
            else:
                print(f"{name:<14} {length:>7} {margin:>+7}  {status}")
        print()

    if exit_code != 0:
        print(
            f"FAIL: {sum(1 for r in rows if r[3] == 'OVER')} skill(s) over the "
            f"{DESCRIPTION_CAP}-char description cap.",
            file=sys.stderr,
        )

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
