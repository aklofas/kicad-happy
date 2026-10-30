"""Drill files are counted as KiCad's drill report counts them.

Gerber-format drill files (KiCad's ``-drl.gbr``: X2 ``FileFunction`` Plated /
NonPlated, round holes flashed, a slot drawn as one D01) and ``.xln``/``.nc``
Excellon files are drills; an Excellon route-mode slot (``G00`` move, ``M15``
plunge, ``G01``, ``M16`` retract, ``G05``) and a G85 slot are one hole of their
tool, as KiCad's ``m_TotalCount`` and its drill report count them.
"""
import io, json, os, sys, tempfile, unittest
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
import analyze_gerbers as ag  # noqa: E402

EDGE = ("%TF.FileFunction,Profile,NP*%\n%FSLAX46Y46*%\n%MOMM*%\n%ADD10C,0.100000*%\nD10*\n"
        "X0Y0D02*\nX10000000Y0D01*\nX10000000Y10000000D01*\nX0Y10000000D01*\nX0Y0D01*\nM02*\n")

# As KiCad's Gerber drill writer emits them: X2 forced, one aperture per tool
# carrying its TA.AperFunction, round holes flashed, a slot as D02 + one D01.
PTH = ("%TF.GenerationSoftware,KiCad,Pcbnew,10.0.7*%\n"
       "%TF.FileFunction,Plated,1,2,PTH,Drill*%\n%FSLAX46Y46*%\n%MOMM*%\n"
       "%TA.AperFunction,ViaDrill*%\n%ADD10C,0.300000*%\n%TD*%\n"
       "%TA.AperFunction,ComponentDrill*%\n%ADD11C,1.000000*%\n%TD*%\n"
       "D10*\nX1000000Y1000000D03*\nX2000000Y1000000D03*\nX3000000Y1000000D03*\n"
       "D11*\n%TO.C,U1*%\nX4000000Y4000000D03*\nX5000000Y4000000D03*\n%TD*%\n"
       "X6000000Y6000000D02*\nX8000000Y6000000D01*\nM02*\n")
NPTH = ("%TF.GenerationSoftware,KiCad,Pcbnew,10.0.7*%\n"
        "%TF.FileFunction,NonPlated,1,2,NPTH,Drill*%\n%FSLAX46Y46*%\n%MOMM*%\n"
        "%TA.AperFunction,ComponentDrill*%\n%ADD10C,3.000000*%\n%TD*%\n"
        "D10*\n%TO.C,H1*%\nX1000000Y9000000D03*\n%TO.C,H2*%\nX9000000Y9000000D03*\n%TD*%\nM02*\n")

EXC_HEAD = "M48\nMETRIC\nT1C0.800\nT2C1.000\n%\nG90\nG05\n"
# KiCad's route-mode slot (the GUI default oval format).
ROUTE = EXC_HEAD + "T1\nX1.0Y1.0\nT2\nG00X1.0Y2.0\nM15\nG01X3.0Y2.0\nM16\nG05\nX5.0Y5.0\nM30\n"
# KiCad's alternate (G85) slot, kicad-cli's default oval format.
G85 = EXC_HEAD + "T2\nX1.0Y2.0G85X3.0Y2.0\nM30\n"


def _write(d, name, text):
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def _rule_ids(r):
    return sorted(f["rule_id"] + ":" + f["severity"] for f in r["findings"])


