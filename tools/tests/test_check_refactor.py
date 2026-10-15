import contextlib, io, json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools import check_refactor as cr


class CompareJson(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(cr.compare_json({"a": [1, {"b": None}]}, {"a": [1, {"b": None}]}, set()), [])

    def test_value_change_reports_path(self):
        d = cr.compare_json({"a": {"b": 1}}, {"a": {"b": 2}}, set())
        self.assertEqual(d, [("a.b", "value", 1, 2)])

    def test_absent_vs_null_differ(self):
        d = cr.compare_json({"a": {}}, {"a": {"b": None}}, set())
        self.assertEqual(d, [("a.b", "added", None, None)])

    def test_bool_vs_int_differ(self):
        d = cr.compare_json({"a": True}, {"a": 1}, set())
        self.assertEqual(d[0][:2], ("a", "type"))

    def test_list_order_matters(self):
        d = cr.compare_json({"a": [1, 2]}, {"a": [2, 1]}, set())
        self.assertEqual([x[1] for x in d], ["value", "value"])
        self.assertEqual(d[0][0], "a[0]")

    def test_list_length(self):
        d = cr.compare_json({"a": [1]}, {"a": [1, 2]}, set())
        self.assertEqual(d, [("a", "length", 1, 2)])

    def test_volatile_leaf_masked(self):
        d = cr.compare_json({"inputs": {"run_id": "x"}}, {"inputs": {"run_id": "y"}}, {"inputs.run_id"})
        self.assertEqual(d, [])

    def test_volatile_wildcard_in_list(self):
        d = cr.compare_json({"f": [{"t": 1}, {"t": 2}]}, {"f": [{"t": 9}, {"t": 8}]}, {"f[*].t"})
        self.assertEqual(d, [])

    def test_key_order_reported_separately(self):
        d = cr.compare_json({"a": 1, "b": 2}, {"b": 2, "a": 1}, set())
        self.assertEqual(d, [("", "order", ["a", "b"], ["b", "a"])])


class CompareCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.base = root / "base"
        self.cand = root / "cand"
        (self.base / "sub").mkdir(parents=True)
        self.cand.mkdir()
        (self.base / "a.json").write_text(json.dumps({"x": 1, "inputs": {"run_id": "r1"}}), encoding="utf-8")
        (self.cand / "a.json").write_text(json.dumps({"x": 1, "inputs": {"run_id": "r2"}}), encoding="utf-8")
        (self.base / "sub" / "b.json").write_text(json.dumps({"y": 2}), encoding="utf-8")
        (self.cand / "sub").mkdir()
        (self.cand / "sub" / "b.json").write_text(json.dumps({"y": 2}), encoding="utf-8")
        self.policy = root / "policy.json"
        self.policy.write_text(json.dumps({"volatile_leaves": ["inputs.run_id"]}), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cr.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def argv(self, *extra):
        return ["compare", str(self.base), str(self.cand), "--policy", str(self.policy), *extra]

    def test_identical_dirs_exit_0(self):
        rc, out, _ = self.run_main(self.argv())
        self.assertEqual(rc, 0)
        self.assertIn("compare: OK", out)

    def test_value_change_exit_1(self):
        (self.cand / "a.json").write_text(json.dumps({"x": 9, "inputs": {"run_id": "r2"}}), encoding="utf-8")
        rc, out, _ = self.run_main(self.argv())
        self.assertEqual(rc, 1)
        self.assertIn("a.json: 1 delta(s)", out)
        self.assertIn("value", out)
        self.assertIn("compare: FAIL", out)

    def test_missing_in_candidate_exit_1(self):
        (self.cand / "sub" / "b.json").unlink()
        rc, out, _ = self.run_main(self.argv())
        self.assertEqual(rc, 1)
        self.assertIn("MISSING in candidate: sub/b.json", out)

    def test_extra_in_candidate_exit_1(self):
        (self.cand / "new.json").write_text("{}", encoding="utf-8")
        rc, out, _ = self.run_main(self.argv())
        self.assertEqual(rc, 1)
        self.assertIn("EXTRA in candidate: new.json", out)

    def test_json_output_shape(self):
        (self.cand / "a.json").write_text(json.dumps({"x": 9, "inputs": {"run_id": "r2"}}), encoding="utf-8")
        rc, out, _ = self.run_main(self.argv("--json"))
        self.assertEqual(rc, 1)
        report = json.loads(out)
        self.assertEqual(report["total_deltas"], 1)
        self.assertEqual(report["files"]["a.json"], [["x", "value", 1, 9]])
        self.assertEqual(report["missing_in_candidate"], [])
        self.assertEqual(report["extra_in_candidate"], [])

    def test_missing_base_dir_exit_2(self):
        rc, _, err = self.run_main(["compare", str(self.base / "nope"), str(self.cand), "--policy", str(self.policy)])
        self.assertEqual(rc, 2)
        self.assertIn("base", err)

    def test_missing_cand_dir_exit_2(self):
        rc, _, err = self.run_main(["compare", str(self.base), str(self.cand / "nope"), "--policy", str(self.policy)])
        self.assertEqual(rc, 2)
        self.assertIn("cand", err)

    def test_base_without_json_exit_2(self):
        empty = Path(self._tmp.name) / "empty"
        empty.mkdir()
        rc, _, err = self.run_main(["compare", str(empty), str(self.cand), "--policy", str(self.policy)])
        self.assertEqual(rc, 2)
        self.assertIn("no *.json", err)

    def test_missing_policy_exit_2(self):
        rc, _, err = self.run_main(["compare", str(self.base), str(self.cand), "--policy", str(self.policy) + ".nope"])
        self.assertEqual(rc, 2)
        self.assertIn("policy", err)

    def test_malformed_policy_exit_2(self):
        self.policy.write_text("{not json", encoding="utf-8")
        rc, _, err = self.run_main(self.argv())
        self.assertEqual(rc, 2)
        self.assertIn("policy", err)


if __name__ == "__main__":
    unittest.main()
