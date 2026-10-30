"""An --analysis-dir run is a snapshot: a derived output (thermal, EMC, cross-analysis, SPICE)
stays in a run only while every output it was built from is unchanged, on both the new-run
and the overwrite path, and the run's source_hashes keep every source's hash."""
import hashlib, io, json, os, shutil, subprocess, sys, tempfile, unittest
from contextlib import redirect_stderr
from pathlib import Path
from tools.tests._fixtures import fixture_path, have

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
FX = fixture_path("simple-project")
sys.path.insert(0, str(SCRIPTS))

import analysis_cache  # noqa: E402


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _manifest(ad):
    with open(os.path.join(ad, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


def _run_files(ad, rid):
    run = os.path.join(ad, rid)
    return {name: _sha(os.path.join(run, name)) for name in sorted(os.listdir(run))}


@unittest.skipUnless(have(FX), "KH_FIXTURES not set")
class CliSnapshotTest(unittest.TestCase):
    def _run(self, script, *args):
        env = dict(os.environ, PYTHONHASHSEED="0", PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([sys.executable, str(SCRIPTS / script), *args], capture_output=True,
                           text=True, encoding="utf-8", cwd=self.tmp, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def _base(self, config=None):
        """sch -> pcb -> thermal into one run; returns (project dir, analysis dir, run id)."""
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        proj = os.path.join(self.tmp, "proj")
        shutil.copytree(FX, proj)
        if config is not None:
            Path(proj, ".kicad-happy.json").write_text(json.dumps(config), encoding="utf-8")
        ad = os.path.join(proj, "analysis")
        self.sch = os.path.join(proj, "simple.kicad_sch")
        self.pcb = os.path.join(proj, "simple.kicad_pcb")
        self._run("analyze_schematic.py", self.sch, "--analysis-dir", ad)
        self._run("analyze_pcb.py", self.pcb, "--analysis-dir", ad)
        self._run("analyze_thermal.py", "--analysis-dir", ad)
        rid = _manifest(ad)["current"]
        self.assertEqual(sorted(os.listdir(os.path.join(ad, rid))),
                         ["pcb.json", "schematic.json", "thermal.json"])
        return proj, ad, rid

    def _change_r_value(self):
        text = Path(self.sch).read_text(encoding="utf-8")
        self.assertEqual(text.count('(property "Value" "330"'), 1)
        Path(self.sch).write_text(text.replace('(property "Value" "330"', '(property "Value" "10k"'),
                                  encoding="utf-8")

    def test_new_run_after_a_schematic_change_drops_thermal(self):
        _proj, ad, base = self._base()
        base_files = _run_files(ad, base)
        self._change_r_value()
        r = self._run("analyze_schematic.py", self.sch, "--analysis-dir", ad)
        m = _manifest(ad)
        new = m["current"]
        self.assertNotEqual(new, base)
        files = _run_files(ad, new)
        self.assertEqual(sorted(files), ["pcb.json", "schematic.json"])
        self.assertEqual(files["pcb.json"], base_files["pcb.json"])
        self.assertNotEqual(files["schematic.json"], base_files["schematic.json"])
        self.assertEqual(m["runs"][new]["outputs"], {"schematic": "schematic.json", "pcb": "pcb.json"})
        self.assertEqual(m["runs"][new]["source_hashes"],
                         {"simple.kicad_sch": "sha256:" + _sha(self.sch),
                          "simple.kicad_pcb": "sha256:" + _sha(self.pcb)})
        self.assertIn("thermal.json dropped from the run", r.stderr)
        self.assertEqual(_run_files(ad, base), base_files)

    def test_overwrite_after_a_schematic_change_drops_thermal(self):
        _proj, ad, base = self._base({"analysis": {"diff_threshold": "breaking"}})
        self._change_r_value()
        r = self._run("analyze_schematic.py", self.sch, "--analysis-dir", ad)
        m = _manifest(ad)
        self.assertEqual(m["current"], base)
        self.assertEqual(sorted(os.listdir(os.path.join(ad, base))), ["pcb.json", "schematic.json"])
        self.assertEqual(m["runs"][base]["outputs"], {"schematic": "schematic.json", "pcb": "pcb.json"})
        self.assertIn("thermal.json dropped from the run", r.stderr)

    def test_unchanged_reruns_keep_thermal(self):
        _proj, ad, base = self._base()
        base_files = _run_files(ad, base)
        for script, src in (("analyze_schematic.py", self.sch), ("analyze_pcb.py", self.pcb)):
            r = self._run(script, src, "--analysis-dir", ad)
            self.assertNotIn("dropped from the run", r.stderr)
        m = _manifest(ad)
        self.assertEqual(m["current"], base)
        self.assertEqual(_run_files(ad, base), base_files)
        self.assertEqual(m["runs"][base]["outputs"]["thermal"], "thermal.json")


def _write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


class CreateRunTest(unittest.TestCase):
    """create_run on a hand-built previous run whose derived outputs record their inputs."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.ad = os.path.join(self.tmp, "analysis")
        self.prev = os.path.join(self.ad, "prev")
        os.makedirs(self.prev)
        _write_json(os.path.join(self.prev, "schematic.json"), {"analyzer_type": "schematic", "n": 1})
        _write_json(os.path.join(self.prev, "pcb.json"), {"analyzer_type": "pcb", "n": 1})
        sch_sha = _sha(os.path.join(self.prev, "schematic.json"))
        pcb_sha = _sha(os.path.join(self.prev, "pcb.json"))

        def art(name, sha):
            return {"path": os.path.join(self.prev, name), "sha256": sha,
                    "schema_version": "1.4.0", "run_id": "20261030T000000Z-000000"}
        _write_json(os.path.join(self.prev, "cross_analysis.json"), {"inputs": {"upstream_artifacts": {
            "schematic": art("schematic.json", sch_sha), "pcb": art("pcb.json", pcb_sha)}}})
        _write_json(os.path.join(self.prev, "emc.json"), {"inputs": {"upstream_artifacts": {
            "pcb": art("pcb.json", pcb_sha)}}})
        _write_json(os.path.join(self.prev, "spice.json"), {"simulation_results": []})
        _write_json(os.path.join(self.ad, "manifest.json"), {
            "version": 1, "project": "", "current": "prev", "runs": {"prev": {
                "source_hashes": {"a.kicad_sch": "sha256:aa", "a.kicad_pcb": "sha256:bb"},
                "outputs": {"schematic": "schematic.json", "pcb": "pcb.json",
                            "cross_analysis": "cross_analysis.json", "emc": "emc.json",
                            "spice": "spice.json"},
                "scripts": {}, "generated": "2026-10-30T00:00:00+00:00", "pinned": False}}})
        self.out = os.path.join(self.tmp, "out")
        os.makedirs(self.out)

    def _create(self, source_hashes):
        with redirect_stderr(io.StringIO()):
            rid = analysis_cache.create_run(self.ad, self.out, source_hashes=source_hashes,
                                            scripts={}, run_id="new")
        return sorted(os.listdir(os.path.join(self.ad, rid))), _manifest(self.ad)["runs"][rid]

    def test_byte_identical_schematic_carries_everything_forward(self):
        shutil.copy(os.path.join(self.prev, "schematic.json"), self.out)
        files, run = self._create({"a.kicad_sch": "sha256:aa"})
        self.assertEqual(files, ["cross_analysis.json", "emc.json", "pcb.json", "schematic.json",
                                 "spice.json"])
        self.assertEqual(sorted(run["outputs"]), ["cross_analysis", "emc", "pcb", "schematic", "spice"])
        for name in files:
            self.assertEqual(_sha(os.path.join(self.ad, "new", name)), _sha(os.path.join(self.prev, name)))

    def test_changed_schematic_keeps_only_outputs_not_built_from_it(self):
        _write_json(os.path.join(self.out, "schematic.json"), {"analyzer_type": "schematic", "n": 2})
        files, run = self._create({"a.kicad_sch": "sha256:cc"})
        # emc recorded only the pcb; spice records nothing, so it counts as built from both
        self.assertEqual(files, ["emc.json", "pcb.json", "schematic.json"])
        self.assertEqual(run["outputs"], {"schematic": "schematic.json", "pcb": "pcb.json",
                                          "emc": "emc.json"})
        self.assertEqual(run["source_hashes"], {"a.kicad_sch": "sha256:cc", "a.kicad_pcb": "sha256:bb"})

    def test_changed_pcb_drops_every_output_built_from_it(self):
        _write_json(os.path.join(self.out, "pcb.json"), {"analyzer_type": "pcb", "n": 2})
        files, run = self._create({"a.kicad_pcb": "sha256:dd"})
        self.assertEqual(files, ["pcb.json", "schematic.json"])
        self.assertEqual(run["source_hashes"], {"a.kicad_sch": "sha256:aa", "a.kicad_pcb": "sha256:dd"})

    def test_missing_previous_file_leaves_outputs(self):
        os.unlink(os.path.join(self.prev, "emc.json"))
        _write_json(os.path.join(self.out, "thermal.json"), {"inputs": {}})
        files, run = self._create({})
        self.assertNotIn("emc", run["outputs"])
        self.assertEqual(files, ["cross_analysis.json", "pcb.json", "schematic.json", "spice.json",
                                 "thermal.json"])


if __name__ == "__main__":
    unittest.main()
