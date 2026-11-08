"""A symbol with more than one Value field keeps KiCad 10's reading (the last one wins) and gets a
duplicate_value_field entry in property_issues naming the text it ignores.  Eagle imports write a
hidden empty copy after the real value: kicad-cli 10.0.8 shows no value for those parts (Bela
cape rev C2 C20/C22/C23)."""
import os, sys, tempfile, unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT))

from schematic.pipeline import analyze_schematic  # noqa: E402
from tools.tests.test_symbol_instances import ROOT_UUID, sch, sym, u  # noqa: E402


def _analyze(extra, value="0.1uf"):
    inst = f' (instances (project "t" (path "/{ROOT_UUID}" (reference "C1") (unit 1))))'
    body = sym(u(10), "C1", value, 50, inst=extra + inst)
    text = sch(20231120, ROOT_UUID, body, tail='(sheet_instances (path "/" (page "1")))')
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "t.kicad_sch")
        Path(path).write_text(text, encoding="utf-8")
        with redirect_stderr(StringIO()):
            return analyze_schematic(path)


def _prop(name, text):
    return f' (property "{name}" "{text}" (at 0 0 0) (effects (hide yes)))'


def _entries(result):
    return [i for i in (result.get("property_issues") or {}).get("issues", [])
            if i["issue"] == "duplicate_value_field"]


class DuplicateValueFieldTest(unittest.TestCase):
    def test_empty_second_value_is_annotated_as_showing_no_value(self):
        result = _analyze(_prop("Value", ""))
        self.assertEqual(result["components"][0]["value"], "")
        self.assertEqual(_entries(result), [{
            "component": "C1", "issue": "duplicate_value_field",
            "message": "C1: the symbol has more than one Value field; KiCad 10 reads the last "
                       "and shows no value, ignoring '0.1uf'"}])

    def test_upper_case_variant_names_the_value_shown(self):
        (entry,) = _entries(_analyze(_prop("VALUE", "430173003816"), value="Left"))
        self.assertEqual(entry["message"],
                         "C1: the symbol has more than one Value field; KiCad 10 reads the last "
                         "and shows '430173003816', ignoring 'Left'")

    def test_identical_copies_are_not_annotated(self):
        self.assertEqual(_entries(_analyze(_prop("Value", "0.1uf"))), [])

    def test_single_value_is_not_annotated(self):
        self.assertEqual(_entries(_analyze("")), [])

    def test_kicad6_instance_value_decides_and_is_not_annotated(self):
        # crabik-slot-esp32-s3 R1 (20211123): Value "10 kOhm", a hidden Value "10k", and a
        # (symbol_instances) value "10 kOhm"; kicad-cli 10.0.8 shows "10 kOhm".
        si = (f'(symbol_instances (path "/{u(10)}" (reference "C1") (unit 1) (value "10 kOhm")'
              f' (footprint "")))')
        body = sym(u(10), "C1", "10 kOhm", 50, inst=_prop("Value", "10k"))
        text = sch(20211123, ROOT_UUID, body, tail=f'(sheet_instances (path "/" (page "1"))) {si}')
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "k.kicad_sch")
            Path(path).write_text(text, encoding="utf-8")
            with redirect_stderr(StringIO()):
                result = analyze_schematic(path)
        self.assertEqual(result["components"][0]["value"], "10 kOhm")
        self.assertEqual(_entries(result), [])

    def test_private_dropped_values_never_reach_output(self):
        result = _analyze(_prop("Value", ""))
        self.assertNotIn("_dropped_values", result["components"][0])


if __name__ == "__main__":
    unittest.main()
