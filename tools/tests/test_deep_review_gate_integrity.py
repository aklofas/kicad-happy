"""Deep Review gate: a quote must keep the page's numbers, signs, decimal points,
comparison operators and unit letters; malformed evidence, a non-array findings
list and a page below 1 or past the end of the PDF quarantine instead of crashing
or verifying."""
import json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "skills" / "kicad" / "review" / "scripts"
GATE = REVIEW / "deep_review_gate.py"
for p in (REVIEW, ROOT / "skills" / "kicad" / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import deep_review_gate  # noqa: E402

PAGE_A = "Maximum resistance of device at 20°C.\nThe over-\nvoltage clamp limit is 5.5 V"

# (quote, page text, expected, what the quote claims against the page)
QUOTE_CASES = [
    ("Maximum input voltage 55 V", "Maximum input voltage 5.5 V", False, "decimal dropped"),
    ("Maximum input voltage 5.5 V", "Maximum input voltage 55 V", False, "decimal added"),
    ("Maximum input voltage 5.5V", "Maximum input voltage 5.5 V", True, "unit spacing"),
    ("Operating range -40 C to 85 C", "Operating range 40 C to 85 C", False, "sign added"),
    ("Operating range 40 C to 85 C", "Operating range -40 C to 85 C", False, "sign dropped"),
    ("Operating range -40°C to +85°C", "Operating range −40 °C to +85 °C", True, "U+2212 minus"),
    ("Operating range -40°C to 85°C", "Operating range –40°C to 85°C", True, "en dash minus"),
    ("40°C", "TA = −40°C", False, "number inside a signed number"),
    ("VIN < 5 V", "VIN > 5 V", False, "operator flipped"),
    ("VIN ≤ 5 V", "VIN ≤ 5 V", True, "same operator"),
    ("VIN <= 5 V", "VIN ≤ 5 V", True, "ASCII spelling of ≤"),
    ("VIN<5V", "VIN < 5 V", True, "operator spacing"),
    ("...", "anything at all", False, "no content"),
    ("…", "anything at all", False, "no content, Unicode ellipsis"),
    ("- -", "anything at all", False, "punctuation only"),
    ("SOT-23 package", "SOT-23 package", True, "identifier hyphen"),
    ("SOT23 package", "SOT-23 package", True, "identifier hyphen dropped"),
    ("3.3-5.5 V", "3.3-5.5 V", True, "range dash"),
    ("10 µA", "10 μA", True, "micro sign vs Greek mu"),
    ("10 µA", "10 A", False, "unit prefix dropped"),
    ("1 kΩ", "1 k", False, "ohm sign dropped"),
    ("1,000 hours", "1,000 hours", True, "thousands comma"),
    ("Maximum resistance of device at 20°C", PAGE_A, True, "KH-347 #1"),
    ("maximum resistance of device at 20 ° C", PAGE_A, True, "KH-347 #2"),
    ("the overvoltage clamp limit is 5.5V", PAGE_A, True, "KH-347 #3"),
    ("over-voltage clamp limit", PAGE_A, True, "KH-347 #4"),
    ("Maximum resistance of device at 25°C", PAGE_A, False, "KH-347 #5"),
    ("alpha bravo ... echo foxtrot", "alpha bravo charlie delta echo foxtrot", True, "KH-385"),
    ("echo foxtrot ... alpha bravo", "alpha bravo charlie delta echo foxtrot", False, "KH-385 order"),
    ("alpha zulu charlie", "alpha bravo charlie delta echo foxtrot", False, "KH-385"),
    ("VCC + 0.3 V", "VCC + 0.3 V", True, "plus spaced"),
    ("VIN-0.3V", "VIN – 0.3V", True, "binary minus spelled differently"),
    ("0.9 1.0", "0.91.0", False, "two numbers are not one"),
    ("15 V", "±15 V", False, "± dropped"),
    ("15 V", "+/-15 V", False, "+/- dropped"),
    ("-15 V", "±15 V", False, "± read as minus"),
    ("+15 V", "±15 V", False, "± read as plus"),
    ("0.5 V", "5 V ±0.5 V", False, "tolerance read as a value"),
    ("±15 V", "±15 V", True, "same ±"),
    ("±15 V", "+/-15 V", True, "+/- spelling of ±"),
    ("+/- 15 V", "± 15 V", True, "spaced +/- spelling of a spaced ±"),
    ("±15V", "+-15 V", True, "+- spelling of ±"),
    ("a ± b", "a ± b", True, "± between words"),
    ("-15 V", "+/−15 V", False, "minus vs +/−15 V"),
    ("15 V", "+/−15 V", False, "unsigned vs +/−15 V"),
    ("±15 V", "+/−15 V", True, "± vs +/−15 V"),
    ("-15 V", "+/–15 V", False, "minus vs +/–15 V"),
    ("15 V", "+/–15 V", False, "unsigned vs +/–15 V"),
    ("±15 V", "+/–15 V", True, "± vs +/–15 V"),
    ("-15 V", "+–15 V", False, "minus vs +–15 V"),
    ("15 V", "+–15 V", False, "unsigned vs +–15 V"),
    ("±15 V", "+–15 V", True, "± vs +–15 V"),
    ("-15 V", "+—15 V", False, "minus vs +—15 V"),
    ("15 V", "+—15 V", False, "unsigned vs +—15 V"),
    ("±15 V", "+—15 V", True, "± vs +—15 V"),
]


class QuoteMatchTest(unittest.TestCase):
    def test_cases(self):
        for quote, text, expected, why in QUOTE_CASES:
            with self.subTest(why=why, quote=quote):
                self.assertIs(deep_review_gate._quote_in_text(quote, text), expected)

    def test_control_characters_in_page_text_are_not_numbers(self):
        # pdftotext emits C0 bytes for symbol fonts; they must not read as a sign
        # or a decimal point
        page = "Supply \x01 \x02 voltage 3\x023 V and \x0140 C"
        self.assertTrue(deep_review_gate._quote_in_text("Supply voltage 3", page))
        self.assertFalse(deep_review_gate._quote_in_text("voltage 3.3 V", page))
        self.assertFalse(deep_review_gate._quote_in_text("and -40 C", page))


def _pdf(pages):
    """A minimal PDF, one Helvetica text page per entry (WinAnsi: µ = 0xB5)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    kids = []
    for text in pages:
        esc = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({esc}) Tj ET".encode("cp1252")
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 3 0 R >> >> /Contents {len(objs)} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        body = body if isinstance(body, bytes) else body.encode("latin-1")
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


PAGES = ["Maximum input voltage 5.5 V at -40 C", "Quiescent current 10 µA typical"]


@unittest.skipUnless(shutil.which("pdftotext"), "pdftotext (poppler) not installed")
class GateCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        (self.tmp / "analysis").mkdir()
        (self.tmp / "datasheets").mkdir()
        (self.tmp / "datasheets" / "TPS1.pdf").write_bytes(_pdf(PAGES))
        (self.tmp / "analysis" / "schematic.json").write_text(json.dumps(
            {"components": [{"reference": "U1"}], "nets": {"VCC": {}}}), encoding="utf-8")

    def _gate(self, doc, env=None):
        path = self.tmp / "deep_review.json"
        raw = json.dumps(doc, ensure_ascii=False)
        path.write_text(raw, encoding="utf-8")
        r = subprocess.run([sys.executable, str(GATE), str(path),
                            "--analysis-dir", str(self.tmp / "analysis"),
                            "--datasheets-dir", str(self.tmp / "datasheets")],
                           capture_output=True, text=True, encoding="utf-8", timeout=120,
                           env=dict(os.environ, **(env or {})))
        self.assertNotIn("Traceback", r.stderr)
        after = path.read_text(encoding="utf-8")
        return r, (json.loads(after) if after != raw else None)

    @staticmethod
    def _doc(findings, **top):
        return {"schema_version": "1.0", "produced_for_run_id": "r",
                "produced_at": "2026-10-29T00:00:00Z", "findings": findings,
                "quarantined": [], **top}

    @staticmethod
    def _finding(evidence=None, **cite):
        c = {"mpn": "TPS1", "page": 1, "quote": "Maximum input voltage 5.5 V"}
        c.update(cite)
        return {"detector": "deep_review", "category": "power", "severity": "warning",
                "confidence": "high", "summary": "input headroom",
                "evidence": evidence if evidence is not None
                else {"components": ["U1"], "datasheet": [c]}}

    def _one(self, finding, rc):
        r, out = self._gate(self._doc([finding]))
        self.assertEqual(r.returncode, rc, r.stderr)
        return out

    def test_legitimate_respellings_verify(self):
        for quote, page in (("Maximum input voltage 5.5V", 1),
                            ("maximum input voltage 5.5 v at −40 C", 1),
                            ("Quiescent current 10 μA", 2)):
            with self.subTest(quote=quote):
                out = self._one(self._finding(quote=quote, page=page), 0)
                self.assertEqual(out["findings"][0]["evidence_checked"], "full")

    def test_absent_page_searches_the_whole_document(self):
        f = self._finding(quote="Quiescent current 10 µA")
        del f["evidence"]["datasheet"][0]["page"]
        out = self._one(f, 0)
        self.assertEqual(out["findings"][0]["evidence_checked"], "full")

    def test_meaning_changes_quarantine(self):
        for quote, page in (("Maximum input voltage 55 V", 1),
                            ("voltage 5.5 V at 40 C", 1),
                            ("Quiescent current 10 A", 2)):
            with self.subTest(quote=quote):
                out = self._one(self._finding(quote=quote, page=page), 1)
                self.assertEqual(out["findings"], [])
                self.assertIn("quote not found page", out["quarantined"][0]["quarantine_reason"])

    def test_quote_without_content_quarantines(self):
        out = self._one(self._finding(quote="..."), 1)
        self.assertIn("has no letter or digit", out["quarantined"][0]["quarantine_reason"])

    def test_page_below_one_quarantines(self):
        for page in (0, -3):
            with self.subTest(page=page):
                out = self._one(self._finding(page=page), 1)
                self.assertIn(f"page {page} is not a page number",
                              out["quarantined"][0]["quarantine_reason"])

    def test_page_past_the_end_quarantines(self):
        out = self._one(self._finding(page=3), 1)
        self.assertIn("page 3 is past the end of TPS1.pdf",
                      out["quarantined"][0]["quarantine_reason"])

    def test_non_object_evidence_quarantines(self):
        for ev in ("U1", ["U1"]):
            with self.subTest(evidence=ev):
                out = self._one(self._finding(evidence=ev), 1)
                reason = out["quarantined"][0]["quarantine_reason"]
                self.assertIn("is not of type 'object'", reason)
                self.assertIn("no design anchor", reason)

    def test_non_array_findings_is_a_shape_error(self):
        for key in ("findings", "quarantined"):
            with self.subTest(key=key):
                r, out = self._gate({**self._doc([]), key: 1})
                self.assertEqual(r.returncode, 2)
                self.assertIn(f"({key} must be an array)", r.stderr)
                self.assertIsNone(out)

    def test_null_findings_stay_empty(self):
        r, out = self._gate(self._doc(None))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(out["findings"], [])

    def test_unloadable_analyzer_json_exits_2_naming_the_file(self):
        doc = self._doc([self._finding()])
        for name, raw in (("schematic.json", b"[1]"), ("schematic.json", b"{not json"),
                          ("schematic.json", b'{"components": "\xff"}'),
                          ("pcb.json", b'"a string"')):
            with self.subTest(name=name, raw=raw):
                (self.tmp / "analysis" / "schematic.json").write_text(
                    json.dumps({"components": [{"reference": "U1"}]}), encoding="utf-8")
                (self.tmp / "analysis" / "pcb.json").unlink(missing_ok=True)
                (self.tmp / "analysis" / name).write_bytes(raw)
                r, out = self._gate(doc)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("cannot load inputs", r.stderr)
                self.assertIn(name, r.stderr)
                self.assertIsNone(out)

    def test_odd_shapes_inside_analyzer_json_are_ignored(self):
        (self.tmp / "analysis" / "schematic.json").write_text(json.dumps(
            {"components": [{"reference": "U1"}], "nets": ["VCC"]}), encoding="utf-8")
        (self.tmp / "analysis" / "pcb.json").write_text(
            json.dumps({"footprints": 7}), encoding="utf-8")
        r, out = self._gate(self._doc([self._finding()]))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_rewrite_keeps_the_file_mode_and_leaves_no_temp(self):
        path = self.tmp / "deep_review.json"
        path.write_text(json.dumps(self._doc([])), encoding="utf-8")
        os.chmod(path, 0o640)
        r, _ = self._gate(self._doc([self._finding()]))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()),
                         ["analysis", "datasheets", "deep_review.json"])

    def test_symlinked_document_is_replaced_not_followed(self):
        real = self.tmp / "elsewhere.json"
        real.write_text(json.dumps(self._doc([self._finding()])), encoding="utf-8")
        before = real.read_bytes()
        link = self.tmp / "deep_review.json"
        link.symlink_to(real)
        deep_review_gate.write_text_atomic(link, "{}\n")
        self.assertFalse(link.is_symlink())
        self.assertEqual(link.read_text(encoding="utf-8"), "{}\n")
        self.assertEqual(real.read_bytes(), before)

    def test_utf8_under_an_ascii_locale(self):
        f = self._finding(quote="Quiescent current 10 µA", page=2)
        f["summary"] = "Iq 10 µA"
        r, out = self._gate(self._doc([f]), env={"LC_ALL": "C", "PYTHONUTF8": "0",
                                                 "PYTHONIOENCODING": "utf-8"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(out["findings"][0]["summary"], "Iq 10 µA")


if __name__ == "__main__":
    unittest.main()
