"""Job-file completeness: implied inner copper, KiCad 9.0.0-9.0.4 job layer ids, bare .g<n> numbering."""
import json, os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
import analyze_gerbers as ag  # noqa: E402

LINE = "X0Y0D02*\nX1000000Y0D01*\n"
SQUARE = ("X0Y0D02*\nX10000000Y0D01*\nX10000000Y10000000D01*\n"
          "X0Y10000000D01*\nX0Y0D01*\n")
DRILL_PTH = "M48\n;TYPE=PLATED\nMETRIC\nT1C0.3\n%\nT1\nX1.0Y1.0\nM30\n"

OUTER = [("x-F_Cu.gbr", "Copper,L1,Top"), ("x-F_Mask.gbr", "Soldermask,Top"),
         ("x-B_Mask.gbr", "Soldermask,Bot"), ("x-Edge_Cuts.gbr", "Profile,NP")]


def _gbr(d, name, ff, head_extra=""):
    head = f"%TF.FileFunction,{ff}*%\n" if ff else ""
    body = SQUARE if ff and ff.startswith("Profile") else LINE
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        f.write(f"{head_extra}{head}%FSLAX46Y46*%\n%MOMM*%\n%ADD10C,0.1*%\nD10*\n{body}M02*\n")


def _job(d, version, layer_number, files):
    """files: [(name, FileFunction)] as KiCad writes FilesAttributes."""
    job = {
        "Header": {"GenerationSoftware": {"Vendor": "KiCad", "Application": "Pcbnew",
                                          "Version": version},
                   "CreationDate": "2025-05-01T00:00:00+00:00"},
        "GeneralSpecs": {"Size": {"X": 10.0, "Y": 10.0}, "LayerNumber": layer_number,
                         "BoardThickness": 1.6},
        "FilesAttributes": [{"Path": n, "FileFunction": ff, "FilePolarity": "Positive"}
                            for n, ff in files],
    }
    with open(os.path.join(d, "x-job.gbrjob"), "w", encoding="utf-8") as f:
        json.dump(job, f)


def _run(listed, present, version="9.0.5", layer_number=4):
    """listed: job FilesAttributes; present: files written to disk (their own TF attribute)."""
    with tempfile.TemporaryDirectory() as d:
        for name, ff in present:
            _gbr(d, name, ff)
        with open(os.path.join(d, "x-PTH.drl"), "w", encoding="utf-8") as f:
            f.write(DRILL_PTH)
        _job(d, version, layer_number, listed)
        return ag.analyze_gerbers(d)


def _gr001(result):
    return sorted((f["summary"], f["severity"]) for f in result["findings"]
                  if f["rule_id"] == "GR-001")


class JobImpliedInnerCopperTest(unittest.TestCase):
    def test_four_layer_job_outer_only(self):
        # KiCad gerber_jobfile_writer.cpp: LayerNumber = GetCopperLayerCount(),
        # FilesAttributes lists only the plotted files.
        files = OUTER + [("x-B_Cu.gbr", "Copper,L4,Bot")]
        r = _run(files, files)
        c = r["completeness"]
        self.assertEqual(c["source"], "gbrjob")
        self.assertEqual(c["missing"], ["In1.Cu", "In2.Cu"])
        self.assertIs(c["complete"], False)
        self.assertEqual(_gr001(r), [("Missing layer: In1.Cu", "warning"),
                                     ("Missing layer: In2.Cu", "warning")])

    def test_four_layer_job_with_inner_files(self):
        files = OUTER + [("x-In1_Cu.gbr", "Copper,L2,Inr"), ("x-In2_Cu.gbr", "Copper,L3,Inr"),
                         ("x-B_Cu.gbr", "Copper,L4,Bot")]
        r = _run(files, files)
        self.assertEqual(r["completeness"]["missing"], [])
        self.assertIs(r["completeness"]["complete"], True)
        self.assertEqual(_gr001(r), [])

    def test_two_layer_job_one_side(self):
        files = [("x-B_Cu.gbr", "Copper,L2,Bot"), ("x-B_Mask.gbr", "Soldermask,Bot"),
                 ("x-Edge_Cuts.gbr", "Profile,NP")]
        r = _run(files, files, layer_number=2)
        self.assertEqual(r["completeness"]["missing"], [])
        self.assertIs(r["completeness"]["complete"], True)

    def test_four_layer_job_one_outer_side(self):
        # A job listing one outer side is a deliberate partial export.
        files = [("x-B_Cu.gbr", "Copper,L4,Bot"), ("x-Edge_Cuts.gbr", "Profile,NP")]
        r = _run(files, files)
        self.assertEqual(r["completeness"]["missing"], [])

    def test_paste_only_job(self):
        files = [("x-F_Paste.gbr", "Paste,Top")]
        r = _run(files, files)
        self.assertEqual(r["completeness"]["missing"], [])
        self.assertEqual(r["completeness"]["expected_layers"], ["F.Paste"])
        self.assertEqual(_gr001(r), [])


