"""A sheet file used by several sheet instances is parsed once per run, reusing its
parsed tree gives the same output as reading the file again for every instance, and a
sheet file that does not parse whole gets one diagnostics record however many instances
it has."""
import json, os, sys, tempfile, unittest
from collections import Counter
from contextlib import ExitStack, redirect_stderr
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import kicad_core.sexp as sexp  # noqa: E402
import schematic.hierarchy as hierarchy  # noqa: E402
import schematic.pipeline as pipeline  # noqa: E402
import schematic.reader as reader  # noqa: E402
from schematic.pipeline import analyze_schematic  # noqa: E402
from tools.tests.test_top_level_sheets_kicad10 import resistor, sch, u  # noqa: E402

ROOT_UUID = u(301)
AMPS = [u(310), u(320), u(330)]
INNER = u(340)


def sheet(uuid, name, fname, x, pin):
    return (f'(sheet (at {x} 80) (size 20 10) (uuid "{uuid}")'
            f' (property "Sheetname" "{name}" (at {x} 79 0))'
            f' (property "Sheetfile" "{fname}" (at {x} 91 0))'
            f' (pin "{pin}" input (at {x} 82 180) (uuid "{uuid[:-3]}901")))')


def project():
    """Three instances of amp.kicad_sch, each holding one instance of inner.kicad_sch.
    The inner resistor's field names another symbol, so its sheet is read again once
    every symbol is known."""
    root = "".join(sheet(a, f"Amp{i}", "amp.kicad_sch", 100 + 30 * i, "IN")
                   for i, a in enumerate(AMPS))
    root += f'(wire (pts (xy 100 82) (xy 160 82)) (uuid "{u(350)}"))'
    amp = (resistor(u(311), "R?", 50, [(f"/{ROOT_UUID}/{a}", f"R{i + 1}")
                                        for i, a in enumerate(AMPS)])
           + f'(wire (pts (xy 50 46.19) (xy 60 46.19)) (uuid "{u(312)}"))'
           f' (hierarchical_label "IN" (shape input) (at 60 46.19 0) (uuid "{u(313)}"))'
           + sheet(INNER, "Inner", "inner.kicad_sch", 60, "X")
           .replace("(at 60 80)", "(at 60 40)").replace("(at 60 82 180)", "(at 60 46.19 180)"))
    inner = resistor(u(341), "R?", 50, [(f"/{ROOT_UUID}/{a}/{INNER}", f"R{i + 11}")
                                         for i, a in enumerate(AMPS)])
    inner = inner.replace('(property "Datasheet" ""',
                          '(property "Note" "${R1:Value}" (at 50 50 0)) (property "Datasheet" ""')
    inner += (f' (wire (pts (xy 50 46.19) (xy 60 46.19)) (uuid "{u(342)}"))'
              f' (hierarchical_label "X" (shape input) (at 60 46.19 0) (uuid "{u(343)}"))')
    return {"p.kicad_sch": sch(ROOT_UUID, root),
            "amp.kicad_sch": sch(u(314), amp),
            "inner.kicad_sch": sch(u(344), inner)}


def write(files, tmp):
    for name, text in files.items():
        with open(os.path.join(tmp, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return os.path.join(tmp, "p.kicad_sch")


def stable(result, tmp):
    """The output as text, without the temporary directory or a run id."""
    (result.get("inputs") or {}).pop("run_id", None)
    text = json.dumps(result, sort_keys=True, default=str)
    for form in sorted({tmp, os.path.realpath(tmp)}, key=len, reverse=True):
        text = text.replace(json.dumps(form)[1:-1], "<tmp>")
    return text


class SheetParsedOnceTest(unittest.TestCase):
    def test_each_sheet_file_is_parsed_once(self):
        counts = Counter()

        def counting(real):
            def parse(path, *args, **kwargs):
                counts[os.path.basename(str(path))] += 1
                return real(path, *args, **kwargs)
            return parse

        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            path = write(project(), tmp)
            names = [n for n in ("parse_file", "parse_file_checked") if hasattr(sexp, n)]
            fakes = {n: counting(getattr(sexp, n)) for n in names}
            for module in (sexp, hierarchy, pipeline, reader):
                for name in names:
                    if hasattr(module, name):
                        stack.enter_context(mock.patch.object(module, name, fakes[name]))
            with redirect_stderr(StringIO()):
                result = analyze_schematic(path)
        self.assertEqual(len(result["sheets"]), 7)
        self.assertEqual(dict(counts), {"p.kicad_sch": 1, "amp.kicad_sch": 1,
                                        "inner.kicad_sch": 1})

    def test_reusing_the_tree_gives_the_output_of_reading_each_instance(self):
        real = reader.parse_single_sheet

        def fresh(path, *args, root=None, **kwargs):
            return real(path, *args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            path = write(project(), tmp)
            with redirect_stderr(StringIO()):
                cached = stable(analyze_schematic(path), tmp)
                with mock.patch.object(hierarchy, "parse_single_sheet", fresh):
                    reread = stable(analyze_schematic(path), tmp)
        self.assertIn('"R13"', cached)
        self.assertEqual(cached, reread)


class PartialSheetReportedOnceTest(unittest.TestCase):
    def test_cut_short_sheet_used_three_times_gets_one_record(self):
        files = project()
        files["amp.kicad_sch"] = files["amp.kicad_sch"].rstrip()[:-1]
        with tempfile.TemporaryDirectory() as tmp:
            path = write(files, tmp)
            with redirect_stderr(StringIO()):
                result = analyze_schematic(path)
        self.assertEqual(result["diagnostics"], [{
            "source": "schematic.hierarchy.parse_all_sheets", "exception": "ValueError",
            "message": "amp.kicad_sch: the file ends inside an open list",
            "effect": "partial sheet analyzed"}])
        self.assertEqual(len(result["sheets"]), 7)


if __name__ == "__main__":
    unittest.main()
