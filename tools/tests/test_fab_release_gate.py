"""The fab release gate reads the keys analyzers write and exits by verdict."""
import json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

from tools.tests._fixtures import fixture

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import fab_release_gate as gate  # noqa: E402


def _run(script, *args):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})


def _dump(tmp, name, data):
    p = os.path.join(tmp, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return p


PASS_SCH = {"statistics": {"total_components": 1, "total_nets": 2, "dnp_parts": 0}}
PASS_PCB = {"connectivity": {"total_nets_with_pads": 2, "unrouted_count": 0,
                             "routing_complete": True},
            "dfm_summary": {"dfm_tier": "standard"},
            "statistics": {"footprint_count": 1, "net_count": 2},
            "silkscreen": {"documentation_warnings": []}}


def _completeness(gerber_data):
    return [c for c in gate.check_gerbers(gerber_data) if c["check_id"] == "layer_completeness"][0]


class GerberCompletenessTest(unittest.TestCase):
    def _analyze_without(self, *names):
        src = fixture("simple-project", "gerbers")
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        dst = os.path.join(tmp, "gerbers")
        shutil.copytree(src, dst)
        for n in names:
            os.remove(os.path.join(dst, n))
        r = _run("analyze_gerbers.py", dst, "--output", os.path.join(tmp, "g.json"))
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(tmp, "g.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_missing_edge_cuts_gbrjob_fails(self):
        c = _completeness(self._analyze_without("simple-Edge_Cuts.gm1"))
        self.assertEqual(c["status"], "fail")
        self.assertIn("Edge.Cuts", c["message"])

    def test_missing_edge_cuts_defaults_fails(self):
        c = _completeness(self._analyze_without("simple-Edge_Cuts.gm1", "simple-job.gbrjob"))
        self.assertEqual(c["status"], "fail")
        self.assertIn("Edge.Cuts", c["message"])

    def test_missing_silk_only_warns(self):
        c = _completeness(self._analyze_without("simple-F_Silkscreen.gto"))
        self.assertEqual(c["status"], "warn")

    def test_missing_inner_copper_fails(self):
        c = _completeness({"completeness": {"source": "gbrjob", "missing": ["In2.Cu"]}})
        self.assertEqual(c["status"], "fail")
        self.assertIn("In2.Cu", c["message"])

    def test_legacy_missing_layers_still_read(self):
        c = _completeness({"completeness": {"missing_layers": ["F.Mask"]}})
        self.assertEqual(c["status"], "fail")

    def test_defaults_recommended_only_warns(self):
        c = _completeness({"completeness": {"source": "defaults", "missing_required": [],
                                            "missing_recommended": ["F.SilkS"]}})
        self.assertEqual(c["status"], "warn")


class EmcThermalTest(unittest.TestCase):
    def _findings(self, n_active, n_suppressed=0):
        return ([{"severity": "error"}] * n_active
                + [{"severity": "error", "suppressed": True}] * n_suppressed)

    def test_emc_counts_active_errors(self):
        c = gate.check_emc({"findings": self._findings(4, 1),
                            "summary": {"by_severity": {"error": 5}}})[0]
        self.assertEqual(c["status"], "warn")
        self.assertEqual(c["details"]["error_count"], 4)

    def test_emc_summary_fallbacks(self):
        c = gate.check_emc({"summary": {"critical": 2}})[0]
        self.assertEqual(c["status"], "warn")
        c = gate.check_emc({"summary": {"by_severity": {"error": 3}}})[0]
        self.assertEqual(c["status"], "warn")

    def test_emc_zero_errors_passes(self):
        c = gate.check_emc({"findings": [{"severity": "warning"}] + self._findings(0, 2),
                            "summary": {"by_severity": {"error": 2}}})[0]
        self.assertEqual(c["status"], "pass")

    def test_thermal_empty_components(self):
        c = gate.check_thermal({"findings": [{"severity": "error", "components": []}]})[0]
        self.assertEqual(c["status"], "fail")
        self.assertIn("?", c["message"])


class ExitCodeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_missing_gerbers_path_is_a_usage_error(self):
        sch = _dump(self.tmp, "s.json", PASS_SCH)
        pcb = _dump(self.tmp, "p.json", PASS_PCB)
        r = _run("fab_release_gate.py", "-s", sch, "-p", pcb,
                 "--gerbers", os.path.join(self.tmp, "nope.json"))
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("nope.json", r.stderr)
        self.assertIn("usage:", r.stderr)

    def test_wrong_analyzer_output_is_a_usage_error(self):
        sch = _dump(self.tmp, "s.json", PASS_SCH)
        pcb = _dump(self.tmp, "p.json", PASS_PCB)
        g = _dump(self.tmp, "g.json", {"analyzer_type": "gerber"})
        r = _run("fab_release_gate.py", "-s", sch, "-p", pcb, "--thermal", g)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("gerber", r.stderr)

    def test_empty_schematic_is_a_usage_error(self):
        sch = _dump(self.tmp, "s.json", {})
        pcb = _dump(self.tmp, "p.json", PASS_PCB)
        r = _run("fab_release_gate.py", "-s", sch, "-p", pcb)
        self.assertEqual(r.returncode, 2, r.stderr)

    def test_empty_optional_input_is_a_usage_error(self):
        sch = _dump(self.tmp, "s.json", PASS_SCH)
        pcb = _dump(self.tmp, "p.json", PASS_PCB)
        empty = _dump(self.tmp, "e.json", {})
        for flag in ("--gerbers", "--thermal", "--emc"):
            with self.subTest(flag=flag):
                r = _run("fab_release_gate.py", "-s", sch, "-p", pcb, flag, empty)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn(f"{flag} {empty}: empty", r.stderr)

    def test_pass_verdict_exits_0(self):
        sch = _dump(self.tmp, "s.json", PASS_SCH)
        pcb = _dump(self.tmp, "p.json", PASS_PCB)
        r = _run("fab_release_gate.py", "-s", sch, "-p", pcb)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["overall_status"], "PASS")

    def test_fail_verdict_exits_1(self):
        proj = fixture("simple-project")
        sch = os.path.join(self.tmp, "s.json")
        pcb = os.path.join(self.tmp, "p.json")
        self.assertEqual(_run("analyze_schematic.py", str(proj / "simple.kicad_sch"),
                              "--output", sch).returncode, 0)
        self.assertEqual(_run("analyze_pcb.py", str(proj / "simple.kicad_pcb"), "--full",
                              "--output", pcb).returncode, 0)
        r = _run("fab_release_gate.py", "-s", sch, "-p", pcb)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(json.loads(r.stdout)["overall_status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
