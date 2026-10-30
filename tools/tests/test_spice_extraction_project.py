"""The SPICE datasheet-spec fallback reads extractions only from the project
the analysis names: a relative source path run from a shared cwd is no project."""
import json, os, shutil, sys, tempfile, unittest
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


if __name__ == "__main__":
    unittest.main()
