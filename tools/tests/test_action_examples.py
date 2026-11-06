"""The fork-safe comment example only comments on a verified pull request number."""
import os, re, shutil, stat, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMMENT = ROOT / "action" / "examples" / "fork-safe-comment.yml"


def step_script(text, step_id):
    """The `run: |` body of the step with this id, dedented."""
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if l.strip() == f"- id: {step_id}")
    i = next(i for i in range(start, len(lines)) if lines[i].strip() == "run: |")
    indent = len(lines[i]) - len(lines[i].lstrip())
    body = []
    for l in lines[i + 1:]:
        if l.strip() and len(l) - len(l.lstrip()) <= indent:
            break
        body.append(l)
    return "\n".join(b[indent + 2:] for b in body) + "\n"


@unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "POSIX bash step")
class PrNumberStepTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)
        gh = self.d / "bin" / "gh"
        gh.parent.mkdir()
        gh.write_text('#!/bin/sh\nprintf "%s\\n" "$STUB_SHA"\n', encoding="utf-8")
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
        self.script = step_script(COMMENT.read_text(encoding="utf-8"), "pr-number")

    def tearDown(self):
        self._tmp.cleanup()

    def run_step(self, number, stub_sha="abc"):
        (self.d / "pr-number.txt").write_bytes(number.encode())
        out = self.d / "out"
        out.write_text("", encoding="utf-8")
        env = dict(os.environ, PATH=f"{self.d / 'bin'}{os.pathsep}{os.environ['PATH']}",
                   GITHUB_OUTPUT=str(out), REPO="o/r", HEAD_SHA="abc", STUB_SHA=stub_sha)
        r = subprocess.run(["bash", "-c", self.script], cwd=self.d, env=env, capture_output=True, text=True)
        return r, out.read_text(encoding="utf-8")

    def test_valid_number_with_matching_head_is_output(self):
        r, out = self.run_step("12\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(out, "number=12\n")

    def test_non_numeric_or_injected_number_is_refused(self):
        for bad in ("12\nfoo=bar", "abc", "1;id"):
            with self.subTest(bad=bad):
                r, out = self.run_step(bad)
                self.assertNotEqual(r.returncode, 0)
                self.assertEqual(out, "")

    def test_no_number_skips_the_comment(self):
        r, out = self.run_step("")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(out, "")

    def test_head_mismatch_skips_the_comment(self):
        r, out = self.run_step("12", stub_sha="zzz")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(out, "")
        self.assertIn("not commenting", r.stdout)

    def test_comment_step_needs_a_verified_number(self):
        text = COMMENT.read_text(encoding="utf-8")
        self.assertRegex(text, r"if: steps\.pr-number\.outputs\.number != ''\n\s+uses: thollander/")


class ActionInputsTest(unittest.TestCase):
    def test_derating_profile_input_is_deprecated(self):
        text = (ROOT / "action.yml").read_text(encoding="utf-8")
        block = re.search(r"^  derating-profile:\n((?:    .*\n)+)", text, re.M).group(1)
        self.assertIn("deprecationMessage:", block)


if __name__ == "__main__":
    unittest.main()
