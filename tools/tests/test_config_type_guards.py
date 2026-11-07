"""Wrong-typed config values warn and fall back to the default instead of crashing; a suppression
pattern list given as one string is one pattern."""
import io, json, os, subprocess, sys, tempfile, unittest
from contextlib import redirect_stderr
from unittest import mock
from pathlib import Path
from tools.tests._fixtures import fixture_path, have

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
FX = fixture_path("simple-project")
sys.path.insert(0, str(SCRIPTS))

from project_config import _load_and_validate, load_config, matches_suppression  # noqa: E402
from design_intent import resolve_design_intent  # noqa: E402


def _load(cfg):
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, ".kicad-happy.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        err = io.StringIO()
        with redirect_stderr(err):
            out = _load_and_validate(p)
    return out, err.getvalue()


class SuppressionStringTest(unittest.TestCase):
    def test_string_components_is_one_pattern(self):
        sup = {"rule_id": "TS-001", "components": "Q9*"}
        self.assertFalse(matches_suppression({"rule_id": "TS-001", "components": ["U1"]}, sup))
        self.assertTrue(matches_suppression({"rule_id": "TS-001", "components": ["Q91"]}, sup))

    def test_string_nets_is_one_pattern(self):
        sup = {"rule_id": "DC-001", "nets": "+3V3"}
        self.assertFalse(matches_suppression({"rule_id": "DC-001", "nets": ["GND"]}, sup))
        self.assertTrue(matches_suppression({"rule_id": "DC-001", "nets": ["+3V3"]}, sup))

    def test_bare_net_pattern_matches_the_root_sheet_net(self):
        sup = {"rule_id": "DC-001", "nets": "NAME"}
        self.assertTrue(matches_suppression({"rule_id": "DC-001", "nets": ["/NAME"]}, sup))
        self.assertTrue(matches_suppression({"rule_id": "DC-001", "nets": ["/Sheet/NAME"]}, sup))
        self.assertFalse(matches_suppression({"rule_id": "DC-001", "nets": ["/OTHER"]}, sup))

    def test_validator_wraps_a_string_and_warns(self):
        cfg, err = _load({"suppressions": [{"rule_id": "TS-001", "components": "Q9*"}]})
        self.assertEqual(cfg["suppressions"], [{"rule_id": "TS-001", "components": ["Q9*"]}])
        self.assertIn("project_config._load_and_validate", err)

    def test_validator_drops_an_entry_with_a_non_list_pattern(self):
        cfg, err = _load({"suppressions": [{"rule_id": "TS-001", "nets": 7}]})
        self.assertEqual(cfg["suppressions"], [])
        self.assertIn("suppressions[0] ignored", err)

    def test_validator_drops_an_entry_with_a_non_string_pattern(self):
        keep = {"rule_id": "IO-001", "components": ["J1"]}
        cfg, err = _load({"suppressions": [{"rule_id": "IO-001", "components": [1]},
                                           {"rule_id": "IO-001", "nets": [None]}, keep]})
        self.assertEqual(cfg["suppressions"], [keep])
        self.assertEqual(err.count("suppressions[0] ignored"), 1, err)
        self.assertEqual(err.count("suppressions[1] ignored"), 1, err)


class UnreadableConfigTest(unittest.TestCase):
    def _check(self, data):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, ".kicad-happy.json")
            Path(p).write_bytes(data)
            err = io.StringIO()
            with redirect_stderr(err):
                out = _load_and_validate(p)
                cfg = load_config(tmp)
            self.assertIsNone(out)
            self.assertIn("Warning: failed to parse", err.getvalue())
            self.assertEqual(cfg["suppressions"], [])

    def test_non_utf8_file_warns_and_is_skipped(self):
        self._check(b'\xff{"project": {}}')

    def test_deeply_nested_file_warns_and_is_skipped(self):
        self._check(('{"project": ' + "[" * 100000 + "]" * 100000 + "}").encode())


