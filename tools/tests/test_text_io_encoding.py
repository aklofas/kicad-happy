"""Every text-mode open(), read_text() and write_text() in the shipped code names its encoding, so a
non-UTF-8 locale (Windows cp1252) cannot change how reports, review files and artefacts are read or written."""
import ast, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _open_mode(call):
    mode = None
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
        mode = call.args[1].value
    for k in call.keywords:
        if k.arg == "mode" and isinstance(k.value, ast.Constant):
            mode = k.value.value
    return mode


def _unencoded_sites(root):
    hits = []
    for top in ("skills", "action"):
        for p in sorted((root / top).rglob("*.py")):
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                if not isinstance(n, ast.Call) or any(k.arg == "encoding" for k in n.keywords):
                    continue
                f = n.func
                if isinstance(f, ast.Name) and f.id == "open":
                    mode = _open_mode(n)
                    if not (isinstance(mode, str) and "b" in mode):
                        hits.append("%s:%d open" % (p.relative_to(root), n.lineno))
                elif isinstance(f, ast.Attribute):
                    if f.attr in ("read_text", "write_text"):
                        hits.append("%s:%d %s" % (p.relative_to(root), n.lineno, f.attr))
                    elif f.attr == "open" and isinstance(f.value, ast.Name) and f.value.id in ("io", "codecs"):
                        hits.append("%s:%d %s.open" % (p.relative_to(root), n.lineno, f.value.id))
    return hits


class TextIoEncodingTest(unittest.TestCase):
    def test_no_text_io_without_encoding(self):
        hits = _unencoded_sites(ROOT)
        self.assertEqual(hits, [], "text I/O without encoding=:\n" + "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
