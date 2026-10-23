"""Finding readers render the same lines whether a finding carries `title` (pre-v3 EMC) or only `summary`."""
import copy, json, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
EMC = ROOT / "skills" / "emc" / "scripts"
LEGACY = Path(__file__).resolve().parent / "fixtures" / "text" / "emc_legacy_shape.json"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(EMC))

from kicad_core.render import summary_or_title  # noqa: E402


def shapes():
    """(legacy, new) EMC documents; one finding raised to error so the error-only report paths render it."""
    legacy = json.loads(LEGACY.read_text(encoding="utf-8"))
    legacy["findings"][0]["severity"] = "error"
    new = copy.deepcopy(legacy)
    for f in new["findings"]:
        del f["title"]
    return legacy, new


def run(*args, cwd):
    r = subprocess.run([sys.executable, *map(str, args)], cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout


def render_all(doc, d):
    """Every rendered artefact that reads a finding's title, for one EMC document, rendered in `d`."""
    from analyze_emc import format_text_report
    out = {"emc_text": format_text_report(doc)}
    empty = dict(copy.deepcopy(doc), findings=[])
    (d / "emc.json").write_text(json.dumps(doc), encoding="utf-8")
    (d / "empty.json").write_text(json.dumps(empty), encoding="utf-8")
    diff = SCRIPTS / "diff_analysis.py"
    out["diff_new_text"] = run(diff, d / "empty.json", d / "emc.json", "--text", cwd=d)
    out["diff_resolved_text"] = run(diff, d / "emc.json", d / "empty.json", "--text", cwd=d)
    out["diff_new_json"] = run(diff, d / "empty.json", d / "emc.json", cwd=d)
    (d / "diff.json").write_text(out["diff_new_json"], encoding="utf-8")
    run(ROOT / "action" / "format-report.py", "--emc", d / "emc.json", "--diff", d / "diff.json",
        "--output", d / "pr.md", "--output-full", d / "full.md", cwd=d)
    out["report_pr"] = (d / "pr.md").read_text(encoding="utf-8")
    out["report_full"] = (d / "full.md").read_text(encoding="utf-8")
    return out


class DualShape(unittest.TestCase):
    def test_summary_or_title(self):
        self.assertEqual(summary_or_title({"summary": "s", "title": "t"}), "s")
        self.assertEqual(summary_or_title({"title": "t"}), "t")
        self.assertEqual(summary_or_title({"summary": "", "title": "t"}), "t")
        self.assertEqual(summary_or_title({}), "")

    def test_readers_accept_both_shapes(self):
        legacy, new = shapes()
        with tempfile.TemporaryDirectory() as d:  # one directory: the diff JSON embeds input paths
            a, b = render_all(legacy, Path(d)), render_all(new, Path(d))
        title = legacy["findings"][0]["title"]
        for name in a:
            self.assertEqual(b[name], a[name], name)
        for name in ("emc_text", "diff_new_text", "diff_resolved_text", "report_pr", "report_full"):
            self.assertIn(title, b[name], name)
        self.assertIn(f'"title": "{title}"', b["diff_new_json"])


if __name__ == "__main__":
    unittest.main()
