"""Thermal reads datasheet extractions only from the project the schematic
analysis names, never from the folder the analysis JSON happens to sit in."""
import json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
THERMAL = ROOT / "skills" / "kicad" / "scripts" / "analyze_thermal.py"
MPN = "PLDO1"
# Tj = 25 + 1.0 W x 60 C/W (SOT-223 table row) = 85 C: under the default 125 C limit, over a 60 C datasheet limit.
EXTRACTION = {"meta": {"extraction_score": 9.0},
              "absolute_maximum_ratings": {"junction_temp_max_c": 60}}


def schematic(source_files):
    return {"analyzer_type": "schematic", "inputs": {"source_files": source_files},
            "findings": [{"detector": "detect_power_regulators", "ref": "U1", "value": MPN,
                          "topology": "ldo",
                          "power_dissipation": {"estimated_pdiss_W": 1.0, "vin_estimated_V": 5.0,
                                                "vout_V": 3.3}}]}


PCB = {"analyzer_type": "pcb",
       "footprints": [{"reference": "U1", "value": MPN, "mpn": MPN, "x": 10.0, "y": 10.0,
                       "library": "Package_TO_SOT_SMD:SOT-223-3_TabPin2"}]}


class ThermalExtractDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def plant(self, folder):
        ext = folder / "datasheets" / "extracted"
        ext.mkdir(parents=True)
        (ext / f"{MPN}.json").write_text(json.dumps(EXTRACTION), encoding="utf-8")

    def run_thermal(self, json_dir, sch, cwd=None):
        json_dir.mkdir(parents=True, exist_ok=True)
        (json_dir / "schematic.json").write_text(json.dumps(sch), encoding="utf-8")
        (json_dir / "pcb.json").write_text(json.dumps(PCB), encoding="utf-8")
        out = self.tmp / f"thermal-{json_dir.name}.json"
        r = subprocess.run([sys.executable, str(THERMAL), "-s", str(json_dir / "schematic.json"),
                            "-p", str(json_dir / "pcb.json"), "-o", str(out)],
                           capture_output=True, text=True, cwd=cwd or self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr[-600:])
        self.stderr = r.stderr
        d = json.loads(out.read_text(encoding="utf-8"))
        (a,) = d["assessments"]
        return a, sorted(f["rule_id"] for f in d["findings"])

    def test_cache_beside_a_json_that_names_no_project_is_not_read(self):
        clean, clean_rules = self.run_thermal(self.tmp / "clean", schematic([]))
        shared = self.tmp / "shared"
        self.plant(shared)
        a, rules = self.run_thermal(shared, schematic([]))
        self.assertEqual((a["tj_max_c"], a["tj_max_source"]), (125.0, "default_125"))
        self.assertEqual((clean["tj_max_c"], clean["tj_max_source"]), (125.0, "default_125"))
        self.assertEqual(rules, clean_rules)

    def test_project_cache_is_used(self):
        proj = self.tmp / "proj"
        self.plant(proj)
        sch = schematic([str(proj / "board.kicad_sch")])
        for json_dir in (proj, proj / "analysis" / "run1"):
            a, _ = self.run_thermal(json_dir, sch)
            self.assertEqual((a["tj_max_c"], a["tj_max_source"]), (60.0, "datasheet"), json_dir)
            self.assertEqual(a["margin_c"], -25.0)

    @unittest.skipIf(os.name == "nt", "symlinks")
    def test_symlinked_project_datasheets_folder_is_refused(self):
        real = self.tmp / "elsewhere"
        self.plant(real)
        proj = self.tmp / "proj"
        proj.mkdir()
        os.symlink(real / "datasheets", proj / "datasheets")
        a, _ = self.run_thermal(proj, schematic([str(proj / "board.kicad_sch")]))
        self.assertEqual((a["tj_max_c"], a["tj_max_source"]), (125.0, "default_125"))
        self.assertIn("is reached through a symlink; datasheet extraction cache ignored", self.stderr)

    def test_regular_project_datasheets_folder_is_read_without_warning(self):
        proj = self.tmp / "proj"
        self.plant(proj)
        a, _ = self.run_thermal(proj, schematic([str(proj / "board.kicad_sch")]))
        self.assertEqual((a["tj_max_c"], a["tj_max_source"]), (60.0, "datasheet"))
        self.assertNotIn("symlink", self.stderr)

    def test_relative_source_path(self):
        # `analyze_schematic.py board.kicad_sch` records the path as typed.
        shared = self.tmp / "shared"
        self.plant(shared)
        a, _ = self.run_thermal(self.tmp / "out1", schematic(["board.kicad_sch"]), cwd=shared)
        self.assertEqual((a["tj_max_c"], a["tj_max_source"]), (125.0, "default_125"))
        proj = self.tmp / "proj"
        self.plant(proj)
        (proj / "board.kicad_sch").write_text("(kicad_sch)", encoding="utf-8")
        a, _ = self.run_thermal(self.tmp / "out2", schematic(["board.kicad_sch"]), cwd=proj)
        self.assertEqual((a["tj_max_c"], a["tj_max_source"]), (60.0, "datasheet"))


if __name__ == "__main__":
    unittest.main()
