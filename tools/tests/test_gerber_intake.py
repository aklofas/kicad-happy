"""What a Gerber folder is read for. A `*.g*` file without a Gerber layer extension (a gerbv
project, photoplotter info, G-code) is read only when its head reads as Gerber; an unreadable
file with a layer extension (an encrypted .gbr, a binary .gto) is still reported as an error
record. KiCad 5 job files are read: `-job.gbj` in the Gerber-attribute form (as KiCad 5.0 wrote
it) and JSON with a comma before a closing brace (KiCad 5.1). A nightly (8.99/9.99) job that
numbers inner copper as KiCad 9.0.0-9.0.4 did (L5/L7 on a 4-layer board) is remapped."""
import contextlib, io, json, os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
import analyze_gerbers as ag  # noqa: E402

LINE = "X0Y0D02*\nX1000000Y0D01*\n"
SQUARE = "X0Y0D02*\nX10000000Y0D01*\nX10000000Y10000000D01*\nX0Y10000000D01*\nX0Y0D01*\n"
DRILL = "M48\n;TYPE=PLATED\nMETRIC\nT1C0.3\n%\nT1\nX1.0Y1.0\nM30\n"
OUTER = [("x-F_Cu.gbr", "Copper,L1,Top"), ("x-B_Cu.gbr", "Copper,L2,Bot"),
         ("x-F_Mask.gbr", "Soldermask,Top"), ("x-B_Mask.gbr", "Soldermask,Bot"),
         ("x-Edge_Cuts.gbr", "Profile,NP")]


def _write(d, name, data):
    mode = "wb" if isinstance(data, bytes) else "w"
    with open(os.path.join(d, name), mode, **({} if mode == "wb" else {"encoding": "utf-8"})) as f:
        f.write(data)


def _gbr(d, name, ff):
    body = SQUARE if ff.startswith("Profile") else LINE
    _write(d, name, f"%TF.FileFunction,{ff}*%\n%FSLAX46Y46*%\n%MOMM*%\n%ADD10C,0.1*%\nD10*\n"
                    f"{body}M02*\n")


def _run(extra=(), layers=OUTER):
    with tempfile.TemporaryDirectory() as d:
        for name, ff in layers:
            _gbr(d, name, ff)
        _write(d, "x-PTH.drl", DRILL)
        for name, data in extra:
            _write(d, name, data)
        with contextlib.redirect_stderr(io.StringIO()):
            return ag.analyze_gerbers(d)


def _names(result):
    return sorted(g["filename"] for g in result["gerbers"])


def _errors(result):
    return sorted(g["filename"] for g in result["gerbers"] if g.get("error"))


class NonLayerFiles(unittest.TestCase):
    def test_gerbv_project_photoplot_info_and_gcode_are_not_layers(self):
        r = _run([("x.gvp", '(gerbv-file-version! "2.0A")\n(define-layer! 0 (cons \'filename "x-F_Cu.gbr"))\n'),
                  ("x.gpi", "Photoplotter Info File\nLayer: F.Cu\n"),
                  ("mill.gcode", "G21\nG90\nG04 P0 (dwell)\nG01 X1 Y1 F100\nM2\n")])
        self.assertEqual(_names(r), sorted(n for n, _ in OUTER))
        self.assertEqual(_errors(r), [])

    def test_unreadable_files_with_a_layer_extension_stay_error_records(self):
        r = _run([("x-crypt.gbr", b"\x00GITCRYPT\x00" + bytes(range(256))),
                  ("x-F_SilkS.gto", bytes(range(256)) * 4)])
        self.assertEqual(_errors(r), ["x-F_SilkS.gto", "x-crypt.gbr"])

    def test_other_g_file_that_reads_as_gerber_is_kept(self):
        r = _run([("x-extra.gx1", "G04 Extra layer*\n%FSLAX46Y46*%\n%MOMM*%\n%ADD10C,0.1*%\nD10*\n"
                                  + LINE + "M02*\n")])
        self.assertIn("x-extra.gx1", _names(r))
        self.assertEqual(_errors(r), [])


