"""The Action entrypoint runs its inline Python isolated from the checked-out workspace."""
import os, re, shutil, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCH = ('(kicad_sch (version 20231120) (generator "eeschema") '
       '(uuid "11111111-1111-1111-1111-111111111111") (paper "A4") (lib_symbols))\n')


def run_entrypoint(tmp, files, **env):
    """Run action/entrypoint.sh from a copy of the Action in tmp, with `files` as the workspace.
    Returns (CompletedProcess, GITHUB_OUTPUT as a dict)."""
    tmp = Path(tmp)
    ws = tmp / "ws"
    ap = tmp / "action-path"
    (tmp / "t").mkdir(exist_ok=True)
    ws.mkdir(exist_ok=True)
    for rel, text in files.items():
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(ROOT / "action", ap / "action", ignore=ignore)
    shutil.copytree(ROOT / "skills" / "kicad" / "scripts", ap / "skills" / "kicad" / "scripts", ignore=ignore)
    gh_out, gh_env = tmp / "github_output", tmp / "github_env"
    gh_out.write_text("", encoding="utf-8")
    gh_env.write_text("", encoding="utf-8")
    full_env = {"PATH": os.environ["PATH"], "HOME": str(tmp), "TMPDIR": str(tmp / "t"),
                "ACTION_PATH": str(ap), "GITHUB_OUTPUT": str(gh_out), "GITHUB_ENV": str(gh_env),
                "INPUT_SPICE": "false", "DIGIKEY_CLIENT_ID": "", "DIGIKEY_CLIENT_SECRET": "",
                "ELEMENT14_API_KEY": "", "MOUSER_SEARCH_API_KEY": "", **env}
    r = subprocess.run(["bash", str(ap / "action" / "entrypoint.sh")], cwd=ws, env=full_env,
                       capture_output=True, text=True, encoding="utf-8", timeout=300)
    out = {}
    for line in gh_out.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return r, out


@unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "runs the bash entrypoint")
class EntrypointIsolationTest(unittest.TestCase):
    def test_workspace_json_module_is_not_imported(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            sentinel = tmp / "SENTINEL"
            planted = f'open({str(sentinel)!r}, "w").close()\nraise ImportError("planted")\n'
            r, out = run_entrypoint(tmp, {"top.kicad_sch": SCH, "json.py": planted})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(sentinel.exists())
            self.assertIn("Components: 0, Nets: 0", r.stdout)
            self.assertEqual(out["has-critical"], "false")


PCB = '(kicad_pcb (version 20240108) (generator "pcbnew") (general (thickness 1.6)) (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user)))\n'


@unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "runs the bash entrypoint")
class EntrypointFailedAnalysisTest(unittest.TestCase):
    def test_only_selected_analysis_failed_fails_the_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, out = run_entrypoint(Path(tmp), {"top.kicad_sch": ""})
            self.assertEqual(r.returncode, 1)
            self.assertEqual(out["has-critical"], "false")
            self.assertIn("Incomplete review", Path(out["report-path"]).read_text(encoding="utf-8"))

    def test_missing_configured_path_counts_as_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, out = run_entrypoint(Path(tmp), {"x": ""}, INPUT_SCHEMATIC="nope.kicad_sch")
            self.assertEqual(r.returncode, 1)
            self.assertIn("Schematic analysis failed", Path(out["report-path"]).read_text(encoding="utf-8"))

    def test_failed_schematic_beside_a_pcb_posts_an_error_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "bin").mkdir()
            curl = tmp / "bin" / "curl"
            curl.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {tmp / "curl.args"}\n', encoding="utf-8")
            curl.chmod(0o755)
            r, out = run_entrypoint(tmp, {"top.kicad_sch": "", "top.kicad_pcb": PCB},
                                    PATH=f"{tmp / 'bin'}{os.pathsep}{os.environ['PATH']}",
                                    GITHUB_TOKEN="t", GITHUB_REPOSITORY="o/r", GITHUB_SHA="abc")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('"state":"error"', (tmp / "curl.args").read_text(encoding="utf-8"))
            self.assertIn("pcb-json", out)

    def test_both_selected_analyses_failed_fails_the_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "bin").mkdir()
            curl = tmp / "bin" / "curl"
            curl.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {tmp / "curl.args"}\n', encoding="utf-8")
            curl.chmod(0o755)
            r, out = run_entrypoint(tmp, {"top.kicad_sch": "", "top.kicad_pcb": ""},
                                    PATH=f"{tmp / 'bin'}{os.pathsep}{os.environ['PATH']}",
                                    GITHUB_TOKEN="t", GITHUB_REPOSITORY="o/r", GITHUB_SHA="abc")
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertIn('"state":"error"', (tmp / "curl.args").read_text(encoding="utf-8"))
            report = Path(out["report-path"]).read_text(encoding="utf-8")
            self.assertIn("Incomplete review", report)
            self.assertIn("Schematic, PCB analysis failed", report)

    def test_failed_pcb_beside_a_schematic_is_listed_and_does_not_fail_the_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, out = run_entrypoint(Path(tmp), {"top.kicad_sch": SCH, "top.kicad_pcb": ""})
            self.assertEqual(r.returncode, 0, r.stderr)
            report = Path(out["report-path"]).read_text(encoding="utf-8")
            self.assertIn("Incomplete review", report)
            self.assertIn("PCB analysis failed", report)
            self.assertNotIn("Schematic analysis failed", report)
            self.assertNotIn("Schematic, ", report)


class EntrypointStaticTest(unittest.TestCase):
    def test_no_inline_python_reads_the_workspace(self):
        for name in ("entrypoint.sh", "diff_base.sh", "detect_project.sh"):
            text = (ROOT / "action" / name).read_text(encoding="utf-8")
            self.assertEqual(re.findall(r"python3 -c\b", text), [], name)
        text = (ROOT / "action" / "entrypoint.sh").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"python3 -I -c ", text)), 12)
