"""--output JSON is streamed to the file instead of being built as one string first, with the
same bytes; atomic_write_text takes the text or a callable that writes it."""
import contextlib, io, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

from tools.tests._fixtures import fixture_path, have

SKILLS = Path(__file__).resolve().parents[2] / "skills"
for _d in ("kicad", "emc"):
    sys.path.insert(0, str(SKILLS / _d / "scripts"))
FX = fixture_path("simple-project")

from kicad_core.fileio import atomic_write_text  # noqa: E402
import analyze_schematic, analyze_pcb, analyze_emc, analyze_thermal  # noqa: E402

REAL_DUMPS = json.dumps


class WriterFormTest(unittest.TestCase):
    def test_callable_writes_what_the_text_form_writes(self):
        text = "line one\nline two\n"
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a.txt", Path(d) / "b.txt"
            atomic_write_text(a, text)
            atomic_write_text(b, lambda f: f.write(text))
            self.assertEqual(a.read_bytes(), b.read_bytes())
            atomic_write_text(os.devnull, lambda f: f.write(text))

    def test_failing_writer_leaves_the_old_file_and_no_temp(self):
        def boom(f):
            f.write("partial")
            raise ValueError("cannot encode")

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "out.json"
            p.write_text("old", encoding="utf-8")
            with self.assertRaises(ValueError):
                atomic_write_text(p, boom)
            self.assertEqual(p.read_text(encoding="utf-8"), "old")
            self.assertEqual(os.listdir(d), ["out.json"])


@unittest.skipUnless(have(FX / "simple.kicad_sch"), "fixtures absent")
class LargeOutputStreamTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        t = Path(cls._tmp.name)
        cls.sch, cls.pcb = str(t / "sch.json"), str(t / "pcb.json")
        with contextlib.redirect_stderr(io.StringIO()):
            assert analyze_schematic.main([str(FX / "simple.kicad_sch"), "-o", cls.sch]) == 0
            assert analyze_pcb.main([str(FX / "simple.kicad_pcb"), "-o", cls.pcb]) == 0

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_streamed(self, main, argv):
        """main(argv + ["-o", out]) with an indented json.dumps of the envelope refused;
        returns the file's text and the envelope json.dump was given."""
        seen = []
        real_dump = json.dump

        def dumps(obj, *args, **kwargs):
            if kwargs.get("indent") is not None and isinstance(obj, dict) and "compat" in obj:
                raise AssertionError("the whole --output text was built in memory")
            return REAL_DUMPS(obj, *args, **kwargs)

        def dump(obj, fp, *args, **kwargs):
            seen.append(obj)
            return real_dump(obj, fp, *args, **kwargs)

        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.json"
            with mock.patch.object(json, "dumps", dumps), mock.patch.object(json, "dump", dump), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(argv + ["-o", str(out)]), 0)
            self.assertEqual(len(seen), 1)
            return out.read_text(encoding="utf-8"), seen[0]

    def test_large_output_written_by_stream(self):
        cases = {
            "schematic": (analyze_schematic.main, [str(FX / "simple.kicad_sch")], str),
            "pcb": (analyze_pcb.main, [str(FX / "simple.kicad_pcb")], str),
            "emc": (analyze_emc.main, ["--schematic", self.sch, "--pcb", self.pcb], None),
            "thermal": (analyze_thermal.main, ["--schematic", self.sch, "--pcb", self.pcb], None),
        }
        for name, (main, argv, default) in cases.items():
            with self.subTest(name):
                text, result = self.run_streamed(main, argv)
                self.assertEqual(text, REAL_DUMPS(result, indent=2, default=default))

    def test_compact_output_is_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.json"
            with contextlib.redirect_stderr(io.StringIO()):
                analyze_schematic.main([str(FX / "simple.kicad_sch"), "--compact", "-o", str(out)])
            text = out.read_text(encoding="utf-8")
        self.assertNotIn("\n", text)
        self.assertEqual(REAL_DUMPS(json.loads(text), default=str), text)


if __name__ == "__main__":
    unittest.main()