class GerberDrillTest(unittest.TestCase):
    def _pair(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "b-Edge_Cuts.gm1", EDGE)
            _write(d, "b-PTH-drl.gbr", PTH)
            _write(d, "b-NPTH-drl.gbr", NPTH)
            return ag.analyze_gerbers(d)

    def test_gerber_drill_pair_counts_as_drills(self):
        r = self._pair()
        st = r["statistics"]
        # 3 vias + 2 component holes + 1 slot + 2 NPTH holes.
        self.assertEqual((st["gerber_files"], st["drill_files"], st["total_holes"]), (1, 2, 8))
        self.assertEqual([g["filename"] for g in r["gerbers"]], ["b-Edge_Cuts.gm1"])
        self.assertNotIn("GR-003", {f["rule_id"] for f in r["findings"]})
        drills = {x["filename"]: x for x in r["drills"]}
        self.assertEqual(drills["b-PTH-drl.gbr"]["type"], "PTH")
        self.assertEqual(drills["b-NPTH-drl.gbr"]["type"], "NPTH")
        self.assertEqual(drills["b-PTH-drl.gbr"]["layer_span"], [1, 2])
        self.assertEqual(drills["b-PTH-drl.gbr"]["tools"], {
            "D10": {"diameter_mm": 0.3, "hole_count": 3, "aper_function": "ViaDrill"},
            "D11": {"diameter_mm": 1.0, "hole_count": 3, "aper_function": "ComponentDrill"}})
        dc = r["drill_classification"]
        self.assertEqual((dc["vias"]["count"], dc["component_holes"]["count"],
                          dc["mounting_holes"]["count"]), (3, 3, 2))
        self.assertTrue(r["completeness"]["has_pth_drill"])
        self.assertTrue(r["completeness"]["has_npth_drill"])

    def test_drill_file_refs_leave_component_analysis(self):
        # The drill files' %TO.C refs are hole attributes, not layer components.
        self.assertNotIn("component_analysis", self._pair())

    def test_generator_falls_back_to_a_gerber_drill(self):
        self.assertEqual(self._pair()["generator"], "KiCad,Pcbnew,10.0.7")

    def test_gerber_drill_in_inches(self):
        text = ("%TF.FileFunction,Plated,1,2,PTH*%\n%FSLAX24Y24*%\n%MOIN*%\n"
                "%ADD10C,0.040000*%\nD10*\nX10000Y20000D03*\nM02*\n")
        with tempfile.TemporaryDirectory() as d:
            _write(d, "b-PTH-drl.gbr", text)
            r = ag.analyze_gerbers(d)
        dr = r["drills"][0]
        self.assertEqual(dr["tools"]["D10"]["diameter_mm"], 1.016)  # 0.04 in
        self.assertEqual(r["alignment"]["layer_extents"]["drill_PTH"], {"width": 0.0, "height": 0.0})

    def test_region_contour_is_not_a_drawn_hole(self):
        # Gerber spec: a G36..G37 region's D01 segments are its contour; the
        # current aperture is not used, so they are no slots of that tool.
        text = ("%TF.FileFunction,NonPlated,1,2,NPTH,Drill*%\n%FSLAX46Y46*%\n%MOMM*%\n"
                "%ADD10C,3.000000*%\nD10*\nX1000000Y1000000D03*\n"
                "G36*\nX0Y0D02*\nX3000000Y0D01*\nX3000000Y3000000D01*\nX0Y0D01*\nG37*\n"
                "X9000000Y9000000D03*\nM02*\n")
        with tempfile.TemporaryDirectory() as d:
            _write(d, "b-NPTH-drl.gbr", text)
            r = ag.analyze_gerbers(d)
        self.assertEqual(r["drills"][0]["tools"]["D10"]["hole_count"], 2)

    def test_drill_only_folder_invents_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "b-PTH-drl.gbr", PTH.replace("Plated,1,2,", "Plated,1,4,"))
            r = ag.analyze_gerbers(d)
        self.assertEqual(r["layer_count"], 4)
        self.assertEqual(r["gerbers"], [])
        self.assertNotIn("component_analysis", r)
        self.assertNotIn("net_analysis", r)
        self.assertEqual(r["completeness"]["missing_required"],
                         ["B.Cu", "B.Mask", "Edge.Cuts", "F.Cu", "F.Mask", "In1.Cu", "In2.Cu"])
        self.assertEqual(r["alignment"]["issues"], [])
        self.assertEqual(_rule_ids(r), sorted(
            ["GR-001:warning"] * 7 + ["GR-001:info"] * 2))


class ExcellonSlotTest(unittest.TestCase):
    def _drill(self, text, name="b.drl"):
        with tempfile.TemporaryDirectory() as d:
            return ag.parse_drill(_write(d, name, text))

    def test_route_slot_is_one_hole(self):
        r = self._drill(ROUTE)
        self.assertEqual(r["tools"]["T2"]["hole_count"], 2)
        self.assertEqual(r["tools"]["T1"]["hole_count"], 1)
        self.assertEqual(r["hole_count"], 3)
        self.assertEqual(r["coordinate_range"],
                         {"x_min": 1.0, "x_max": 5.0, "y_min": 1.0, "y_max": 5.0})

    def test_g85_slot_is_one_hole(self):
        self.assertEqual(self._drill(G85)["tools"]["T2"]["hole_count"], 1)

    def test_route_move_without_plunge_is_not_a_hole(self):
        r = self._drill(EXC_HEAD + "T2\nG00X1.0Y2.0\nG05\nX5.0Y5.0\nM30\n")
        self.assertEqual(r["tools"]["T2"]["hole_count"], 1)


