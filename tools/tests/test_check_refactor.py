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


class CompareDirsRoots(unittest.TestCase):
    def test_snapshot_root_substituted_in_keys_and_values(self):
        with tempfile.TemporaryDirectory() as td:
            dirs = []
            for n in ("a", "b"):
                d = Path(td) / n
                d.mkdir()
                root = str(d.resolve())
                doc = {"inputs": {"source_files": [root + "/x/s.json"], "source_hashes": {root + "/x/s.json": "h"}}}
                (d / "o.json").write_text(json.dumps(doc), encoding="utf-8")
                dirs.append(d)
            rep = cr.compare_dirs(dirs[0], dirs[1], set())
            self.assertEqual(rep["total_deltas"], 0)

    def test_substitution_still_detects_real_change(self):
        with tempfile.TemporaryDirectory() as td:
            dirs = []
            for n, h in (("a", "h1"), ("b", "h2")):
                d = Path(td) / n
                d.mkdir()
                (d / "o.json").write_text(json.dumps({"k": {str(d.resolve()) + "/f": h}}), encoding="utf-8")
                dirs.append(d)
            self.assertEqual(cr.compare_dirs(dirs[0], dirs[1], set())["total_deltas"], 1)

    def test_policy_prefix_wildcard(self):
        vol = {"inputs.source_hashes.<SNAP>*"}
        base = {"inputs": {"source_hashes": {"<SNAP>/x__y/schematic.json": "a", "/fix/real.kicad_sch": "h"}}}
        cand = {"inputs": {"source_hashes": {"<SNAP>/x__y/schematic.json": "b", "/fix/real.kicad_sch": "h"}}}
        self.assertEqual(cr.compare_json(base, cand, vol), [])
        cand["inputs"]["source_hashes"]["/fix/real.kicad_sch"] = "changed"
        self.assertEqual(len(cr.compare_json(base, cand, vol)), 1)


class RunSnapshot(unittest.TestCase):
    def test_missing_full_output_is_failure_and_stale_cleared(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            prod, fx, out = td / "prod", td / "fx", td / "out"
            fake = ("import sys\n"
                    "if '--full' in sys.argv: sys.exit(1)\n"
                    "open(sys.argv[sys.argv.index('-o') + 1], 'w').write('{\"ok\": 1}')\n")
            for rel in cr.ANALYZERS.values():
                (prod / rel).parent.mkdir(parents=True, exist_ok=True)
                (prod / rel).write_text(fake, encoding="utf-8")
            (fx / "p").mkdir(parents=True)
            (fx / "p" / "b.kicad_pcb").write_text("(kicad_pcb)", encoding="utf-8")
            slot = out / "p__b.kicad_pcb"
            slot.mkdir(parents=True)
            (slot / "pcb_full.json").write_text("stale", encoding="utf-8")
            stats = cr.run_snapshot(fx, out, prod, {})
            self.assertEqual([f["fixture"] for f in stats["failures"]], ["p/b.kicad_pcb:pcb_full.json"])
            self.assertFalse((slot / "pcb_full.json").exists())
            self.assertTrue((slot / "pcb.json").exists())


class DiscoverFixtures(unittest.TestCase):
    def test_discovers_sch_pcb_and_gerber_dirs(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "p1").mkdir(); (root / "p1" / "a.kicad_sch").write_text("(kicad_sch)", encoding="utf-8")
            (root / "p1" / "a.kicad_pcb").write_text("(kicad_pcb)", encoding="utf-8")
            (root / "p1" / "gerbers").mkdir(); (root / "p1" / "gerbers" / "a-F_Cu.gbr").write_text("G04*", encoding="utf-8")
            (root / "p2").mkdir(); (root / "p2" / "b.kicad_sch").write_text("(kicad_sch)", encoding="utf-8")
            fx = cr.discover_fixtures(root)
            kinds = sorted((f["kind"], f["rel"]) for f in fx)
            self.assertEqual(kinds, [("gerber", "p1/gerbers"), ("pcb", "p1/a.kicad_pcb"),
                                     ("sch", "p1/a.kicad_sch"), ("sch", "p2/b.kicad_sch")])


if __name__ == "__main__":
    unittest.main()
