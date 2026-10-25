"""analysis.retention / diff_threshold / output_dir are honoured; EMC/SPICE cache bytes unchanged."""
import json, os, re, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from tools.tests._fixtures import fixture_path, have

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
FX = fixture_path("simple-project")
# Frozen pre-change export (git archive 0490c49) for the manifest-bytes comparison.
OLD = Path(os.environ.get("KH_OLD_TREE", "/tmp/kh-r8"))
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


def _normalise(manifest_text):
    """Replace run ids by ordinals and blank timestamps; everything else stays byte-for-byte."""
    m = json.loads(manifest_text)
    ids = {rid: f"RUN{i}" for i, rid in enumerate(sorted(m["runs"], key=lambda r: m["runs"][r]["generated"]))}
    for meta in m["runs"].values():
        meta["generated"] = "T"
    text = manifest_text
    for rid in sorted(ids, key=len, reverse=True):
        text = text.replace(f'"{rid}"', f'"{ids[rid]}"')
    return re.sub(r'"generated": "[^"]*"', '"generated": "T"', text)


@unittest.skipUnless(have(FX / "simple.kicad_sch") and (OLD / "skills/emc/scripts/analyze_emc.py").is_file(),
                     "frozen fixtures or the pre-change export not present")
class ManifestBytes(unittest.TestCase):
    def test_emc_and_spice_manifest_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d) / "proj"
            shutil.copytree(FX, proj)
            # Inputs produced once, so both trees hash identical bytes. sch.json sits beside the
            # .kicad_pro, which a manifest-project lookup would pick up.
            for script, src, out in (("analyze_schematic.py", "simple.kicad_sch", "sch.json"),
                                     ("analyze_pcb.py", "simple.kicad_pcb", "pcb.json")):
                r = run(ROOT, f"skills/kicad/scripts/{script}", str(proj / src), "--output", str(proj / out),
                        cwd=proj)
                self.assertEqual(r.returncode, 0, r.stderr)
            manifests = {}
            for label, tree in (("old", OLD), ("new", ROOT)):
                adir = Path(d) / f"adir-{label}"
                steps = [
                    ("emc", ("skills/emc/scripts/analyze_emc.py", "--schematic", str(proj / "sch.json"),
                             "--pcb", str(proj / "pcb.json"), "--analysis-dir", str(adir))),
                    ("emc", ("skills/emc/scripts/analyze_emc.py", "--schematic", str(proj / "sch.json"),
                             "--pcb", str(proj / "pcb.json"), "--analysis-dir", str(adir))),
                    ("spice", ("skills/spice/scripts/simulate_subcircuits.py", "--schematic", str(proj / "sch.json"),
                               "--analysis-dir", str(adir), "--offline")),
                ]
                texts = []
                for _name, (rel, *args) in steps:
                    r = run(tree, rel, *args, cwd=d)
                    self.assertEqual(r.returncode, 0, f"{label} {rel}: {r.stderr}")
                    texts.append(_normalise((adir / "manifest.json").read_text(encoding="utf-8")))
                # An unreadable stored spice.json counts as changed, forcing the SPICE create-run path.
                cur = json.loads((adir / "manifest.json").read_text(encoding="utf-8"))["current"]
                (adir / cur / "spice.json").write_text("not json", encoding="utf-8")
                r = run(tree, "skills/spice/scripts/simulate_subcircuits.py", "--schematic", str(proj / "sch.json"),
                        "--analysis-dir", str(adir), "--offline", cwd=d)
                self.assertEqual(r.returncode, 0, f"{label} spice: {r.stderr}")
                texts.append(_normalise((adir / "manifest.json").read_text(encoding="utf-8")))
                gitignore = (adir / ".gitignore").read_bytes()
                manifests[label] = (texts, gitignore, len(run_dirs(adir)))
            self.assertEqual(manifests["old"], manifests["new"])
            self.assertEqual(manifests["new"][2], 2, "the SPICE create-run path was not exercised")


if __name__ == "__main__":
    unittest.main()
