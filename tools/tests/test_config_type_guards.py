"""Wrong-typed config values warn and fall back to the default instead of crashing; a suppression
pattern list given as one string is one pattern."""
import io, json, os, subprocess, sys, tempfile, unittest
from contextlib import redirect_stderr
from pathlib import Path
from tools.tests._fixtures import fixture_path, have

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
FX = fixture_path("simple-project")
sys.path.insert(0, str(SCRIPTS))

from project_config import _load_and_validate, matches_suppression, resolve_design_intent  # noqa: E402


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

    def test_validator_wraps_a_string_and_warns(self):
        cfg, err = _load({"suppressions": [{"rule_id": "TS-001", "components": "Q9*"}]})
        self.assertEqual(cfg["suppressions"], [{"rule_id": "TS-001", "components": ["Q9*"]}])
        self.assertIn("project_config._load_and_validate", err)

    def test_validator_drops_an_entry_with_a_non_list_pattern(self):
        cfg, err = _load({"suppressions": [{"rule_id": "TS-001", "nets": 7}]})
        self.assertEqual(cfg["suppressions"], [])
        self.assertIn("suppressions[0] ignored", err)


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


if __name__ == "__main__":
    unittest.main()
