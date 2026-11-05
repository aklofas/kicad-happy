"""Every file a script writes in text mode names its line ending, so Windows writes LF as
Linux and macOS do (a CRLF manifest, JSON or rewritten schematic is not the same file)."""
import ast
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2] / "skills"
OPENERS = {"open", "fdopen", "NamedTemporaryFile"}


def _name(call):
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")


def _text_write_mode(call):
    mode = next((k.value.value for k in call.keywords
                 if k.arg == "mode" and isinstance(k.value, ast.Constant)), None)
    if mode is None and _name(call) in ("open", "fdopen") and len(call.args) >= 2 \
            and isinstance(call.args[1], ast.Constant):
        mode = call.args[1].value
    return isinstance(mode, str) and "b" not in mode and any(c in mode for c in "wax+")


def unset_newlines():
    for path in sorted(SKILLS.rglob("*.py")):
        if path.name.startswith("test_"):
            continue
        for call in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(call, ast.Call) or any(k.arg == "newline" for k in call.keywords):
                continue
            name = _name(call)
            if name == "write_text" or (name in OPENERS and _text_write_mode(call)):
                yield f"{path.relative_to(SKILLS)}:{call.lineno} {name}"


class TextWritesNameTheirNewline(unittest.TestCase):
    def test_no_text_write_uses_the_platform_line_ending(self):
        self.assertEqual(list(unset_newlines()), [])


if __name__ == "__main__":
    unittest.main()
