"""Gerber discovery and credit: a comment is not an operation, a file that is not a drill earns no
drill credit, companion files from other tools are not job, drill or archive inputs, and a damaged
job file is reported."""
import json, os, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from test_gerber_degraded_input import _diags, _four_layer, _gbr, _main  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
import analyze_gerbers as ag  # noqa: E402


def _write(d, name, text):
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        f.write(text)


class CommentTest(unittest.TestCase):
    def test_comment_holding_an_operation_code_is_not_copper(self):
        with tempfile.TemporaryDirectory() as d:
            _four_layer(d)
            _write(d, "b-F_Cu.gtl", "G04 draws use D01 and flashes D03*\n")
            env = _main(d)
        self.assertNotIn("F.Cu", env["completeness"]["found_layers"])
        self.assertFalse(env["completeness"]["complete"])
        self.assertEqual(len(_diags(env, "ValueError")), 1)

    def test_project_name_in_a_file_attribute_comment_adds_no_draw(self):
        with tempfile.TemporaryDirectory() as d:
            _gbr(d, "b-F_Cu.gtl", "Copper,L1,Top")
            p = os.path.join(d, "b-F_Cu.gtl")
            plain = ag.parse_gerber(p)["draw_count"]
            with open(p, encoding="utf-8") as f:
                body = f.read()
            _write(d, "b-F_Cu.gtl", "G04 #@! TF.ProjectId,lcd S6D0164,6e75,rev?*\n" + body)
            self.assertEqual(ag.parse_gerber(p)["draw_count"], plain)


class DrillTest(unittest.TestCase):
    def test_empty_and_prose_drill_files_earn_no_credit(self):
        for text in ("", "T01  0.70mm\nT02  2.00mm\n"):
            with self.subTest(text=text[:8]):
                with tempfile.TemporaryDirectory() as d:
                    _four_layer(d)
                    _write(d, "b.drl", text)
                    env = _main(d)
                self.assertFalse(env["completeness"]["complete"])
                self.assertEqual(len(_diags(env, "ValueError")), 1)
                self.assertIn("error", env["drills"][0])
                gr3 = [f for f in env["findings"] if f["rule_id"] == "GR-003"]
                self.assertEqual([f["severity"] for f in gr3], ["warning"])

    def test_drill_without_leading_digit_diameter_is_still_a_drill(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "NCDrill.drl", "%\nT1C.014F095S3\nX016034Y012031\nM30\n")
            self.assertNotIn("error", ag.parse_drill(os.path.join(d, "NCDrill.drl")))

    def test_header_only_drill_is_a_valid_empty_drill(self):
        with tempfile.TemporaryDirectory() as d:
            _four_layer(d)
            _write(d, "b.drl", "M48\n;TYPE=PLATED\nMETRIC\n%\nM30\n")
            env = _main(d)
        self.assertNotIn("error", env["drills"][0])
        self.assertEqual([f["severity"] for f in env["findings"] if f["rule_id"] == "GR-003"], ["info"])


class DrillCandidateTest(unittest.TestCase):
    def test_bom_text_is_not_a_drill_candidate_but_excellon_text_is(self):
        with tempfile.TemporaryDirectory() as d:
            _four_layer(d)
            _write(d, "bom.txt", "Ref  Value\nC1 cap T1C2 0402\nR1 res\n")
            _write(d, "eagle.txt", "M48\nMETRIC\nT1C0.8\n%\nT1\nX1000Y2000\nM30\n")
            env = _main(d)
        self.assertEqual(sorted(x["filename"] for x in env["drills"] if "bom" in x["filename"]), [])
        self.assertIn("eagle.txt", [x["filename"] for x in env["drills"]])
        self.assertFalse([x for x in env["drills"] if "error" in x])
        self.assertEqual(_diags(env, "ValueError"), [])


class CompanionFileTest(unittest.TestCase):
    def test_dot_companions_are_not_job_drill_or_archive_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            _four_layer(d)
            _write(d, "._b.gbrjob", json.dumps({"GeneralSpecs": {"LayerNumber": 2}, "FilesAttributes": []}))
            _write(d, "._b-PTH.drl", "")
            _write(d, ".git-x.drl", "")
            _write(d, "._b.zip", "x")
            env = _main(d)
        self.assertEqual(env["diagnostics"], [])
        self.assertEqual([x["filename"] for x in env["drills"]], ["b.drl"])
        self.assertNotIn("zip_archives", env)
        self.assertNotIn("job_file", env)
        self.assertEqual(env["completeness"]["source"], "defaults")
        self.assertFalse([p for p in env["inputs"]["source_files"] if os.path.basename(p).startswith(("._", ".git"))])


class JobFileTest(unittest.TestCase):
    def _job(self, **entry):
        return {"GeneralSpecs": {"LayerNumber": 2},
                "FilesAttributes": [dict({"Path": "b-F_Cu.gtl", "FileFunction": "Copper,L1,Top"}, **entry)]}

    def test_non_string_path_or_function_is_a_diagnostic_not_a_crash(self):
        for entry in ({"Path": None}, {"FileFunction": 3}):
            with self.subTest(entry=entry):
                with tempfile.TemporaryDirectory() as d:
                    _four_layer(d)
                    _write(d, "b.gbrjob", json.dumps(self._job(**entry)))
                    env = _main(d)
                self.assertEqual(env["completeness"]["source"], "defaults")
                self.assertEqual(len(_diags(env, "TypeError")), 1)


if __name__ == "__main__":
    unittest.main()