GBJ = """G04 Gerber job file with board parameters*
%TF.FileFunction,JobInfo*%
%TF.Part,SinglePCB*%
%TF.GenerationSoftware,KiCad,Pcbnew,5.0.2-bee76a0~70~ubuntu18.04.1*%
%TF.CreationDate,2019-01-01T00:00:00+01:00*%
%TF.ProjectId,x,78,rev?*%
%MOMM*%
%TJ.B.Size.X,76.200*%
%TJ.B.Size.Y,52.070*%
%TJ.B.LayerNum,2*%
%TJ.B.Overall.Thickness,1.600*%
%TJ.L."Copper,L1,Top",Positive,x-F_Cu.gbr*%
%TJ.L."Copper,L2,Bot",Positive,x-B_Cu.gbr*%
%TJ.L."SolderMask,Top",Negative,x-F_Mask.gbr*%
%TJ.L."SolderMask,Bot",Negative,x-B_Mask.gbr*%
%TJ.L."Profile",Positive,x-Edge_Cuts.gbr*%
M02*
"""


def _json_job(version, layer_number, files, trailing_comma=False):
    job = {"Header": {"GenerationSoftware": {"Vendor": "KiCad", "Application": "Pcbnew",
                                             "Version": version},
                      "CreationDate": "2020-01-01T00:00:00+00:00"},
           "GeneralSpecs": {"Size": {"X": 30.0, "Y": 20.0}, "LayerNumber": layer_number,
                            "BoardThickness": 1.6},
           "FilesAttributes": [{"Path": n, "FileFunction": ff, "FilePolarity": "Positive"}
                               for n, ff in files]}
    if layer_number is None:
        del job["GeneralSpecs"]["LayerNumber"]
    text = json.dumps(job, indent=2)
    if trailing_comma:
        text = text.replace('"Positive"\n    }', '"Positive",\n    }').replace("}\n  ]", "},\n  ]")
    return text


class KiCad5JobFiles(unittest.TestCase):
    def test_gerber_attribute_job_is_read(self):
        r = _run([("x-job.gbj", GBJ)])
        self.assertEqual(r["job_file"]["generator"], "Pcbnew 5.0.2-bee76a0~70~ubuntu18.04.1")
        self.assertEqual((r["board_dimensions"]["width_mm"], r["board_dimensions"]["height_mm"]),
                         (76.2, 52.07))
        self.assertEqual(r["completeness"]["source"], "gbrjob")
        self.assertNotIn("x-job.gbj", _names(r))

    def test_json_job_with_trailing_commas_is_read(self):
        text = _json_job("5.1.5", 2, OUTER, trailing_comma=True)
        self.assertRaises(ValueError, json.loads, text)
        r = _run([("x-job.gbrjob", text)])
        self.assertEqual(r["job_file"]["generator"], "Pcbnew 5.1.5")
        self.assertEqual(r["completeness"]["source"], "gbrjob")


INNER_PRESENT = OUTER + [("x-In1_Cu.gbr", "Copper,L2,Inr"), ("x-In2_Cu.gbr", "Copper,L3,Inr")]
INNER_PRESENT = [(n, "Copper,L4,Bot" if n == "x-B_Cu.gbr" else ff) for n, ff in INNER_PRESENT]


class NightlyInnerNumbering(unittest.TestCase):
    def _completeness(self, version, listed_inner, layer_number=4):
        listed = [(n, ff) for n, ff in INNER_PRESENT if "In" not in n] + listed_inner
        present = [p for p in INNER_PRESENT if p[0] != "x-In1_Cu.gbr"]
        r = _run([("x-job.gbrjob", _json_job(version, layer_number, listed))], layers=present)
        return r["completeness"]

    def test_nightly_with_9_0_0_numbering_is_remapped(self):
        c = self._completeness("9.99.0-1234-g0123456789",
                               [("x-In1_Cu.gbr", "Copper,L5,Inr"), ("x-In2_Cu.gbr", "Copper,L7,Inr")])
        self.assertEqual(c["missing"], ["In1.Cu"])
        self.assertNotIn("In4.Cu", c["expected_layers"])

    def test_nightly_with_current_numbering_is_not_remapped(self):
        c = self._completeness("8.99.0-500-gabcdef",
                               [("x-In1_Cu.gbr", "Copper,L2,Inr"), ("x-In2_Cu.gbr", "Copper,L3,Inr")])
        self.assertEqual(c["missing"], ["In1.Cu"])

    def test_nightly_without_a_layer_count_is_not_remapped(self):
        c = self._completeness("9.99.0-1234-g0123456789",
                               [("x-In1_Cu.gbr", "Copper,L2,Inr"), ("x-In2_Cu.gbr", "Copper,L3,Inr")],
                               layer_number=None)
        self.assertEqual(c["missing"], ["In1.Cu"])


if __name__ == "__main__":
    unittest.main()
