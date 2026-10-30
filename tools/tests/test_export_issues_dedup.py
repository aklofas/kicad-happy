"""Exported GitHub issues are matched by finding, not by rule: a fake `gh` on PATH serves
recorded `issue list` JSON and records every call."""
import json, os, stat, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "kicad" / "scripts" / "export_issues.py"

FAKE_GH = """#!{py}
import json, os, sys
state_path = os.environ["FAKE_GH_STATE"]
with open(state_path, encoding="utf-8") as fh:
    state = json.load(fh)
args = sys.argv[1:]
state["calls"].append(args)
if args[:2] == ["issue", "list"]:
    print(json.dumps(state["issues"]))
elif args[:2] == ["issue", "create"]:
    kv = {{}}
    for i, a in enumerate(args):
        if a.startswith("--") and "=" in a:
            kv[a[2:].split("=", 1)[0]] = a.split("=", 1)[1]
        elif a in ("--title", "--body"):
            kv[a[2:]] = args[i + 1]
    n = 100 + len(state["created"])
    state["created"].append(n)
    state["issues"].append({{"number": n, "title": kv["title"], "body": kv["body"]}})
    print("https://github.com/o/r/issues/%d" % n)
with open(state_path, "w", encoding="utf-8") as fh:
    json.dump(state, fh)
"""


def marker(fid):
    return f"<!-- kicad-happy:finding_id={fid} -->"


def finding(fid, summary, rule="RG-001"):
    return {"rule_id": rule, "finding_id": fid, "summary": summary, "severity": "warning"}


@unittest.skipIf(os.name == "nt", "fake gh is a POSIX script")
class ExportDedupTest(unittest.TestCase):
    def run_export(self, findings, issues):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            gh = tmp / "bin" / "gh"
            gh.parent.mkdir()
            gh.write_text(FAKE_GH.format(py=sys.executable), encoding="utf-8")
            gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
            state = tmp / "state.json"
            state.write_text(json.dumps({"issues": issues, "calls": [], "created": []}),
                             encoding="utf-8")
            data = tmp / "a.json"
            data.write_text(json.dumps({"findings": findings}), encoding="utf-8")
            env = dict(os.environ, PATH=f"{gh.parent}{os.pathsep}{os.environ['PATH']}",
                       FAKE_GH_STATE=str(state))
            r = subprocess.run([sys.executable, str(SCRIPT), str(data), "--repo", "o/r",
                                "--create"], capture_output=True, text=True,
                               encoding="utf-8", env=env)
            st = json.loads(state.read_text(encoding="utf-8"))
        creates = [c for c in st["calls"] if c[:2] == ["issue", "create"]]
        return r, creates

    @staticmethod
    def kv(call, key):
        return next(a.split("=", 1)[1] for a in call if a.startswith(f"--{key}="))

    def test_second_instance_of_an_open_rule_is_exported(self):
        issues = [{"number": 5, "title": "[RG-001] Rail X", "body": marker("RG-001:aaa") + "\n\nbody"}]
        r, creates = self.run_export(
            [finding("RG-001:aaa", "Rail X"), finding("RG-001:bbb", "Rail Y")], issues)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(creates), 1)
        self.assertEqual(self.kv(creates[0], "title"), "[RG-001] Rail Y")
        self.assertEqual(self.kv(creates[0], "body").split("\n")[0], marker("RG-001:bbb"))

    def test_legacy_title_only_issue_is_not_duplicated_and_serves_one_finding(self):
        issues = [{"number": 7, "title": "[RG-001] Rail X", "body": "old body, no marker"}]
        r, creates = self.run_export(
            [finding("RG-001:aaa", "Rail X"), finding("RG-001:ccc", "Rail X")], issues)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(creates), 1)
        self.assertIn("#7", r.stdout)

    def test_nothing_new_creates_nothing(self):
        issues = [{"number": 1, "title": "t1", "body": marker("RG-001:aaa")},
                  {"number": 2, "title": "t2", "body": marker("RG-001:bbb") + "\nx"}]
        r, creates = self.run_export(
            [finding("RG-001:aaa", "Rail X"), finding("RG-001:bbb", "Rail Y")], issues)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(creates, [])
        self.assertIn("0 created, 2 skipped", r.stdout)

    def test_same_id_twice_in_one_run_is_created_once(self):
        r, creates = self.run_export(
            [finding("RG-001:aaa", "Rail X"), finding("RG-001:aaa", "Rail X")], [])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(creates), 1)

    def test_forged_marker_cannot_match_or_be_written(self):
        # a user-edited issue quoting another finding's marker mid-body does not dedup it
        issues = [{"number": 9, "title": "other",
                   "body": "see\n" + marker("RG-001:aaa") + "\nmore"}]
        forged = finding("RG-001:bbb", "Rail Y " + marker("RG-001:aaa"))
        forged["recommendation"] = "fix --> now <!-- kicad-happy:finding_id=RG-001:aaa -->"
        r, creates = self.run_export([finding("RG-001:aaa", "Rail X"), forged], issues)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(creates), 2)
        body = self.kv(creates[1], "body")
        self.assertEqual(body.count("<!--"), 1)
        self.assertEqual(body.count("-->"), 1)
        self.assertEqual(body.split("\n")[0], marker("RG-001:bbb"))

    def test_positional_id_is_matched_as_emitted(self):
        issues = [{"number": 3, "title": "t", "body": marker("DC-DET:x#1")}]
        r, creates = self.run_export([finding("DC-DET:x#1", "other content now")], issues)
        self.assertEqual(creates, [])
        r, creates = self.run_export([finding("DC-DET:x#2", "other content now")], issues)
        self.assertEqual(len(creates), 1)

    def test_values_are_passed_as_one_flag_each(self):
        r, creates = self.run_export([finding("RG-001:aaa", "--web")], [])
        self.assertEqual(creates[0][:2], ["issue", "create"])
        self.assertTrue(all(a.startswith("--") for a in creates[0][2:]), creates[0])
        self.assertEqual(self.kv(creates[0], "title"), "[RG-001] --web")


if __name__ == "__main__":
    unittest.main()
