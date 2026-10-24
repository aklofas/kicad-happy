# tools/tests/test_render.py
"""Pins kicad_core.render: the severity normaliser, the text-report bucket adapter, and the shared text fragments."""
import sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.render import (  # noqa: E402
    finding_line, fmt_g4, fmt_signed, normalize_severity, plural, severity_bucket, wrap_lines)


class RenderTests(unittest.TestCase):
    def test_normalize_severity_table_matches_harness_pin(self):
        for raw, want in [("CRITICAL", "error"), ("HIGH", "error"), ("MEDIUM", "warning"), ("LOW", "info"),
                          ("INFO", "info"), ("critical", "error"), ("high", "error"), ("medium", "warning"),
                          ("low", "info"), ("error", "error"), ("warning", "warning"), ("info", "info"),
                          (None, "info"), ("", "info"), (42, "info"), ("garbage", "info"), ("WARN", "info")]:
            self.assertEqual(normalize_severity(raw), want, raw)

    def test_severity_bucket_is_the_warn_tolerant_adapter(self):
        self.assertEqual(severity_bucket("WARN"), "warning")
        self.assertEqual(severity_bucket("ERROR"), "error")
        self.assertEqual(severity_bucket(None), "info")
        self.assertEqual(severity_bucket("low"), "info")

    def test_fragments(self):
        self.assertEqual(plural(1, "error"), "1 error")
        self.assertEqual(plural(0, "warning"), "0 warnings")
        self.assertEqual(finding_line(3, "WARNING", "DC-001", "x"), "  [3] WARNING DC-001: x")
        self.assertEqual(wrap_lines("a" * 150), ["    " + "a" * 70, "      " + "a" * 70, "      " + "a" * 10])
        self.assertEqual(fmt_signed(30.0), "+30.0")
        self.assertEqual(fmt_signed(30), "+30.0")
        self.assertEqual(fmt_signed(-0.04), "-0.0")
        self.assertEqual(fmt_g4(0.00012345), "0.0001234")
        self.assertEqual(fmt_g4(1234567), "1.235e+06")


if __name__ == "__main__":
    unittest.main()
