"""A placed symbol's instance list is read and indexed once per hierarchy walk, however many
sheet instances use its sheet file, and the indexed lookup picks the instance the linear
rule picks."""
import os, sys, tempfile, unittest
from collections import Counter
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import schematic.reader as reader  # noqa: E402
from kicad_core.instances import index_instances, resolve_indexed, _norm_path  # noqa: E402
from kicad_core.sexp import get_value  # noqa: E402
from schematic.pipeline import analyze_schematic  # noqa: E402
from tools.tests.test_sheet_parse_once import project, sheet, write  # noqa: E402
from tools.tests.test_top_level_sheets_kicad10 import resistor, sch, u  # noqa: E402


def counted_analysis(files):
    """analyze_schematic on *files*, counting inline_instances calls per symbol uuid."""
    counts = Counter()
    real = reader.inline_instances

    def counting(sym, *args, **kwargs):
        counts[get_value(sym, "uuid")] += 1
        return real(sym, *args, **kwargs)

    with tempfile.TemporaryDirectory() as tmp:
        path = write(files, tmp)
        with mock.patch.object(reader, "inline_instances", counting), \
                redirect_stderr(StringIO()):
            result = analyze_schematic(path)
    return result, counts


def old_linear(candidates, instance_path, project_name):
    want = _norm_path(instance_path)
    hit = None
    for cand in candidates:
        if _norm_path(cand.get("path") or "") == want:
            hit = cand
    if hit is not None or not candidates:
        return hit
    for cand in candidates:
        if cand.get("project") == project_name:
            return cand
    return candidates[0]


class InstanceListReadOnceTest(unittest.TestCase):
    def test_each_symbol_instance_list_is_read_once(self):
        result, counts = counted_analysis(project())
        self.assertEqual(len(result["sheets"]), 7)
        self.assertEqual(dict(counts), {u(311): 1, u(341): 1})

    def test_forty_instances_resolve_and_index_once(self):
        root_uuid = u(401)
        sheets = [u(410 + i) for i in range(40)]
        root = "".join(sheet(s, f"S{i}", "sub.kicad_sch", 100 + 30 * i, "IN")
                       for i, s in enumerate(sheets))
        sub = resistor(u(460), "R?", 50, [(f"/{root_uuid}/{s}", f"R{i + 1}")
                                           for i, s in enumerate(sheets)])
        sub += (f' (wire (pts (xy 50 46.19) (xy 60 46.19)) (uuid "{u(461)}"))'
                f' (hierarchical_label "IN" (shape input) (at 60 46.19 0) (uuid "{u(462)}"))')
        files = {"p.kicad_sch": sch(root_uuid, root), "sub.kicad_sch": sch(u(463), sub)}
        result, counts = counted_analysis(files)
        refs = [c["reference"] for c in result["components"] if c["type"] != "power_symbol"]
        self.assertEqual(refs, [f"R{i + 1}" for i in range(40)])
        self.assertEqual(dict(counts), {u(460): 1})


class IndexMatchesLinearRuleTest(unittest.TestCase):
    def cand(self, path, project, ref):
        return {"path": path, "project": project, "reference": ref, "unit": 1}

    def test_index_matches_linear_rule(self):
        cases = {
            "exact duplicates, last wins": (
                [self.cand("/a/b", "p", "R1"), self.cand("/a/c", "p", "R2"),
                 self.cand("/a/b", "q", "R3")], "/a/b", "p"),
            "trailing slash and case": (
                [self.cand("/A/B/", "p", "R1"), self.cand("/a/c", "p", "R2")], "/a/b", "p"),
            "no match, project candidate second": (
                [self.cand("/x", "zzz", "R11"), self.cand("/y", "proj", "R12"),
                 self.cand("/z", "proj", "R13")], "/a", "proj"),
            "no match, no project match": (
                [self.cand("/x", "zzz", "R11"), self.cand("/y", "proj", "R12")], "/a", "other"),
            "empty path candidate": (
                [self.cand("", "p", "R1"), self.cand(None, "p", "R2")], "", "p"),
            "empty": ([], "/a", "proj"),
        }
        for name, (cands, path, proj) in cases.items():
            with self.subTest(name):
                self.assertIs(resolve_indexed(index_instances(cands), path, proj),
                              old_linear(cands, path, proj))


if __name__ == "__main__":
    unittest.main()