class WrongTypeTest(unittest.TestCase):
    CASES = [
        ({"suppressions": 7}, "suppressions"),
        ({"bom": {"group_by": ["mpn"]}}, "bom.group_by"),
        ({"bom": {"group_by": {"a": 1}}}, "bom.group_by"),
        ({"design_intent": 7}, "design_intent"),
        ({"design_intent": None}, "design_intent"),
        ({"design_intent": {"product_class": ["x"]}}, "design_intent.product_class"),
        ({"design_intent": {"ipc_class": {"a": 1}}}, "design_intent.ipc_class"),
        ({"design_intent": {"target_market": ["x"]}}, "design_intent.target_market"),
        ({"design_intent": {"operating_temp_range": "bogus"}}, "design_intent.operating_temp_range"),
        ({"design_intent": {"test_coverage_target": "high"}}, "design_intent.test_coverage_target"),
        ({"design_intent": {"expected_lifetime_years": [5]}}, "design_intent.expected_lifetime_years"),
        ({"project": {"ambient_temperature_c": "bogus"}}, "project.ambient_temperature_c"),
        ({"project": "bogus"}, "project"),
        ({"project": None}, "project"),
    ]

    def test_each_wrong_type_warns_once_and_resolves(self):
        for cfg, label in self.CASES:
            with self.subTest(label=label, cfg=cfg):
                out, err = _load(cfg)
                self.assertEqual(err.count("Warning:"), 1, err)
                self.assertIn(f"{label} ignored, default used", err)
                resolve_design_intent(out)

    def test_valid_values_pass_unchanged(self):
        cfg = {"design_intent": {"ipc_class": 3, "product_class": "production",
                                 "operating_temp_range": [-40, 85], "test_coverage_target": 0.9},
               "project": {"ambient_temperature_c": 40}, "bom": {"group_by": "mpn"}}
        out, err = _load(json.loads(json.dumps(cfg)))
        self.assertEqual(err, "")
        self.assertEqual(out, cfg)


class ConfigShapeTest(unittest.TestCase):
    def test_null_analysis_warns_and_uses_default(self):
        out, err = _load({"analysis": None})
        self.assertNotIn("analysis", out)
        self.assertIn("project_config._load_and_validate", err)
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, ".kicad-happy.json"), "w", encoding="utf-8") as f:
                json.dump({"analysis": None}, f)
            with redirect_stderr(io.StringIO()):
                cfg = load_config(tmp)
                self.assertEqual(cfg["analysis"]["output_dir"], "analysis")
                from project_config import apply_power_rails_config
                apply_power_rails_config({"VBAT": 3.7}, [], cfg)

    def test_output_dir_outside_the_working_directory_is_dropped(self):
        for bad in ("../../escape", "/tmp/x", "C:\\x", "C:x", "\\\\srv\\share", "a/../b", "a\\..\\b"):
            with self.subTest(bad=bad):
                out, err = _load({"analysis": {"output_dir": bad}})
                self.assertNotIn("output_dir", out["analysis"])
                self.assertIn("analysis.output_dir must be a relative path", err)
        for good in ("build/analysis", "~/x", "a..b"):
            with self.subTest(good=good):
                out, err = _load({"analysis": {"output_dir": good}})
                self.assertEqual((out["analysis"]["output_dir"], err), (good, ""))

    def test_home_config_output_dir_outside_the_working_directory_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as proj:
            with open(os.path.join(home, ".kicad-happy.json"), "w", encoding="utf-8") as f:
                json.dump({"analysis": {"output_dir": "/elsewhere"}}, f)
            err = io.StringIO()
            with mock.patch("os.path.expanduser", return_value=home), redirect_stderr(err):
                cfg = load_config(proj)
            self.assertEqual(cfg["analysis"]["output_dir"], "analysis")
            self.assertIn("analysis.output_dir must be a relative path", err.getvalue())

    def test_non_string_ignore_item_is_dropped(self):
        out, err = _load({"analysis": {"power_rails": {"ignore": ["VBAT", 5], "flag": [None, "V*"]}}})
        pr = out["analysis"]["power_rails"]
        self.assertEqual(pr["ignore"], ["VBAT"])
        self.assertEqual(pr["flag"], ["V*"])
        self.assertIn("non-string entries ignored", err)

    def test_valid_rail_lists_pass_unchanged(self):
        cfg = {"analysis": {"power_rails": {"ignore": ["VBAT"], "flag": ["V*"]}}}
        out, err = _load(json.loads(json.dumps(cfg)))
        self.assertEqual(err, "")
        self.assertEqual(out, cfg)

    def test_bom_config_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, ".kicad-happy.json")
            with open(p, "wb") as f:
                f.write(b"\xef\xbb\xbf" + json.dumps(
                    {"analysis": {"power_rails": {"ignore": ["VBAT"]}}}).encode())
            err = io.StringIO()
            with redirect_stderr(err):
                out = _load_and_validate(p)
        self.assertEqual(out["analysis"]["power_rails"]["ignore"], ["VBAT"])
        self.assertNotIn("failed to parse", err.getvalue())

    def test_bom_kicad_pro_loads(self):
        from kicad_core.project import load_kicad_pro
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "a.kicad_pro")
            with open(p, "wb") as f:
                f.write(b"\xef\xbb\xbf" + json.dumps({"meta": {"version": 1}}).encode())
            self.assertEqual(load_kicad_pro(p), {"meta": {"version": 1}})


