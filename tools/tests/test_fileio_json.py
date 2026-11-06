import io, json, os, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_core import fileio  # noqa: E402


class JsonHelpersTest(unittest.TestCase):
    def test_deep_nesting_is_a_decode_error(self):
        for call in (lambda: fileio.json_loads("[" * 100000),
                     lambda: fileio.json_loads(b"[" * 100000),
                     lambda: fileio.json_load(io.StringIO("[" * 100000))):
            with self.assertRaises(json.JSONDecodeError) as cm:
                call()
            self.assertIsInstance(cm.exception, ValueError)
            self.assertIn("nested too deeply", str(cm.exception))

    def test_valid_input_matches_the_stdlib(self):
        self.assertEqual(fileio.json_load(io.StringIO('{"a":1}')), {"a": 1})
        self.assertEqual(fileio.json_loads(b'[1, 2]'), [1, 2])

    def test_malformed_message_is_the_stdlib_message(self):
        with self.assertRaises(json.JSONDecodeError) as cm:
            fileio.json_loads("{")
        with self.assertRaises(json.JSONDecodeError) as std:
            json.loads("{")
        self.assertEqual(str(cm.exception), str(std.exception))

    def test_read_json_reads_a_file_and_maps_deep_nesting(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok = os.path.join(tmp, "ok.json")
            Path(ok).write_text('{"k": "\u00e9"}', encoding="utf-8")
            self.assertEqual(fileio.read_json(ok), {"k": "\u00e9"})
            deep = os.path.join(tmp, "deep.json")
            Path(deep).write_text("[" * 100000, encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                fileio.read_json(deep)
            with self.assertRaises(OSError):
                fileio.read_json(os.path.join(tmp, "missing.json"))


if __name__ == "__main__":
    unittest.main()
