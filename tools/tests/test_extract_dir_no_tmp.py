"""Datasheet extractions are read only from the project an analysis names:
resolve_extract_dir finds it from the analysis inputs, and with no project
there is no cache (never the shared temporary directory)."""
import json, os, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "skills" / "kicad" / "scripts", ROOT / "skills" / "datasheets" / "scripts",
          ROOT / "skills" / "datasheets", ROOT / "skills" / "emc" / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import datasheet_extract_cache as dec  # noqa: E402
import datasheet_features as df  # noqa: E402
import emc_rules  # noqa: E402
from datasheet_types import cache_reader  # noqa: E402

MPN = "PMCU1"


def mcu_extraction(speed):
    return {"topology": "mcu", "peripherals": {"usb": {"speed": speed}},
            "extraction_metadata": {"extraction_score": 9.0, "extraction_version": 2}}


def schematic_json(source_files):
    return {"inputs": {"source_files": source_files},
            "components": [{"reference": "U1", "type": "ic", "mpn": MPN, "value": MPN}]}


class ExtractDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        # A shared temp dir holding a planted extraction another user wrote.
        self.shared = self.tmp / "shared-tmp"
        poisoned = self.shared / "kicad-happy" / "datasheets" / "extracted"
        poisoned.mkdir(parents=True)
        (poisoned / f"{MPN}.json").write_text(json.dumps(mcu_extraction("SS")), encoding="utf-8")
        env = mock.patch.dict(os.environ, {"TMPDIR": str(self.shared)})
        tdir = mock.patch.object(tempfile, "tempdir", str(self.shared))
        env.start(); tdir.start()
        self.addCleanup(env.stop); self.addCleanup(tdir.stop)
        self.assertEqual(tempfile.gettempdir(), str(self.shared))
        # A real project with its own extraction.
        self.proj = self.tmp / "proj"
        cache = self.proj / "datasheets" / "extracted"
        cache.mkdir(parents=True)
        (self.proj / "board.kicad_sch").write_text("(kicad_sch)", encoding="utf-8")
        (cache / f"{MPN}.json").write_text(json.dumps(mcu_extraction("HS")), encoding="utf-8")

    def test_source_files_name_the_project_cache(self):
        a = {"inputs": {"source_files": [str(self.proj / "board.kicad_sch")]}}
        self.assertEqual(dec.resolve_extract_dir(analysis_json=a),
                         self.proj / "datasheets" / "extracted")
        self.assertEqual(df.get_mcu_features(MPN, analysis_json=a)["usb_speed"], "HS")

    def test_no_project_is_no_cache_and_no_temp_read(self):
        for a in (None, {}, {"inputs": {"source_files": []}}, {"file": ""}):
            self.assertIsNone(dec.resolve_extract_dir(analysis_json=a), a)
        self.assertIsNone(dec.resolve_extract_dir())
        self.assertIsNone(dec.get_cached_extraction(None, MPN))
        with mock.patch.object(df, "get_cached_extraction", side_effect=AssertionError("cache read")), \
             mock.patch.object(cache_reader, "lookup", side_effect=AssertionError("cache read")), \
             mock.patch.object(df, "read_json_object", side_effect=AssertionError("cache read")):
            for kw in ({}, {"analysis_json": {}}, {"project_dir": None},
                       {"analysis_json": {"inputs": {"source_files": []}}}):
                self.assertIsNone(df.get_mcu_features(MPN, **kw), kw)
                self.assertIsNone(df.get_regulator_features(MPN, **kw), kw)
                self.assertIsNone(df.get_pin_function(MPN, "1", **kw), kw)

    def test_emc_without_a_project_ignores_the_planted_cache(self):
        pair = {"shared_ics": ["U1"], "positive": "USB_DP", "negative": "USB_DN"}
        self.assertIsNone(emc_rules._resolve_usb_speed(pair, schematic_json([])))

    def test_emc_beside_a_real_project_uses_its_cache(self):
        pair = {"shared_ics": ["U1"], "positive": "USB_DP", "negative": "USB_DN"}
        sch = schematic_json([str(self.proj / "board.kicad_sch")])
        self.assertEqual(emc_rules._resolve_usb_speed(pair, sch), "HS")
        self.assertEqual(emc_rules._usb_pair_protocol(pair, "HS"), "USB-HS")


if __name__ == "__main__":
    unittest.main()