@unittest.skipUnless(have(FX), "harness fixtures not present")
class CliTest(unittest.TestCase):
    def _run(self, script, *args, cwd):
        env = dict(os.environ, PYTHONHASHSEED="0", PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([sys.executable, str(SCRIPTS / script), *args], capture_output=True,
                              text=True, encoding="utf-8", cwd=cwd, env=env, timeout=300)

    def test_analyzers_survive_wrong_typed_configs(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("simple.kicad_sch", "simple.kicad_pcb"):
                Path(tmp, name).write_bytes((FX / name).read_bytes())
            for cfg, _label in WrongTypeTest.CASES:
                with self.subTest(cfg=cfg):
                    Path(tmp, ".kicad-happy.json").write_text(json.dumps(cfg), encoding="utf-8")
                    for script, src in (("analyze_schematic.py", "simple.kicad_sch"),
                                        ("analyze_pcb.py", "simple.kicad_pcb")):
                        r = self._run(script, src, "-o", os.path.join(tmp, "o.json"), cwd=tmp)
                        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
                        self.assertNotIn("Traceback", r.stderr)

    def test_thermal_with_a_string_ambient_uses_the_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            sch, pcb = os.path.join(tmp, "sch.json"), os.path.join(tmp, "pcb.json")
            self.assertEqual(self._run("analyze_schematic.py", str(FX / "simple.kicad_sch"), "-o", sch,
                                       cwd=tmp).returncode, 0)
            self.assertEqual(self._run("analyze_pcb.py", str(FX / "simple.kicad_pcb"), "-o", pcb,
                                       cwd=tmp).returncode, 0)
            cfg = os.path.join(tmp, "cfg.json")
            Path(cfg).write_text('{"project":{"ambient_temperature_c":"bogus"}}', encoding="utf-8")
            out = os.path.join(tmp, "t.json")
            r = self._run("analyze_thermal.py", "--schematic", sch, "--pcb", pcb, "--config", cfg,
                          "-o", out, cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("project.ambient_temperature_c ignored, default used", r.stderr)
            with open(out, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["summary"]["ambient_c"], 25.0)

    def test_emc_and_thermal_survive_a_null_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            sch, pcb = os.path.join(tmp, "sch.json"), os.path.join(tmp, "pcb.json")
            self.assertEqual(self._run("analyze_schematic.py", str(FX / "simple.kicad_sch"), "-o", sch,
                                       cwd=tmp).returncode, 0)
            self.assertEqual(self._run("analyze_pcb.py", str(FX / "simple.kicad_pcb"), "-o", pcb,
                                       cwd=tmp).returncode, 0)
            cfg = os.path.join(tmp, "cfg.json")
            Path(cfg).write_text('{"project": null}', encoding="utf-8")
            emc = os.path.join(ROOT, "skills", "emc", "scripts", "analyze_emc.py")
            runs = [subprocess.run([sys.executable, emc, "--schematic", sch, "--pcb", pcb, "--config", cfg,
                                    "-o", os.path.join(tmp, "e.json")], capture_output=True, text=True,
                                   encoding="utf-8", cwd=tmp, timeout=300),
                    self._run("analyze_thermal.py", "--schematic", sch, "--pcb", pcb, "--config", cfg,
                              "-o", os.path.join(tmp, "t.json"), cwd=tmp)]
            for r in runs:
                self.assertEqual(r.returncode, 0, r.stderr[-1500:])
                self.assertNotIn("Traceback", r.stderr)
                self.assertIn("project ignored, default used", r.stderr)


class VoltageOverridesValueTest(unittest.TestCase):
    def test_bool_nan_and_infinity_are_dropped_with_a_warning(self):
        cfg = {"analysis": {"power_rails": {"voltage_overrides": {
            "+5V": float("nan"), "+3V3": True, "+12V": 12, "+1V8": float("inf"),
            "-5V": float("-inf"), "VDD": 1.8, "OFF": False}}}}
        out, err = _load(cfg)
        self.assertEqual(out["analysis"]["power_rails"]["voltage_overrides"],
                         {"+12V": 12, "VDD": 1.8})
        for net in ("+5V", "+3V3", "+1V8", "-5V", "OFF"):
            self.assertIn(f"voltage_overrides.{net} must be a finite number", err)

    def test_context_drops_non_finite_override(self):
        from kicad_types import build_analysis_context
        ctx = build_analysis_context([], {}, {}, power_rails_config={"voltage_overrides": {
            "A": float("nan"), "B": float("inf"), "C": True, "D": 0, "E": 3.3}})
        self.assertEqual(ctx.rail_overrides, {"D": 0, "E": 3.3})


if __name__ == "__main__":
    unittest.main()
