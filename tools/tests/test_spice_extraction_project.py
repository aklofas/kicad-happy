"""The SPICE datasheet-spec fallback reads extractions only from the project
the analysis names: a relative source path run from a shared cwd is no project."""
import json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "spice" / "scripts"))
import spice_model_cache as smc  # noqa: E402
import spice_spec_fetcher as ssf  # noqa: E402

MPN = "POPAMP1"
CONTEXT = {"inputs": {"source_files": ["board.kicad_sch"]}}


class SpiceExtractionProjectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        for name in ("lcsc", "digikey", "element14", "mouser"):
            p = mock.patch.object(ssf, f"fetch_specs_{name}", return_value=None)
            p.start(); self.addCleanup(p.stop)

    def plant(self, folder):
        ext = folder / "datasheets" / "extracted"
        ext.mkdir(parents=True)
        (ext / f"{MPN}.json").write_text(json.dumps(
            {"meta": {"extraction_score": 9.0}, "spice_specs": {"gbw_hz": 1e6}}), encoding="utf-8")
        (ext / "manifest.json").write_text(json.dumps(
            {"extractions": {MPN: {"file": f"{MPN}.json"}}}), encoding="utf-8")

    def resolve(self, cwd):
        os.chdir(cwd)
        opts = smc.ModelOptions(cache_dir=str(self.tmp / "model-cache"))
        return smc.get_model_for_part(MPN, "opamp", CONTEXT, options=opts)[1]

    def test_relative_source_from_a_shared_cwd_reads_no_extraction(self):
        shared = self.tmp / "shared"
        self.plant(shared)
        self.assertNotEqual(self.resolve(shared), f"extraction:{MPN}")

    def test_relative_source_from_the_project_cwd_reads_its_extraction(self):
        proj = self.tmp / "proj"
        self.plant(proj)
        (proj / "board.kicad_sch").write_text("(kicad_sch)", encoding="utf-8")
        self.assertEqual(self.resolve(proj), f"extraction:{MPN}")

    def test_no_project_dir_is_no_extraction(self):
        self.assertIsNone(ssf.fetch_specs_from_extraction(MPN, None))
        self.assertIsNone(ssf.fetch_specs_from_datasheet(MPN, None))


class PdfManifestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        (self.tmp / "outside.pdf").write_bytes(b"%PDF-1.4")
        self.n = 0

    def _pdf_project(self, value):
        self.n += 1
        proj = self.tmp / f"proj{self.n}"
        (proj / "datasheets").mkdir(parents=True)
        (proj / "datasheets" / "manifest.json").write_text(json.dumps(
            {"parts": {MPN: {"status": "ok", "file": value}}}), encoding="utf-8")
        return proj

    def _pdftotext_calls(self, proj):
        with mock.patch.object(ssf, "find_executable", return_value="/fake/pdftotext"), \
                mock.patch("subprocess.run") as run:
            ssf.fetch_specs_from_datasheet(MPN, proj)
        return [c.args[0][-2] for c in run.call_args_list]

    def test_pdf_outside_the_datasheets_folder_is_not_read(self):
        for value in ("../../outside.pdf", str(self.tmp / "outside.pdf")):
            self.assertEqual(self._pdftotext_calls(self._pdf_project(value)), [], value)

    @unittest.skipIf(os.name == "nt", "needs symlinks")
    def test_linked_pdf_or_datasheets_folder_is_not_read(self):
        proj = self._pdf_project("POPAMP1.pdf")
        os.symlink(self.tmp / "outside.pdf", proj / "datasheets" / "POPAMP1.pdf")
        self.assertEqual(self._pdftotext_calls(proj), [])
        real = self.tmp / "realds"
        proj2 = self._pdf_project("POPAMP1.pdf")
        shutil.move(str(proj2 / "datasheets"), str(real))
        (real / "POPAMP1.pdf").write_bytes(b"%PDF-1.4")
        os.symlink(real, proj2 / "datasheets")
        self.assertEqual(self._pdftotext_calls(proj2), [])

    def test_pdf_inside_the_folder_is_still_read(self):
        proj = self._pdf_project("POPAMP1.pdf")
        (proj / "datasheets" / "POPAMP1.pdf").write_bytes(b"%PDF-1.4")
        self.assertEqual(self._pdftotext_calls(proj), [str(proj / "datasheets" / "POPAMP1.pdf")])

    def test_wrong_shape_manifests_are_no_spec(self):
        for body in ("[]", json.dumps({"parts": []}), json.dumps({"parts": {MPN: "x"}})):
            proj = self._pdf_project("POPAMP1.pdf")
            (proj / "datasheets" / "manifest.json").write_text(body, encoding="utf-8")
            self.assertIsNone(ssf.fetch_specs_from_datasheet(MPN, proj), body)

    @unittest.skipIf(os.name == "nt", "FIFOs")
    @unittest.skipUnless(hasattr(os, "mkfifo"), "needs named pipes")
    def test_fifo_pdf_manifest_returns_promptly(self):
        proj = self.tmp / "fifoproj"
        (proj / "datasheets").mkdir(parents=True)
        os.mkfifo(proj / "datasheets" / "manifest.json")
        code = ("import sys; sys.path.insert(0, %r); import spice_spec_fetcher as s; "
                "print(s.fetch_specs_from_datasheet(%r, %r))"
                % (str(Path(ssf.__file__).parent), MPN, str(proj)))
        out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True,
                             text=True, timeout=20, check=True).stdout
        self.assertEqual(out.strip(), "None")


if __name__ == "__main__":
    unittest.main()