class KiCad9JobLayerIdTest(unittest.TestCase):
    # KiCad 9.0.0-9.0.4 gerber_jobfile_writer.cpp writes inner copper as
    # Copper,L<layer id + 1> with In1_Cu = 4, In2_Cu = 6 (L5, L7); the Gerber
    # files themselves carry L2/L3. Fixed in 9.0.5 (KiCad commit 9725ac2215).
    LISTED = OUTER + [("x-In1_Cu.gbr", "Copper,L5,Inr"), ("x-In2_Cu.gbr", "Copper,L7,Inr"),
                      ("x-B_Cu.gbr", "Copper,L4,Bot")]
    PRESENT = OUTER + [("x-In1_Cu.gbr", "Copper,L2,Inr"), ("x-In2_Cu.gbr", "Copper,L3,Inr"),
                       ("x-B_Cu.gbr", "Copper,L4,Bot")]

    def test_kicad_901_job_complete(self):
        r = _run(self.LISTED, self.PRESENT, version="9.0.1")
        c = r["completeness"]
        self.assertEqual(c["expected_layers"],
                         ["B.Cu", "B.Mask", "Edge.Cuts", "F.Cu", "F.Mask", "In1.Cu", "In2.Cu"])
        self.assertEqual(c["missing"], [])
        self.assertEqual(c["extra"], [])
        self.assertIs(c["complete"], True)
        self.assertEqual(_gr001(r), [])

    def test_kicad_901_job_listed_file_absent(self):
        present = [p for p in self.PRESENT if p[0] != "x-In1_Cu.gbr"]
        r = _run(self.LISTED, present, version="9.0.1")
        self.assertEqual(r["completeness"]["missing"], ["In1.Cu"])
        self.assertEqual(_gr001(r), [("Missing layer: In1.Cu", "warning")])

    def test_kicad_debian_version_string(self):
        present = [p for p in self.PRESENT if p[0] != "x-In1_Cu.gbr"]
        r = _run(self.LISTED, present, version="9.0.2+dfsg-1")
        self.assertEqual(r["completeness"]["missing"], ["In1.Cu"])

    def test_kicad_905_job_not_remapped(self):
        listed = [("x-F_Cu.gbr", "Copper,L1,Top"), ("x-In1_Cu.gbr", "Copper,L2,Inr"),
                  ("x-In2_Cu.gbr", "Copper,L3,Inr"), ("x-In3_Cu.gbr", "Copper,L4,Inr"),
                  ("x-In4_Cu.gbr", "Copper,L5,Inr"), ("x-B_Cu.gbr", "Copper,L6,Bot")]
        present = [p for p in listed if p[0] != "x-In4_Cu.gbr"]
        r = _run(listed, present, version="9.0.5", layer_number=6)
        self.assertEqual(r["completeness"]["missing"], ["In4.Cu"])


class BareProtelNumberingTest(unittest.TestCase):
    # pcbplot.cpp GetGerberProtelExtension: KiCad 8.0.9 writes g<layer id + 1>
    # with In1_Cu = 1 (In1 = .g2); 9.0.0 writes g<CopperLayerToOrdinal> (In1 = .g1).
    def _layer(self, name, head):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, name)
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"{head}%FSLAX46Y46*%\n%MOMM*%\n%ADD10C,0.1*%\nD10*\n{LINE}M02*\n")
            return ag.parse_gerber(p)["layer_type"]

    def test_kicad8_comment(self):
        self.assertEqual(self._layer(
            "b.g2", "G04 Created by KiCad (PCBNEW 8.0.9) date 2025-01-01 00:00:00*\n"), "In1.Cu")

    def test_kicad9_comment(self):
        self.assertEqual(self._layer(
            "b.g2", "G04 Created by KiCad (PCBNEW 9.0.0) date 2025-01-01 00:00:00*\n"), "In2.Cu")

    def test_kicad5_x2_comment_form(self):
        self.assertEqual(self._layer(
            "b.g3", "G04 #@! TF.GenerationSoftware,KiCad,Pcbnew,(5.1.12)-1*\n"), "In2.Cu")

    def test_kicad5_g1_is_not_inner(self):
        self.assertEqual(self._layer(
            "b.g1", "G04 Created by KiCad (PCBNEW (5.1.12)-1) date 2025-01-01 00:00:00*\n"),
            "unknown")

    def test_no_generator(self):
        self.assertEqual(self._layer("b.g2", ""), "In2.Cu")


if __name__ == "__main__":
    unittest.main()
