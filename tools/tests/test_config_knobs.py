"""analysis.retention / diff_threshold / output_dir are honoured; EMC/SPICE cache manifest shape."""
import json, re, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from tools.tests._fixtures import fixture_path, have

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
FX = fixture_path("simple-project")
sys.path.insert(0, str(SCRIPTS))


def run(tree, rel, *args, cwd):
    return subprocess.run([sys.executable, str(Path(tree) / rel), *args], cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8")


def run_dirs(adir):
    return sorted(p.name for p in Path(adir).iterdir() if p.is_dir())


@unittest.skipUnless(have(FX / "simple.kicad_sch"), "frozen fixtures not present")
class ConfigKnobs(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmp.name) / "proj"
        shutil.copytree(FX, self.proj)
        self.sch = self.proj / "simple.kicad_sch"
        self.adir = Path(self._tmp.name) / "adir"

    def tearDown(self):
        self._tmp.cleanup()

    def config(self, analysis):
        (self.proj / ".kicad-happy.json").write_text(json.dumps({"version": 1, "analysis": analysis}),
                                                     encoding="utf-8")

    def set_resistor(self, value):
        # A value change is a component diff, i.e. a "major" change.
        text = self.sch.read_text(encoding="utf-8")
        text = re.sub(r'\(property "Value" "33\d"', f'(property "Value" "{value}"', text, count=1)
        self.sch.write_text(text, encoding="utf-8")

    def add_wire(self, n):
        # A stray wire segment changes statistics.total_wires only, i.e. a "minor" change.
        text = self.sch.read_text(encoding="utf-8").rstrip()
        assert text.endswith(")")
        wire = (f'\t(wire (pts (xy 200 {200 + n}) (xy 210 {200 + n})) (stroke (width 0) (type default)) '
                f'(uuid "00000000-0000-0000-0000-{n:012d}"))\n')
        self.sch.write_text(text[:-1] + wire + ")\n", encoding="utf-8")

    def schematic(self):
        r = run(ROOT, "skills/kicad/scripts/analyze_schematic.py", str(self.sch), "--analysis-dir", str(self.adir),
                cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_retention_default_keeps_every_run(self):
        for v in ("331", "332", "333", "334"):
            self.set_resistor(v)
            self.schematic()
        self.assertEqual(len(run_dirs(self.adir)), 4)

    def test_retention_prunes_unpinned_runs(self):
        from analysis_cache import load_manifest, pin_run
        self.config({"retention": 2})
        self.set_resistor("331")
        self.schematic()
        pinned = load_manifest(str(self.adir))["current"]
        pin_run(str(self.adir), pinned)
        unpinned = []
        for v in ("332", "333", "334"):
            self.set_resistor(v)
            self.schematic()
            unpinned.append(load_manifest(str(self.adir))["current"])
        m = load_manifest(str(self.adir))
        survivors = run_dirs(self.adir)
        self.assertEqual(len(survivors), 3, survivors)
        self.assertIn(pinned, survivors)
        self.assertNotIn(unpinned[0], survivors)
        for run_id in unpinned[1:]:
            self.assertIn(run_id, survivors)
        self.assertEqual(sorted(m["runs"]), survivors)
        self.assertIn(m["current"], survivors)
        self.assertTrue((self.adir / m["current"] / "schematic.json").is_file())

    def test_diff_threshold_all_creates_run_on_minor_change(self):
        self.schematic()
        self.add_wire(1)
        self.schematic()
        self.assertEqual(len(run_dirs(self.adir)), 1)
        self.config({"diff_threshold": "all"})
        self.add_wire(2)
        self.schematic()
        self.assertEqual(len(run_dirs(self.adir)), 2)
        # 'all' is a change level: an unchanged input still overwrites the current run.
        self.schematic()
        self.assertEqual(len(run_dirs(self.adir)), 2)

    def test_output_dir_moves_capability_sidecar(self):
        self.config({"output_dir": "out"})
        for script, src in (("analyze_schematic.py", "simple.kicad_sch"), ("analyze_pcb.py", "simple.kicad_pcb")):
            r = run(ROOT, f"skills/kicad/scripts/{script}", str(self.proj / src), cwd=self.proj)
            self.assertEqual(r.returncode, 0, r.stderr)
        sch_json = self.proj / "sch.json"
        sch_json.write_text(run(ROOT, "skills/kicad/scripts/analyze_schematic.py", str(self.sch),
                                cwd=self.proj).stdout, encoding="utf-8")
        r = run(ROOT, "skills/emc/scripts/analyze_emc.py", "--schematic", str(sch_json), cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.proj / "out" / "capability_mode.json").is_file())
        self.assertFalse((self.proj / "analysis").exists())


class KnobValidation(unittest.TestCase):
    def test_invalid_knob_values_are_dropped_with_a_warning(self):
        import contextlib, io
        from project_config import load_config_from_path
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / ".kicad-happy.json"
            cfg.write_text(json.dumps({"analysis": {"retention": "abc", "diff_threshold": ["x"], "output_dir": "",
                                                    "track_in_git": True}}), encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                analysis = load_config_from_path(str(cfg))["analysis"]
        self.assertEqual(analysis, {"track_in_git": True})
        for knob in ("retention", "diff_threshold", "output_dir"):
            self.assertIn(f"analysis.{knob}", err.getvalue())


@unittest.skipUnless(have(FX / "simple.kicad_sch"), "frozen fixtures not present")
class ManifestShape(unittest.TestCase):
    """emc, emc, spice, corrupt spice, spice against one analysis dir: what each step leaves in manifest.json."""

    @staticmethod
    def _shape(adir):
        # Run ids by order of creation, hashes and timestamps dropped.
        m = json.loads((Path(adir) / "manifest.json").read_text(encoding="utf-8"))
        ids = {rid: f"RUN{i}" for i, rid in enumerate(sorted(m["runs"], key=lambda r: m["runs"][r]["generated"]))}
        return {"current": ids[m["current"]],
                "runs": {ids[rid]: {"outputs": sorted(meta["outputs"]), "scripts": meta["scripts"],
                                    "pinned": meta["pinned"], "hashed": sorted(meta["source_hashes"])}
                         for rid, meta in m["runs"].items()}}

    @unittest.skipUnless(shutil.which("ngspice"), "ngspice not installed")
    def test_emc_and_spice_manifest_steps(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d) / "proj"
            shutil.copytree(FX, proj)
            # sch.json sits beside the .kicad_pro, which a manifest-project lookup would pick up.
            for script, src, out in (("analyze_schematic.py", "simple.kicad_sch", "sch.json"),
                                     ("analyze_pcb.py", "simple.kicad_pcb", "pcb.json")):
                r = run(ROOT, f"skills/kicad/scripts/{script}", str(proj / src), "--output", str(proj / out),
                        cwd=proj)
                self.assertEqual(r.returncode, 0, r.stderr)
            adir = Path(d) / "adir"
            emc = ("skills/emc/scripts/analyze_emc.py", "--schematic", str(proj / "sch.json"),
                   "--pcb", str(proj / "pcb.json"), "--analysis-dir", str(adir))
            spice = ("skills/spice/scripts/simulate_subcircuits.py", "--schematic", str(proj / "sch.json"),
                     "--analysis-dir", str(adir), "--offline")
            shapes = []
            for step, cmd in enumerate((emc, emc, spice, None, spice)):
                if cmd is None:
                    # An unreadable stored spice.json counts as changed, forcing the SPICE create-run path.
                    cur = json.loads((adir / "manifest.json").read_text(encoding="utf-8"))["current"]
                    (adir / cur / "spice.json").write_text("not json", encoding="utf-8")
                    continue
                r = run(ROOT, *cmd, cwd=d)
                self.assertEqual(r.returncode, 0, f"step {step} {cmd[0]}: {r.stderr}")
                shapes.append(self._shape(adir))
            both = ["emc", "spice"]
            one = {"RUN0": {"outputs": ["emc"], "scripts": {"emc": "analyze_emc.py"}, "pinned": False,
                            "hashed": ["pcb.json", "sch.json"]}}
            self.assertEqual(shapes[0], {"current": "RUN0", "runs": one})
            self.assertEqual(shapes[1], shapes[0], "an unchanged EMC rerun updates the current run in place")
            self.assertEqual(shapes[2]["current"], "RUN0")
            self.assertEqual(list(shapes[2]["runs"]), ["RUN0"])
            self.assertEqual(shapes[2]["runs"]["RUN0"]["outputs"], both)
            self.assertEqual(shapes[2]["runs"]["RUN0"]["scripts"], {"emc": "analyze_emc.py"})
            last = shapes[3]
            self.assertEqual(last["current"], "RUN1")
            self.assertEqual(sorted(last["runs"]), ["RUN0", "RUN1"])
            self.assertEqual(last["runs"]["RUN0"], shapes[2]["runs"]["RUN0"])
            self.assertEqual(last["runs"]["RUN1"]["outputs"], both)
            self.assertEqual(last["runs"]["RUN1"]["scripts"], {"spice": "simulate_subcircuits.py"})
            self.assertEqual(len(run_dirs(adir)), 2, "the SPICE create-run path was not exercised")
            self.assertEqual((adir / ".gitignore").read_bytes(),
                             b"# Analysis output -- regenerable from source files\n*\n!.gitignore\n!manifest.json\n")


if __name__ == "__main__":
    unittest.main()
