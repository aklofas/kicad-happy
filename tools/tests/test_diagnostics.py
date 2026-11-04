"""diagnostics[]: guarded failures are recorded (one stderr line + one record) instead of swallowed,
and every analyzer envelope declares the list as an optional root field."""
import contextlib, io, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
SPICE = ROOT / "skills" / "spice" / "scripts"
for _p in (SCRIPTS, SPICE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

FX = Path(os.environ.get("KH_FIXTURES", "/tmp/harness-pin/tests/fixtures")) / "simple-project"
# The 6a91aaa baseline lives outside the repo (worktree layout only).
ARC = (ROOT.parents[2] / ".superpowers" / "sdd" / "2026-10-14-refactor-arc"
       if len(ROOT.parents) > 2 else None)
OLD_SCH = (ARC / "baseline-6a91aaa" / "simple-project__simple.kicad_sch" / "schematic.json"
           if ARC else None)
SCHEMA_CLIS = (SCRIPTS / "analyze_schematic.py", SCRIPTS / "analyze_pcb.py", SCRIPTS / "analyze_gerbers.py",
               SCRIPTS / "analyze_thermal.py", SCRIPTS / "cross_analysis.py",
               ROOT / "skills" / "emc" / "scripts" / "analyze_emc.py")


def _schema(cli):
    r = subprocess.run([sys.executable, str(cli), "--schema"], capture_output=True, text=True, encoding="utf-8")
    return json.loads(r.stdout)


def _warning_lines(text):
    return [ln for ln in text.splitlines() if ln.startswith("Warning: ")]


class Record(unittest.TestCase):
    def test_record_appends_and_prints_one_line(self):
        from kicad_core.diagnostics import merge, record
        sink, err = [], io.StringIO()
        with contextlib.redirect_stderr(err):
            record(sink, "m.f", KeyError("x" * 300), "thing skipped")
            record(None, "m.g", ValueError("bad"), "other skipped")
        lines = err.getvalue().splitlines()
        self.assertEqual(lines[1], "Warning: m.g: ValueError: bad — other skipped")
        self.assertEqual(len(lines), 2)
        msg = str(KeyError("x" * 300))[:200]
        self.assertEqual(lines[0], f"Warning: m.f: KeyError: {msg} — thing skipped")
        self.assertEqual(sink, [{"source": "m.f", "exception": "KeyError", "message": msg,
                                 "effect": "thing skipped"}])
        self.assertEqual(merge([1], None, [2, 3]), [1, 2, 3])


class EnvelopeSchemas(unittest.TestCase):
    def test_every_envelope_declares_optional_diagnostics(self):
        for cli in SCHEMA_CLIS:
            with self.subTest(cli=cli.name):
                s = _schema(cli)
                self.assertIn("diagnostics", list(s["properties"]))
                self.assertNotIn("diagnostics", s["required"])
                keys = list(s["properties"])
                self.assertEqual(keys[keys.index("compat") + 1], "diagnostics")
        from spice_results import build_report
        self.assertEqual(build_report([])["diagnostics"], [])

    @unittest.skipUnless(OLD_SCH is not None and OLD_SCH.is_file(), "6a91aaa baseline not present")
    def test_old_artifact_without_diagnostics_still_validates(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        old = json.loads(OLD_SCH.read_text(encoding="utf-8"))
        self.assertNotIn("diagnostics", old)
        errors = list(jsonschema.Draft202012Validator(_schema(SCHEMA_CLIS[0])).iter_errors(old))
        self.assertEqual(errors, [])


@unittest.skipUnless((FX / "simple.kicad_sch").is_file(), "frozen fixtures not present")
class PowerRailsGuard(unittest.TestCase):
    def _run(self, patched):
        import analyze_schematic, project_config
        with tempfile.TemporaryDirectory() as d:
            out, err = Path(d) / "s.json", io.StringIO()
            ctx = (mock.patch.object(project_config, "apply_power_rails_config", side_effect=KeyError("x"))
                   if patched else contextlib.nullcontext())
            with ctx, contextlib.redirect_stderr(err):
                rc = analyze_schematic.main([str(FX / "simple.kicad_sch"), "--output", str(out)])
            self.assertEqual(rc, 0)
            return json.loads(out.read_text(encoding="utf-8")), err.getvalue()

    def test_power_rails_guard_becomes_diagnostic(self):
        base, base_err = self._run(False)
        got, got_err = self._run(True)
        self.assertEqual(base["diagnostics"], [])
        self.assertEqual(len(got["diagnostics"]), 1)
        d = got["diagnostics"][0]
        self.assertTrue(d["source"].endswith("finalize_for_cli"), d)
        self.assertEqual((d["exception"], d["message"]), ("KeyError", "'x'"))
        for doc in (base, got):
            for k in ("diagnostics", "flagged_rails", "capability_mode_ref"):
                doc.pop(k, None)
            doc["inputs"].pop("run_id", None)
        self.assertEqual(got, base)
        self.assertEqual(len(_warning_lines(got_err)), len(_warning_lines(base_err)) + 1)
        self.assertEqual(len([ln for ln in _warning_lines(got_err) if "finalize_for_cli" in ln]), 1)


SYNTH = FX.parent / "synthetic_top_level_sheets" / "page1.kicad_sch"


@unittest.skipUnless(SYNTH.is_file(), "frozen fixtures not present")
class PeerSheetGuard(unittest.TestCase):
    def test_peer_sheet_parse_failure_is_one_record_and_one_line(self):
        import schematic.hierarchy as hierarchy
        from schematic.pipeline import analyze_schematic
        real, err = hierarchy.parse_single_sheet, io.StringIO()

        def fail_peers(sheet_path, *a, **k):
            if Path(sheet_path).name != SYNTH.name:
                raise ValueError("bad sheet")
            return real(sheet_path, *a, **k)
        with mock.patch.object(hierarchy, "parse_single_sheet", side_effect=fail_peers), \
                contextlib.redirect_stderr(err):
            result = analyze_schematic(str(SYNTH), no_hierarchy=True)
        recs = [d for d in result["diagnostics"] if d["source"] == "schematic.hierarchy.merge_top_level_sheets"]
        self.assertGreaterEqual(len(recs), 1)
        lines = [ln for ln in err.getvalue().splitlines() if "bad sheet" in ln]
        self.assertEqual(len(lines), len(recs))
        self.assertTrue(all(ln.startswith("Warning: schematic.hierarchy.merge_top_level_sheets: ValueError")
                            for ln in lines), lines)


class GetFacts(unittest.TestCase):
    def test_get_facts_records_lookup_failure(self):
        import lookup_helpers, datasheet_types
        sink, err = [], io.StringIO()
        with mock.patch.object(datasheet_types, "lookup", side_effect=RuntimeError("boom")), \
                contextlib.redirect_stderr(err):
            self.assertIsNone(lookup_helpers.get_facts("LM358", diagnostics=sink))  # no cache dir: a miss
            self.assertEqual(sink, [])
            self.assertIsNone(lookup_helpers.get_facts("LM358", cache_dir=Path(tempfile.gettempdir()),
                                                       diagnostics=sink))
        self.assertEqual(len(sink), 1)
        self.assertEqual(sink[0]["source"], "lookup_helpers.get_facts")
        self.assertEqual((sink[0]["exception"], sink[0]["message"]), ("RuntimeError", "boom"))
        self.assertEqual(len(_warning_lines(err.getvalue())), 1)


class OpampModelFallback(unittest.TestCase):
    def test_opamp_generator_records_model_fallback(self):
        import spice_model_cache, spice_templates
        det = {"configuration": "inverting", "reference": "U1", "value": "LM358", "output_net": "OUT",
               "inverting_input_net": "INN", "non_inverting_input_net": "GND", "gain": -10.0,
               "feedback_resistor": {"ref": "R2", "ohms": 100000.0},
               "input_resistor": {"ref": "R1", "ohms": 10000.0}}
        err = io.StringIO()
        with mock.patch.object(spice_model_cache, "get_model_for_part", side_effect=OSError("no cache")), \
                contextlib.redirect_stderr(err):
            tb = spice_templates.generate_opamp_circuit(det, "out.txt", context={})
        self.assertEqual(tb.extra_vars["model_source"], "ideal")
        self.assertEqual(len(tb.diagnostics), 1)
        self.assertEqual(tb.diagnostics[0]["effect"], "ideal opamp model used")
        self.assertEqual(tb.diagnostics[0]["exception"], "OSError")
        self.assertEqual(len(_warning_lines(err.getvalue())), 1)
        self.assertNotIn("diagnostics", tb.extra_vars)

    def test_once_sink_drops_repeats_silently(self):
        from kicad_core.diagnostics import OnceSink, record
        nominal: list = []
        with contextlib.redirect_stderr(io.StringIO()):
            record(nominal, "m.f", OSError("x"), "fallback used")
        sink = OnceSink(nominal)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            record(sink, "m.f", OSError("x"), "fallback used")
            record(sink, "m.f", OSError("x"), "fallback used")
        self.assertEqual(len(sink), 1)
        self.assertEqual(_warning_lines(err.getvalue()), [])
        plain: list = []
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            record(plain, "m.f", OSError("x"), "fallback used")
            record(plain, "m.f", OSError("x"), "fallback used")
        self.assertEqual(len(plain), 2)
        self.assertEqual(len(_warning_lines(err.getvalue())), 2)

    def test_monte_carlo_trials_report_each_fallback_once(self):
        import spice_model_cache, simulate_subcircuits as ss
        det = {"detector": "detect_opamp_circuits", "configuration": "inverting", "reference": "U1",
               "value": "LM358", "output_net": "OUT", "inverting_input_net": "INN",
               "non_inverting_input_net": "GND", "gain": -10.0,
               "feedback_resistor": {"ref": "R2", "ohms": 100000.0},
               "input_resistor": {"ref": "R1", "ohms": 10000.0}}

        def fake(cmd, **kw):
            out = os.path.join(kw["cwd"], os.path.splitext(cmd[-1])[0] + ".out")
            with open(out, "w", encoding="utf-8") as f:
                f.write("gain_1k=20.0\n")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as wd, \
                mock.patch.object(spice_model_cache, "get_model_for_part", side_effect=OSError("no cache")), \
                mock.patch("spice_simulator.subprocess.run", side_effect=fake), \
                contextlib.redirect_stderr(err):
            report = ss.simulate_subcircuits({"findings": [det]}, workdir=wd, monte_carlo_n=3)
        lines = [ln for ln in _warning_lines(err.getvalue())
                 if ln.startswith("Warning: spice_templates.generate_opamp_circuit")]
        self.assertEqual(len(lines), 1, err.getvalue())
        recs = [d for d in report["diagnostics"] if d["source"] == "spice_templates.generate_opamp_circuit"]
        self.assertEqual(len(recs), 1, report["diagnostics"])
        self.assertTrue(any("tolerance_analysis" in r for r in report["simulation_results"]), report["simulation_results"])


if __name__ == "__main__":
    unittest.main()
