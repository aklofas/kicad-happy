import contextlib, importlib.util, io, json, subprocess, sys, tempfile, unittest
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

    def test_aba_builtin_kicad10_pair_differs_in_sorted_position_of_common(self):
        self.assertIn('(net "COMMON")', cr.KICAD10_BOARD_A)
        self.assertIn('(net "AAA")', cr.KICAD10_BOARD_B)
        self.assertNotIn('(net 1', cr.KICAD10_BOARD_A)  # name-keyed: no numeric declarations
        self.assertIn("pcb10", cr.ABA_PROGRAM)


class ImportRules(unittest.TestCase):
    def _tree(self, td):
        root = Path(td)
        for rel, body in {
            "skills/kicad/scripts/kicad_utils.py": "import os\n",
            "skills/kicad/scripts/kicad_core/__init__.py": "",
            "skills/kicad/scripts/kicad_core/fields.py": "import re\nfrom kicad_core import values\n",
            "skills/kicad/scripts/kicad_core/bad.py": "import kicad_utils\n",
            "skills/emc/scripts/emc_rules.py": "from kicad_utils import parse_value\n",
            "skills/emc/scripts/emc_spice.py": "from spice_simulator import NgspiceBackend\n",
            "skills/spice/scripts/spice_simulator.py": "import json\n",
            "skills/bom/scripts/bom_manager.py": "import analyze_schematic\n",
        }.items():
            p = root / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(body, encoding="utf-8")
        return root

    def test_classifies_three_rule_kinds(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            rules = json.loads((cr.TOOLS_DIR / "layer_rules.json").read_text(encoding="utf-8"))
            v = cr.classify_edges(cr.scan_imports(root), rules, root)
            got = sorted((x["file"], x["rule"]) for x in v)
            self.assertEqual(got, [
                ("skills/bom/scripts/bom_manager.py", "no-cli-import"),
                ("skills/emc/scripts/emc_spice.py", "optional-to-optional"),
                ("skills/kicad/scripts/kicad_core/bad.py", "core-package-stdlib-only"),
            ])

    def test_same_directory_module_is_same_skill(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for rel, body in {
                "skills/aaa/scripts/helper.py": "import os\n",
                "skills/aaa/scripts/a_main.py": "import helper\n",
                "skills/bbb/scripts/helper.py": "import os\n",
                "skills/bbb/scripts/b_main.py": "import helper\n",
            }.items():
                p = root / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(body, encoding="utf-8")
            rules = json.loads((cr.TOOLS_DIR / "layer_rules.json").read_text(encoding="utf-8"))
            self.assertEqual(cr.classify_edges(cr.scan_imports(root), rules, root), [])

    def test_exception_suppresses_only_its_violation(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            rules = json.loads((cr.TOOLS_DIR / "layer_rules.json").read_text(encoding="utf-8"))
            rules["exceptions"] = [{"file": "skills/kicad/scripts/kicad_core/bad.py",
                                    "module": "kicad_utils", "rule": "core-package-stdlib-only"}]
            got = sorted((x["file"], x["rule"]) for x in cr.classify_edges(cr.scan_imports(root), rules, root))
            self.assertEqual(got, [
                ("skills/bom/scripts/bom_manager.py", "no-cli-import"),
                ("skills/emc/scripts/emc_spice.py", "optional-to-optional"),
            ])
            rules["exceptions"][0]["rule"] = "no-cli-import"  # wrong rule: must not suppress
            self.assertEqual(len(cr.classify_edges(cr.scan_imports(root), rules, root)), 3)


class TagScan(unittest.TestCase):
    def _scan(self, body):
        import textwrap
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "skills" / "kicad" / "scripts" / "x.py"; p.parent.mkdir(parents=True)
            p.write_text(textwrap.dedent(body), encoding="utf-8")
            return cr.scan_tags(Path(td))

    def test_direct_make_finding_flagged(self):
        sites = self._scan('''
            def f():
                make_finding(detector="d", rule_id="R-001", category="c", summary="s", schema_era="v1.4")
                make_finding(detector=Det.X, rule_id="R-002", category="c", summary="s")
        ''')
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0]["nonliteral"], ["detector"])
        self.assertEqual(sites[0]["missing"], ["schema_era"])

    def test_literal_wrapper_and_callers_not_flagged(self):
        sites = self._scan('''
            def _make_ex(a):
                return make_finding(detector="d", rule_id="R-1", schema_era="v1.4", summary=a)
            def f():
                _make_ex("a"); _make_ex("b")
        ''')
        self.assertEqual(sites, [])

    def test_nonliteral_wrapper_flags_inner_not_callers(self):
        sites = self._scan('''
            def _make_ex(a):
                return make_finding(detector=a, rule_id="R-1", schema_era="v1.4")
            def f():
                _make_ex("a")
        ''')
        self.assertEqual([(s["callee"], s["nonliteral"]) for s in sites], [("make_finding", ["detector"])])

    def test_non_factory_make_never_flagged(self):
        sites = self._scan('''
            def _make_label(x):
                return str(x)
            def f():
                _make_label("a")
        ''')
        self.assertEqual(sites, [])

    def test_dict_factory_callers_are_scanned(self):
        sites = self._scan('''
            def _make_d(a):
                return {"detector": a}
            def f():
                _make_d(detector="x", rule_id="R", schema_era="v1")
                _make_d("a")
        ''')
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0]["missing"], ["detector", "rule_id", "schema_era"])


