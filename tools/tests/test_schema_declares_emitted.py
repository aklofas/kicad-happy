"""--schema declares keys the analyzers already emit."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PCB_KEYS = ("layer_transitions", "dimensions", "groups",
            "thermal_pad_scan", "copper_presence_summary",
            "decoupling_placement", "decoupling_proximity",
            "switching_loop_areas", "return_path_continuity")


def _schema(script):
    out = subprocess.run([sys.executable, str(ROOT / script), "--schema"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def _types(prop):
    """Set of JSON types a property accepts (Optional[...] emits anyOf)."""
    if "anyOf" in prop:
        return {b.get("type") for b in prop["anyOf"]}
    t = prop.get("type")
    return set(t) if isinstance(t, list) else {t}


class SchemaDeclaresEmitted(unittest.TestCase):
    def test_finding_declares_fix_params(self):
        for script in ("skills/kicad/scripts/analyze_schematic.py",
                       "skills/emc/scripts/analyze_emc.py"):
            props = _schema(script)["properties"]["findings"]["items"]["properties"]
            self.assertIn("fix_params", props, script)
            self.assertEqual(_types(props["fix_params"]), {"object", "null"})

    def test_pcb_schema_declares_emitted_keys(self):
        props = _schema("skills/kicad/scripts/analyze_pcb.py")["properties"]
        for key in PCB_KEYS:
            self.assertIn(key, props)
            self.assertEqual(_types(props[key]), {"array", "null"}, key)
            self.assertNotIn(key, _schema("skills/kicad/scripts/analyze_pcb.py")["required"])

    def test_gerber_zip_archives_names_emitted_keys(self):
        d = _schema("skills/kicad/scripts/analyze_gerbers.py")["properties"]["zip_archives"]["description"]
        for key in ("modified", "newest_member_date", "vs_loose_files", "age_delta_hours", "error"):
            self.assertIn(key, d)
        self.assertNotIn("staleness_warning", d)


if __name__ == "__main__":
    unittest.main()
