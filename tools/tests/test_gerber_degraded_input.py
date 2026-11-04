"""A file that is unreadable or not a Gerber is an error record with a diagnostic, never a layer."""
import io, json, os, sys, tempfile, unittest, zipfile
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
import analyze_gerbers as ag  # noqa: E402

LINE = "X0Y0D02*\nX1000000Y0D01*\n"
SQUARE = ("X0Y0D02*\nX10000000Y0D01*\nX10000000Y10000000D01*\n"
          "X0Y10000000D01*\nX0Y0D01*\n")
DRILL_PTH = "M48\n;TYPE=PLATED\nMETRIC\nT1C0.3\n%\nT1\nX1.0Y1.0\nM30\n"


def _gbr(d, name, ff, body=LINE):
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        f.write(f"%TF.FileFunction,{ff}*%\n%FSLAX46Y46*%\n%MOMM*%\n%ADD10C,0.1*%\nD10*\n{body}M02*\n")


def _four_layer(d):
    _gbr(d, "b-F_Cu.gtl", "Copper,L1,Top")
    _gbr(d, "b-In1_Cu.g2", "Copper,L2,Inr")
    _gbr(d, "b-B_Cu.gbl", "Copper,L4,Bot")
    _gbr(d, "b-F_Mask.gts", "Soldermask,Top")
    _gbr(d, "b-B_Mask.gbs", "Soldermask,Bot")
    _gbr(d, "b-Edge_Cuts.gm1", "Profile,NP", SQUARE)
    with open(os.path.join(d, "b.drl"), "w", encoding="utf-8") as f:
        f.write(DRILL_PTH)


def _main(d):
    """Run the CLI as a user does; returns the envelope."""
    with tempfile.TemporaryDirectory() as out_dir:
        out = os.path.join(out_dir, "gerbers.json")
        with redirect_stderr(io.StringIO()):
            rc = ag.main([d, "--output", out])
        with open(out, encoding="utf-8") as f:
            env = json.load(f)
    assert rc == 0
    return env


def _diags(env, exception=None):
    return [x for x in env["diagnostics"] if exception is None or x["exception"] == exception]


class NotALayerTest(unittest.TestCase):
    def test_directory_named_like_a_layer_is_not_credited(self):
        with tempfile.TemporaryDirectory() as d:
            _four_layer(d)
            os.mkdir(os.path.join(d, "b.GL3"))
            env = _main(d)
        self.assertFalse(env["completeness"]["complete"])
        self.assertIn("In2.Cu", env["completeness"]["missing_required"])
        self.assertTrue([f for f in env["findings"] if f["rule_id"] == "GR-001"])
        self.assertEqual(len(_diags(env, "IsADirectoryError")), 1)

    def test_readable_inner_layer_is_still_credited(self):
        with tempfile.TemporaryDirectory() as d:
            _four_layer(d)
            _gbr(d, "b-In2_Cu.gl3", "Copper,L3,Inr")
            env = _main(d)
        self.assertNotIn("In2.Cu", env["completeness"]["missing_required"])
        self.assertEqual(env["diagnostics"], [])

    def test_zero_byte_and_non_gerber_files_are_errors(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("b-F_Cu.gtl", "b-B_Cu.gbl", "b-F_Mask.gts", "b-B_Mask.gbs",
                         "b-Edge_Cuts.gm1"):
                open(os.path.join(d, name), "w").close()
            with open(os.path.join(d, "b.drl"), "w", encoding="utf-8") as f:
                f.write(DRILL_PTH)
            env = _main(d)
        self.assertFalse(env["completeness"]["complete"])
        self.assertEqual(len(_diags(env, "ValueError")), 5)
        self.assertEqual(sum(1 for g in env["gerbers"] if "error" in g), 5)
        self.assertEqual(sum(1 for g in env["gerbers"] if g.get("layer_type", "").endswith(".Cu")), 0)

    def test_firmware_blob_with_gerber_extension_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            _four_layer(d)
            with open(os.path.join(d, "fw.gbl"), "wb") as f:
                f.write(b"\x00\x01\x02 firmware blob\xff")
            env = _main(d)
        bad = [g for g in env["gerbers"] if g["filename"] == "fw.gbl"]
        self.assertEqual(len(bad), 1)
        self.assertIn("error", bad[0])
        self.assertEqual(len(_diags(env, "ValueError")), 1)


class DiscoveryTest(unittest.TestCase):
    def test_repo_and_fs_artifacts_are_not_discovered(self):
        with tempfile.TemporaryDirectory() as d:
            _four_layer(d)
            open(os.path.join(d, ".gitignore"), "w").close()
            os.mkdir(os.path.join(d, ".git"))
            open(os.path.join(d, "._b-F_Cu.gtl"), "wb").close()
            open(os.path.join(d, "b-F_Cu.gtl:Zone.Identifier"), "w").close()
            env = _main(d)
        self.assertEqual(env["diagnostics"], [])
        self.assertFalse([g for g in env["gerbers"] if "error" in g])
        self.assertEqual(len(env["gerbers"]), 6)

    def test_real_dot_file_gerber_is_still_read(self):
        with tempfile.TemporaryDirectory() as d:
            _four_layer(d)
            _gbr(d, ".kicad_pcb-In2_Cu.gl3", "Copper,L3,Inr")
            env = _main(d)
        self.assertEqual(len(env["gerbers"]), 7)
        self.assertFalse([g for g in env["gerbers"] if "error" in g])
        self.assertNotIn("In2.Cu", env["completeness"]["missing_required"])


class JobFileTest(unittest.TestCase):
    def _run(self, text):
        with tempfile.TemporaryDirectory() as d:
            _four_layer(d)
            with open(os.path.join(d, "b.gbrjob"), "w", encoding="utf-8") as f:
                f.write(text)
            return _main(d)

    def test_unusable_job_files_give_one_diagnostic_and_the_defaults(self):
        for text in ("[]", '{"Header": []}', '{"GeneralSpecs": {"LayerNumber": "4"}}',
                     '{"FilesAttributes": ["x"]}', "{not json"):
            with self.subTest(text=text):
                env = self._run(text)
                diags = [x for x in env["diagnostics"] if x["source"] == "analyze_gerbers.parse_job_file"]
                self.assertEqual(len(diags), 1)
                self.assertEqual(len(env["gerbers"]), 6)
                self.assertFalse([g for g in env["gerbers"] if "error" in g])


class ZipTest(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "symlinks")
    def test_dangling_zip_is_reported_and_loose_files_are_analysed(self):
        with tempfile.TemporaryDirectory() as d:
            _four_layer(d)
            os.symlink(os.path.join(d, "gone.zip"), os.path.join(d, "old.zip"))
            env = _main(d)
        self.assertEqual(len(_diags(env, "FileNotFoundError")), 1)
        self.assertEqual(len(env["gerbers"]), 6)
        entry = [z for z in env["zip_archives"] if z["filename"] == "old.zip"]
        self.assertEqual(len(entry), 1)
        self.assertIn("error", entry[0])

    def test_readable_zip_has_no_diagnostic(self):
        with tempfile.TemporaryDirectory() as d:
            _four_layer(d)
            with zipfile.ZipFile(os.path.join(d, "a.zip"), "w") as z:
                z.writestr("b-F_Cu.gtl", "x")
            env = _main(d)
        self.assertEqual(env["diagnostics"], [])


if __name__ == "__main__":
    unittest.main()