class StableKeys(unittest.TestCase):
    SRC = (
        "class K:\n"
        "    def m(self):\n"
        "        make_finding(detector='d', rule_id='R')\n"
        "        make_finding(detector='d', rule_id='R2')\n"
        "def g():\n"
        "    make_finding(detector='d', rule_id='R')\n"
        "make_finding(detector='d')\n"
    )

    def _tags(self, src):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "skills" / "kicad" / "scripts" / "x.py"; p.parent.mkdir(parents=True)
            p.write_text(src, encoding="utf-8")
            return cr.scan_tags(Path(td))

    def test_tag_keys_survive_line_shift(self):
        a = [cr._tag_key(s) for s in self._tags(self.SRC)]
        b = [cr._tag_key(s) for s in self._tags("\n" * 10 + self.SRC)]
        self.assertEqual(a, b)
        self.assertEqual(len(a), 4)

    def test_same_callee_in_one_function_gets_ordinals(self):
        sites = self._tags(self.SRC)
        k = [(s["function"], s["ordinal"]) for s in sites]
        self.assertEqual(k, [("K.m", 0), ("K.m", 1), ("g", 0), ("<module>", 0)])

    def test_import_repeat_gets_distinct_keys(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for rel, body in {
                "skills/aaa/scripts/a.py": "import os\n",
                "skills/bbb/scripts/b.py": "import a\ndef f():\n    import a\n",
            }.items():
                p = root / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(body, encoding="utf-8")
            rules = json.loads((cr.TOOLS_DIR / "layer_rules.json").read_text(encoding="utf-8"))
            v = cr.classify_edges(cr.scan_imports(root), rules, root)
            keys = [cr._import_key(x) for x in v]
            self.assertEqual(len(keys), 2)
            self.assertEqual(len(set(keys)), 2)
            base = Path(td) / "b.json"
            base.write_text(json.dumps(v[:1]), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cr._ratchet(v, base, False, (), key_fn=cr._import_key), 1)


class Ratchet(unittest.TestCase):
    KEYS = ("file", "callee", "line")

    def test_moved_from_accepts_relocated_shapes_only(self):
        base = [{"file": "a.py", "function": "f", "callee": "make_finding", "ordinal": 0, "line": 1,
                 "missing": ["schema_era"], "nonliteral": []}]
        moved = [{"file": "b.py", "function": "f", "callee": "make_finding", "ordinal": 0, "line": 9,
                  "missing": ["schema_era"], "nonliteral": []}]
        grown = moved + [{"file": "b.py", "function": "g", "callee": "make_finding", "ordinal": 0, "line": 20,
                          "missing": ["schema_era"], "nonliteral": []}]
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
            p = Path(d) / "tag_baseline.json"
            p.write_text(json.dumps(base), encoding="utf-8")
            self.assertEqual(cr._ratchet(moved, p, True, (), key_fn=cr._tag_key, moved_from=("a.py",)), 0)
            self.assertEqual(json.loads(p.read_text())[0]["file"], "b.py")
            p.write_text(json.dumps(base), encoding="utf-8")
            self.assertEqual(cr._ratchet(grown, p, True, (), key_fn=cr._tag_key, moved_from=("a.py",)), 1)
            self.assertEqual(cr._ratchet(moved, p, True, (), key_fn=cr._tag_key, moved_from=()), 1)

    def test_moved_from_rejects_same_count_wrong_shape(self):
        base = [{"file": "a.py", "function": "f", "callee": "make_finding", "ordinal": 0, "line": 1,
                 "missing": ["schema_era"], "nonliteral": []}]
        wrong = [{"file": "b.py", "function": "f", "callee": "make_finding", "ordinal": 0, "line": 9,
                  "missing": ["rule_id"], "nonliteral": []}]
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
            p = Path(d) / "tag_baseline.json"
            p.write_text(json.dumps(base), encoding="utf-8")
            self.assertEqual(cr._ratchet(wrong, p, True, (), key_fn=cr._tag_key, moved_from=("a.py",)), 1)
            self.assertEqual(json.loads(p.read_text()), base)

    def test_moved_from_relocates_import_shape(self):
        def edge(file, line):
            return {"file": file, "line": line, "module": "analyze_schematic", "ordinal": 0, "rule": "no-cli-import"}
        base = [edge("a.py", 3)]
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
            p = Path(d) / "import_baseline.json"
            p.write_text(json.dumps(base), encoding="utf-8")
            self.assertEqual(cr._ratchet([edge("b.py", 7)], p, True, (), key_fn=cr._import_key, moved_from=("a.py",)), 0)
            self.assertEqual(json.loads(p.read_text())[0]["file"], "b.py")

    def test_moved_from_requires_update_baseline(self):
        r = subprocess.run([sys.executable, str(cr.__file__), "tags", "--moved-from", "x.py"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--moved-from requires --update-baseline", r.stderr)

    def _site(self, line):
        return {"file": "a.py", "line": line, "callee": "make_finding", "missing": ["schema_era"], "nonliteral": []}

    def _run(self, current, path, update=False):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cr._ratchet(current, path, update, self.KEYS)
        return rc, buf.getvalue()

    def _baseline(self, td, sites):
        path = Path(td) / "b.json"
        path.write_text(json.dumps(sites), encoding="utf-8")
        return path

    def test_no_change_passes(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._baseline(td, [self._site(1)])
            rc, out = self._run([self._site(1)], path)
            self.assertEqual(rc, 0); self.assertIn("OK (1 known, 0 retired", out)

    def test_new_entry_fails_and_prints(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._baseline(td, [self._site(1)])
            rc, out = self._run([self._site(1), self._site(2)], path)
            self.assertEqual(rc, 1)
            self.assertIn("NEW a.py:2 make_finding", out); self.assertIn("missing=schema_era", out)
            self.assertIn("FAIL (1 new", out)

    def test_new_entry_with_update_does_not_rewrite(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._baseline(td, [self._site(1)])
            rc, _ = self._run([self._site(1), self._site(2)], path, update=True)
            self.assertEqual(rc, 1)
            self.assertEqual(len(json.loads(path.read_text(encoding="utf-8"))), 1)

    def test_shrink_passes_and_counts_retired(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._baseline(td, [self._site(1), self._site(2)])
            rc, out = self._run([self._site(1)], path)
            self.assertEqual(rc, 0); self.assertIn("1 retired since baseline", out)
            self.assertEqual(len(json.loads(path.read_text(encoding="utf-8"))), 2)  # not rewritten

    def test_update_rewrites_when_nothing_new(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._baseline(td, [self._site(1), self._site(2)])
            rc, out = self._run([self._site(1)], path, update=True)
            self.assertEqual(rc, 0); self.assertIn("updated (1 entries, 1 retired)", out)
            self.assertEqual(len(json.loads(path.read_text(encoding="utf-8"))), 1)

    def test_first_generation_creates_baseline(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "new.json"
            rc, _ = self._run([self._site(1)], path, update=True)
            self.assertEqual(rc, 0)
            self.assertEqual(len(json.loads(path.read_text(encoding="utf-8"))), 1)

    def test_missing_baseline_without_update_fails(self):
        with tempfile.TemporaryDirectory() as td:
            rc, _ = self._run([self._site(1)], Path(td) / "none.json")
            self.assertEqual(rc, 1)


class InstallSmoke(unittest.TestCase):
    def test_core_only_help_from_unrelated_cwd(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            failures = cr.install_smoke(cr.REPO_ROOT, None, Path(td))
            self.assertEqual(failures, [], "\n".join(failures))


class QuickJson(unittest.TestCase):
    def test_json_parseable_and_text_summary(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cr.main(["quick", "--json"])
        data = json.loads(buf.getvalue())
        self.assertIn(data["status"], ("ok", "fail"))
        self.assertEqual([c["name"] for c in data["checks"]], ["imports", "tags", "install-smoke"])
        for c in data["checks"]:
            self.assertIn(c["status"], ("ok", "fail"))
            self.assertIsInstance(c["elapsed_s"], float)
            self.assertIsInstance(c["detail"], str)
        self.assertIsNone(data["fixtures_digest"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cr.main(["quick"])
        self.assertTrue(buf.getvalue().rstrip("\n").splitlines()[-1].startswith("quick: "))


FX_REAL = Path("/tmp/harness-pin/tests/fixtures")


def _run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cr.main(argv)
    return rc, out.getvalue(), err.getvalue()


class FailClosed(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.empty = self.root / "empty"
        self.empty.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_snapshot_missing_fixtures_exit_2(self):
        rc, _, err = _run_main(["snapshot", "--fixtures", str(self.root / "typo"), "--out", str(self.root / "o")])
        self.assertEqual(rc, 2)
        self.assertIn("fixtures", err)

    def test_snapshot_empty_fixtures_exit_2(self):
        rc, _, err = _run_main(["snapshot", "--fixtures", str(self.empty), "--out", str(self.root / "o")])
        self.assertEqual(rc, 2)
        self.assertIn("no fixtures", err)

    def test_snapshot_bad_product_exit_2(self):
        (self.empty / "a.kicad_sch").write_text("x", encoding="utf-8")
        rc, _, err = _run_main(["snapshot", "--fixtures", str(self.empty), "--out", str(self.root / "o"),
                                "--product", str(self.root / "nope")])
        self.assertEqual(rc, 2)
        self.assertIn("product", err)

    def test_determinism_missing_and_empty_exit_2(self):
        for fx in (self.root / "typo", self.empty):
            rc, _, _ = _run_main(["determinism", "--fixtures", str(fx)])
            self.assertEqual(rc, 2)

    def test_quick_zero_input_reproduction_exit_2(self):
        rc, out, err = _run_main(["quick", "--fixtures", "/nonexistent/fx", "--baseline", "/nonexistent/base", "--json"])
        self.assertEqual(rc, 2)
        self.assertIn("fixtures", err)

    def test_quick_baseline_without_fixtures_exit_2(self):
        rc, _, err = _run_main(["quick", "--baseline", str(self.empty)])
        self.assertEqual(rc, 2)
        self.assertIn("--baseline requires --fixtures", err)

    def test_quick_empty_fixtures_exit_2(self):
        rc, _, _ = _run_main(["quick", "--fixtures", str(self.empty)])
        self.assertEqual(rc, 2)

    def test_cmp_guard_missing_base_is_error(self):
        rc, base_rc = cr._check_base_dir(self.root / "none"), None
        self.assertIsNotNone(rc)
        self.assertIsNotNone(cr._check_base_dir(self.empty))
        (self.empty / "a.json").write_text("{}", encoding="utf-8")
        self.assertIsNone(cr._check_base_dir(self.empty))


class FixturesDigest(unittest.TestCase):
    def _tree(self, root, payload=b"abc"):
        (root / "a").mkdir(parents=True)
        (root / "a" / "x.kicad_sch").write_bytes(payload)
        g = root / "g"
        g.mkdir()
        (g / "t.gtl").write_bytes(b"gerber")

    def test_content_identity_ignores_mtime(self):
        import os
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            r1, r2 = Path(t1) / "f", Path(t2) / "f"
            self._tree(r1)
            self._tree(r2)
            os.utime(r2 / "a" / "x.kicad_sch", (1, 1))
            os.utime(r2 / "g" / "t.gtl", (5, 5))
            self.assertEqual(cr._fixtures_digest(r1), cr._fixtures_digest(r2))
            (r2 / "a" / "x.kicad_sch").write_bytes(b"abd")
            self.assertNotEqual(cr._fixtures_digest(r1), cr._fixtures_digest(r2))
            (r2 / "a" / "x.kicad_sch").write_bytes(b"abc")
            (r2 / "g" / "t.gtl").write_bytes(b"gerbeR")
            self.assertNotEqual(cr._fixtures_digest(r1), cr._fixtures_digest(r2))


class NormPathAndRoot(unittest.TestCase):
    def test_unbalanced_bracket_key_compares(self):
        d = cr.compare_json({"FOO[": 1}, {"FOO[": 2}, set())
        self.assertEqual(d, [("FOO[", "value", 1, 2)])
        self.assertEqual(cr._norm_path("FOO["), "FOO[")

    def test_key_with_digit_bracket_compares_without_policy(self):
        d = cr.compare_json({"D[0]": 1}, {"D[0]": 2}, set())
        self.assertEqual(d, [("D[0]", "value", 1, 2)])
        self.assertEqual(cr._norm_path("a[12].b[x]"), "a[*].b[x]")

    def test_substitute_requires_separator(self):
        self.assertEqual(cr._substitute_root("/tmp/snap2/x", "/tmp/snap"), "/tmp/snap2/x")
        self.assertEqual(cr._substitute_root("/tmp/snap/x", "/tmp/snap"), "<SNAP>/x")
        self.assertEqual(cr._substitute_root("/tmp/snap", "/tmp/snap"), "<SNAP>")

    def test_substitute_handles_resolved_form(self):
        with tempfile.TemporaryDirectory() as td:
            real = Path(td).resolve() / "real"
            real.mkdir()
            link = Path(td).resolve() / "link"
            link.symlink_to(real)
            a = cr._substitute_root({"p": str(real / "f")}, str(real))
            b = cr._substitute_root({"p": str(real / "f")}, str(link), str(real))
            self.assertEqual(a, b)
            self.assertEqual(b, {"p": "<SNAP>/f"})
            self.assertEqual(cr._substitute_root(str(link / "f"), str(link), str(real)), "<SNAP>/f")


class QuickRobustness(unittest.TestCase):
    def test_raising_check_recorded_as_error(self):
        orig = cr.install_smoke
        def boom(*a, **k):
            raise FileNotFoundError("gone")
        cr.install_smoke = boom
        try:
            rc, out, _ = _run_main(["quick", "--json"])
        finally:
            cr.install_smoke = orig
        self.assertEqual(rc, 1)
        data = json.loads(out)
        self.assertEqual(data["status"], "fail")
        smoke = [c for c in data["checks"] if c["name"] == "install-smoke"][0]
        self.assertEqual(smoke["status"], "error")
        self.assertIn("gone", smoke["detail"])

    def test_install_smoke_timeout_is_failure_line(self):
        import subprocess
        orig = subprocess.run
        def to(*a, **k):
            raise subprocess.TimeoutExpired(a[0], 1)
        subprocess.run = to
        try:
            with tempfile.TemporaryDirectory() as td:
                f = cr.install_smoke(cr.REPO_ROOT, None, Path(td))
        finally:
            subprocess.run = orig
        self.assertTrue(f and all("timeout" in x for x in f))


class ProductShaAndParse(unittest.TestCase):
    def test_sha_dirty_and_unknown(self):
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(cr._git_sha(Path(td)), "unknown")
            subprocess.run(["git", "init", "-q", td], check=True)
            subprocess.run(["git", "-C", td, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                            "--allow-empty", "-m", "x"], check=True)
            clean = cr._git_sha(Path(td))
            self.assertFalse(clean.endswith("-dirty"))
            (Path(td) / "f.txt").write_text("x", encoding="utf-8")
            self.assertEqual(cr._git_sha(Path(td)), clean + "-dirty")

    def _tree(self, td):
        (Path(td) / "skills" / "kicad").mkdir(parents=True)
        (Path(td) / "skills" / "kicad" / "bad.py").write_text("def (:\n", encoding="utf-8")

    def test_imports_and_tags_report_parse_errors(self):
        with tempfile.TemporaryDirectory() as td:
            self._tree(td)
            for cmd in ("imports", "tags"):
                rc, out, _ = _run_main([cmd, "--product", td])
                self.assertEqual(rc, 1)
                self.assertIn("PARSE-ERROR skills/kicad/bad.py", out)

    def test_imports_lists_each_exception(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "skills").mkdir()
            _, out, _ = _run_main(["imports", "--product", td])
            self.assertIn("exceptions: 0 listed", out)

    def test_install_smoke_core_skill_not_double_copied(self):
        with tempfile.TemporaryDirectory() as td:
            f = cr.install_smoke(cr.REPO_ROOT, "kicad", Path(td))
            self.assertEqual(f, [], "\n".join(f))


@unittest.skipUnless(FX_REAL.is_dir(), "frozen fixtures not available")
class AbaReal(unittest.TestCase):
    def test_aba_passes_on_real_fixtures(self):
        rc, out, err = _run_main(["aba", "--fixtures", str(FX_REAL)])
        self.assertEqual(rc, 0, out + err)

    def test_aba_relative_paths(self):
        import os
        old = os.getcwd()
        os.chdir("/tmp")
        try:
            rc, out, err = _run_main(["aba", "--product", os.path.relpath(str(cr.REPO_ROOT), "/tmp"),
                                      "--fixtures", os.path.relpath(str(FX_REAL), "/tmp")])
        finally:
            os.chdir(old)
        self.assertEqual(rc, 0, out + err)

    def test_aba_zero_input_exit_2(self):
        rc, _, _ = _run_main(["aba", "--fixtures", "/nonexistent/fx"])
        self.assertEqual(rc, 2)


class KeptCompatibilitySurfaces(unittest.TestCase):
    """Facade-register entries that must keep accepting the old keyword until the harness migrates."""
    def setUp(self):
        sys.path.insert(0, str(cr.REPO_ROOT / "skills" / "kicad" / "scripts"))

    def test_make_finding_ignores_design_context(self):
        from finding_schema import make_finding
        f = make_finding(detector="d", rule_id="X-001", category="c", summary="s", description="d",
                         design_context={"severity_overrides": {"X-001": "info"}})
        self.assertEqual(f["severity"], "warning")
        self.assertNotIn("design_context", f)

    def test_analysis_context_accepts_retired_fields(self):
        from kicad_types import AnalysisContext
        ctx = AnalysisContext(components=[], nets={}, lib_symbols={}, pin_net={},
                              hierarchy_context=None, design_context={"x": 1})
        self.assertIsNone(ctx.hierarchy_context)


class KicadUtilsFacade(unittest.TestCase):
    def test_every_pre_v3_name_still_importable(self):
        sys.path.insert(0, str(cr.REPO_ROOT / "skills" / "kicad" / "scripts"))
        import importlib, kicad_utils
        importlib.reload(kicad_utils)
        names = json.loads((Path(__file__).parent / "kicad_utils_names_6a91aaa.json").read_text(encoding="utf-8"))
        missing = [n for n in names if not hasattr(kicad_utils, n)]
        self.assertEqual(missing, [])


class SexpParserFacade(unittest.TestCase):
    def test_sexp_parser_facade_exports_every_pre_v3_name(self):
        names = json.loads((Path(__file__).parent / "sexp_parser_names_8912a5a.json").read_text(encoding="utf-8"))
        sys.path.insert(0, str(cr.REPO_ROOT / "skills" / "kicad" / "scripts"))
        import sexp_parser, kicad_core.sexp as core
        for n in names:
            self.assertIs(getattr(sexp_parser, n), getattr(core, n), n)


class SkillLocalResources(unittest.TestCase):
    """merge_results hard-imports jsonschema; run with the harness venv python if bare python3 lacks it."""

    @unittest.skipUnless(importlib.util.find_spec("jsonschema"), "jsonschema not installed")
    def test_merge_results_resolves_persisted_plan_paths_inside_the_skill(self):
        sys.path.insert(0, str(cr.REPO_ROOT / "skills" / "datasheets" / "scripts"))
        import merge_results as mr
        p = mr.resolve_skill_resource("skills/datasheets/schemas/base.schema.json")
        self.assertEqual(p, cr.REPO_ROOT / "skills" / "datasheets" / "schemas" / "base.schema.json")
        self.assertTrue(p.exists())
        self.assertEqual(mr.SCHEMA_DIR, cr.REPO_ROOT / "skills" / "datasheets" / "schemas")


if __name__ == "__main__":
    unittest.main()
