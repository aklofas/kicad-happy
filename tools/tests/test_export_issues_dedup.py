"""Exported GitHub issues are matched by finding, not by rule: a fake `gh` on PATH serves
recorded `issue list` JSON and records every call."""
import contextlib, hashlib, io, json, os, stat, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
SCRIPT = SCRIPTS / "export_issues.py"

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


def keyed_marker(fid, content):
    return f"<!-- kicad-happy:finding_id={fid} key={hashlib.sha256(content.encode()).hexdigest()[:16]} -->"


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
        self.lists = [c for c in st["calls"] if c[:2] == ["issue", "list"]]
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
        self.assertEqual(self.kv(creates[0], "body").split("\n")[0],
                         keyed_marker("RG-001:bbb", "RG-001::::::Rail Y"))

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
        self.assertTrue(body.split("\n")[0].startswith("<!-- kicad-happy:finding_id=RG-001:bbb key="))

    def test_positional_id_is_matched_as_emitted(self):
        issues = [{"number": 3, "title": "t", "body": marker("DC-DET:x#1")}]
        r, creates = self.run_export([finding("DC-DET:x#1", "other content now")], issues)
        self.assertEqual(creates, [])
        r, creates = self.run_export([finding("DC-DET:x#2", "other content now")], issues)
        self.assertEqual(len(creates), 1)

    def test_same_finding_twice_lists_issues_once(self):
        r, creates = self.run_export(
            [finding("RG-001:aaa", "Rail X"), finding("RG-001:aaa", "Rail X")], [])
        self.assertEqual(len(creates), 1)
        self.assertEqual(len(self.lists), 1)

    def test_unnamed_net_renumbering_does_not_duplicate(self):
        old = {"rule_id": "NR-001", "finding_id": "NR-001:__unnamed_3", "summary": "Net __unnamed_3 floats",
               "nets": ["__unnamed_3"], "components": ["R1"]}
        new = dict(old, finding_id="NR-001:__unnamed_7", summary="Net __unnamed_7 floats",
                   nets=["__unnamed_7"])
        content = "NR-001::__unnamed::R1::Net __unnamed floats"
        issues = [{"number": 4, "title": "t",
                   "body": keyed_marker("NR-001:__unnamed_3", content) + "\n\nbody"}]
        r, creates = self.run_export([new], issues)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(creates, [])
        other = dict(new, summary="Net __unnamed_7 shorts", components=["R2"])
        r, creates = self.run_export([other], issues)
        self.assertEqual(len(creates), 1)

    def test_positional_order_swap_does_not_duplicate(self):
        issues = [
            {"number": 1, "title": "t", "body": keyed_marker("DC-DET:v#1", "DC-DET::+3V3::C1::caps A")},
            {"number": 2, "title": "t", "body": keyed_marker("DC-DET:v#2", "DC-DET::+5V::C2::caps B")},
        ]
        a = {"rule_id": "DC-DET", "nets": ["+3V3"], "components": ["C1"], "summary": "caps A"}
        b = {"rule_id": "DC-DET", "nets": ["+5V"], "components": ["C2"], "summary": "caps B"}
        r, creates = self.run_export(
            [dict(b, finding_id="DC-DET:v#1"), dict(a, finding_id="DC-DET:v#2")], issues)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(creates, [])

    def test_mentions_are_inert(self):
        r, creates = self.run_export([finding("RG-001:aaa", "ping @octocat")], [])
        for call in creates:
            for a in call:
                self.assertNotIn("@octocat", a)
        self.assertIn("@\u200boctocat", self.kv(creates[0], "title"))
        self.assertIn("@\u200boctocat", self.kv(creates[0], "body"))

    def test_full_listing_page_is_refused(self):
        issues = [{"number": i, "title": "t", "body": ""} for i in range(3)]
        sys.path.insert(0, str(SCRIPTS))
        try:
            import export_issues
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as tmp:
            gh = Path(tmp) / "bin" / "gh"
            gh.parent.mkdir()
            gh.write_text(FAKE_GH.format(py=sys.executable), encoding="utf-8")
            gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
            state = Path(tmp) / "state.json"
            state.write_text(json.dumps({"issues": issues, "calls": [], "created": []}),
                             encoding="utf-8")
            data = Path(tmp) / "a.json"
            data.write_text(json.dumps({"findings": [finding("RG-001:aaa", "Rail X")]}),
                            encoding="utf-8")
            env = {"PATH": f"{gh.parent}{os.pathsep}{os.environ['PATH']}",
                   "FAKE_GH_STATE": str(state)}
            err = io.StringIO()
            with mock.patch.dict(os.environ, env), \
                    mock.patch.object(export_issues, "LIST_LIMIT", 3), \
                    contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                rc = export_issues.main([str(data), "--repo", "o/r", "--create"])
            calls = json.loads(state.read_text(encoding="utf-8"))["calls"]
        self.assertEqual(rc, 1)
        self.assertIn("truncated", err.getvalue())
        self.assertFalse([c for c in calls if c[:2] == ["issue", "create"]])

    def test_head_of_a_collision_group_is_not_matched_by_id(self):
        a = {"rule_id": "RG-001", "nets": ["N1"], "components": ["U1"], "summary": "A summary"}
        b = {"rule_id": "RG-001", "nets": ["N2"], "components": ["U1"], "summary": "B summary"}
        # B was filed when it held the bare id; A now sorts first and takes it
        issues = [{"number": 8, "title": "t",
                   "body": keyed_marker("schematic:RG-001:u1", "RG-001::N2::U1::B summary")}]
        r, creates = self.run_export(
            [dict(a, finding_id="schematic:RG-001:u1"),
             dict(b, finding_id="schematic:RG-001:u1#1")], issues)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(creates), 1)
        self.assertEqual(self.kv(creates[0], "title"), "[RG-001] A summary (U1)")

    def nt_pair(self):
        return [{"rule_id": "NT-001", "finding_id": f"NT-001:__unnamed_{n}",
                 "nets": [f"__unnamed_{n}"], "components": ["BV10"],
                 "summary": f"Single-pin net: __unnamed_{n} only connects to BV10"}
                for n in (3, 4)]

    def nt_issues(self, count):
        content = "NT-001::__unnamed::BV10::Single-pin net: __unnamed only connects to BV10"
        return [{"number": i + 1, "title": "t",
                 "body": keyed_marker(f"NT-001:__unnamed_{i + 10}", content)}
                for i in range(count)]

    def test_same_key_findings_are_not_collapsed(self):
        for open_count, expected in ((0, 2), (1, 1), (2, 0)):
            r, creates = self.run_export(self.nt_pair(), self.nt_issues(open_count))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(len(creates), expected, open_count)
        three = self.nt_pair() + [dict(self.nt_pair()[0], finding_id="NT-001:__unnamed_5",
                                       nets=["__unnamed_5"])]
        r, creates = self.run_export(three, [])
        self.assertEqual(len(creates), 3)
        # input order does not change which finding is left to file
        r1, c1 = self.run_export(self.nt_pair(), self.nt_issues(1))
        r2, c2 = self.run_export(self.nt_pair()[::-1], self.nt_issues(1))
        self.assertEqual(self.kv(c1[0], "title"), self.kv(c2[0], "title"))

    def test_values_are_passed_as_one_flag_each(self):
        r, creates = self.run_export([finding("RG-001:aaa", "--web")], [])
        self.assertEqual(creates[0][:2], ["issue", "create"])
        self.assertTrue(all(a.startswith("--") for a in creates[0][2:]), creates[0])
        self.assertEqual(self.kv(creates[0], "title"), "[RG-001] --web")


if __name__ == "__main__":
    unittest.main()