class DrillDiscoveryTest(unittest.TestCase):
    def test_xln_and_nc_with_an_excellon_header_are_drills(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "b-Edge_Cuts.gm1", EDGE)
            _write(d, "board.xln", ROUTE)
            _write(d, "npth.NC", G85)
            _write(d, "notes.nc", "this is a CNC note, not a drill file\n")
            _write(d, "empty.xln", "")
            r = ag.analyze_gerbers(d)
        self.assertEqual(sorted(x["filename"] for x in r["drills"]), ["board.xln", "npth.NC"])
        self.assertEqual(r["statistics"]["total_holes"], 4)

    def test_drl_directory_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "b-Edge_Cuts.gm1", EDGE)
            os.mkdir(os.path.join(d, "g.drl"))
            os.mkdir(os.path.join(d, "h.xln"))
            sink = []
            with redirect_stderr(io.StringIO()):
                r = ag.analyze_gerbers(d, diagnostics=sink)
        # A header-validated name (.xln) that is not a file is simply not Excellon.
        self.assertEqual(r["statistics"]["drill_files"], 0)
        self.assertEqual([(x["exception"], Path(x["message"].split("'")[1]).name) for x in sink],
                         [("IsADirectoryError", "g.drl")])

    def test_drl_directory_cli_exit_code_and_diagnostic(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "gerbers")
            os.mkdir(src)
            _write(src, "b-Edge_Cuts.gm1", EDGE)
            os.mkdir(os.path.join(src, "g.drl"))
            out = os.path.join(d, "out", "gerbers.json")
            os.mkdir(os.path.dirname(out))
            err = io.StringIO()
            with redirect_stderr(err):
                rc = ag.main([src, "--output", out])
            with open(out, encoding="utf-8") as f:
                env = json.load(f)
        self.assertEqual(rc, 0)
        self.assertEqual(len(env["diagnostics"]), 1)
        diag = env["diagnostics"][0]
        self.assertEqual((diag["source"], diag["exception"]),
                         ("analyze_gerbers.analyze_gerbers", "IsADirectoryError"))
        self.assertIn("g.drl", diag["message"])
        self.assertIn("Warning: analyze_gerbers.analyze_gerbers: IsADirectoryError", err.getvalue())

    def test_dangling_drill_symlink_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "b-Edge_Cuts.gm1", EDGE)
            os.symlink(os.path.join(d, "gone.drl"), os.path.join(d, "b.drl"))
            sink = []
            with redirect_stderr(io.StringIO()):
                r = ag.analyze_gerbers(d, diagnostics=sink)
        self.assertEqual(r["statistics"]["drill_files"], 0)
        self.assertEqual([x["exception"] for x in sink], ["FileNotFoundError"])

    def test_symlinked_drill_outside_the_folder_is_read(self):
        # Discovery has never refused a symlinked input; it is read like a file.
        with tempfile.TemporaryDirectory() as d:
            outside = _write(d, "outside.drl", G85)
            src = os.path.join(d, "gerbers")
            os.mkdir(src)
            _write(src, "b-Edge_Cuts.gm1", EDGE)
            os.symlink(outside, os.path.join(src, "b.drl"))
            r = ag.analyze_gerbers(src)
        self.assertEqual((r["statistics"]["drill_files"], r["statistics"]["total_holes"]), (1, 1))

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads mode-000 files")
    def test_unreadable_drill_file_does_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "b-Edge_Cuts.gm1", EDGE)
            p = _write(d, "b.drl", G85)
            os.chmod(p, 0)
            try:
                r = ag.analyze_gerbers(d)
            finally:
                os.chmod(p, 0o600)
        self.assertIn("error", r["drills"][0])
        self.assertEqual(r["statistics"]["total_holes"], 0)


if __name__ == "__main__":
    unittest.main()
