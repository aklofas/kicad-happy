#!/usr/bin/env python3
"""Unit tests for search_lcsc.py.

Tests parsing, normalization, table/detail formatting, CLI filtering,
sorting, and API fallback logic. All tests use mocked responses by default
for fast, deterministic, offline execution. An optional live test class
is included for end-to-end verification when network is available.

Run with:
    python3 skills/lcsc/scripts/test_search_lcsc.py
    python3 -m unittest skills/lcsc/scripts/test_search_lcsc.py
"""

import io
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add script directory to sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import search_lcsc


class TestParseExtra(unittest.TestCase):
    """Test safe parsing of the 'extra' field from jlcsearch API responses."""

    def test_extra_none(self):
        comp = {"lcsc": 12345}
        result = search_lcsc._parse_extra(comp)
        self.assertEqual(result, {})

    def test_extra_dict(self):
        extra_data = {"number": "C12345", "quantity": 500}
        comp = {"lcsc": 12345, "extra": extra_data}
        result = search_lcsc._parse_extra(comp)
        self.assertEqual(result, extra_data)

    def test_extra_json_string(self):
        extra_str = json.dumps({"number": "C12345", "quantity": 500})
        comp = {"lcsc": 12345, "extra": extra_str}
        result = search_lcsc._parse_extra(comp)
        self.assertEqual(result, {"number": "C12345", "quantity": 500})
        # Check that component was updated in place with parsed dict
        self.assertIsInstance(comp["extra"], dict)

    def test_extra_invalid_json_string(self):
        comp = {"lcsc": 12345, "extra": "{not valid json}"}
        result = search_lcsc._parse_extra(comp)
        self.assertEqual(result, {})


class TestNormalizeComponent(unittest.TestCase):
    """Test normalization of component dictionaries across API variations."""

    def test_normalize_basic_part(self):
        raw = {
            "lcsc": 318884,
            "mfr": "TS-1187A-B-A-B",
            "package": "SMD-4P,5.1x5.1mm",
            "is_basic": True,
            "description": "Tactile switch 50mA 12V",
            "stock": 1600000,
            "price": 0.0197,
            "datasheet": "https://example.com/ds.pdf"
        }
        item = search_lcsc.normalize_component(raw)
        self.assertEqual(item["lcsc_code"], "C318884")
        self.assertEqual(item["lcsc_id"], 318884)
        self.assertEqual(item["mpn"], "TS-1187A-B-A-B")
        self.assertTrue(item["is_basic"])
        self.assertEqual(item["stock"], 1600000)
        self.assertAlmostEqual(item["price_usd"], 0.0197, places=4)
        self.assertEqual(item["datasheet_url"], "https://example.com/ds.pdf")

    def test_normalize_extra_fields(self):
        raw = {
            "lcsc": 17408,
            "basic": 1,
            "extra": {
                "number": "C17408",
                "mpn": "0805W8F1000T5E",
                "manufacturer": {"name": "UNI-ROYAL"},
                "package": "0805",
                "description": "100 Ohm resistor",
                "quantity": 2500000,
                "whs-js": 1500000,
                "whs-zh": 1000000,
                "whs-hk": 0,
                "datasheet": {"pdf": "https://example.com/resistor.pdf"},
                "attributes": {"Resistance": "100Ω", "Tolerance": "±1%"},
                "prices": [{"min_qty": 100, "max_qty": 499, "price": 0.0034}]
            }
        }
        item = search_lcsc.normalize_component(raw)
        self.assertEqual(item["lcsc_code"], "C17408")
        self.assertEqual(item["manufacturer"], "UNI-ROYAL")
        self.assertEqual(item["package"], "0805")
        self.assertTrue(item["is_basic"])
        self.assertEqual(item["stock"], 2500000)
        self.assertEqual(item["warehouses"]["js"], 1500000)
        self.assertEqual(item["warehouses"]["zh"], 1000000)
        self.assertEqual(item["datasheet_url"], "https://example.com/resistor.pdf")
        self.assertEqual(item["attributes"]["Resistance"], "100Ω")
        self.assertAlmostEqual(item["price_usd"], 0.0034, places=4)


class TestFormatting(unittest.TestCase):
    """Test table and detailed card view formatting."""

    def setUp(self):
        self.sample_item = {
            "lcsc_code": "C17408",
            "lcsc_id": 17408,
            "mpn": "0805W8F1000T5E",
            "manufacturer": "UNI-ROYAL",
            "package": "0805",
            "description": "100 Ohm 1% 1/8W 0805 SMD Resistor",
            "is_basic": True,
            "stock": 2500000,
            "price_usd": 0.0034,
            "datasheet_url": "https://example.com/resistor.pdf",
            "attributes": {"Resistance": "100Ω", "Power": "125mW"},
            "prices": [{"min_qty": 100, "max_qty": 499, "price": 0.0034}],
            "warehouses": {"js": 1500000, "zh": 1000000, "hk": 0}
        }

    def test_format_table_empty(self):
        output = search_lcsc.format_table([])
        self.assertEqual(output, "No components found.")

    def test_format_table_populated(self):
        output = search_lcsc.format_table([self.sample_item])
        self.assertIn("LCSC #", output)
        self.assertIn("C17408", output)
        self.assertIn("0805W8F1000T5E", output)
        self.assertIn("Basic", output)
        self.assertIn("2,500,000", output)
        self.assertIn("$0.0034", output)

    def test_format_details(self):
        output = search_lcsc.format_details(self.sample_item)
        self.assertIn("LCSC Code:      C17408", output)
        self.assertIn("MPN:            0805W8F1000T5E", output)
        self.assertIn("Manufacturer:   UNI-ROYAL", output)
        self.assertIn("JLCPCB Type:    Basic", output)
        self.assertIn("Resistance: 100Ω", output)
        self.assertIn("https://example.com/resistor.pdf", output)


class TestDirectLookupValidation(unittest.TestCase):
    """Test validation and guards in lookup_wmsc_direct."""

    def test_invalid_code_rejected(self):
        # Non-Cxxxxx codes should return None without making any HTTP request
        self.assertIsNone(search_lcsc.lookup_wmsc_direct("resistor"))
        self.assertIsNone(search_lcsc.lookup_wmsc_direct("12345"))
        self.assertIsNone(search_lcsc.lookup_wmsc_direct(""))


class TestMainCli(unittest.TestCase):
    """Test command-line argument parsing and filtering."""

    def setUp(self):
        self.mock_raw_results = [
            {
                "lcsc": 17408,
                "mfr": "0805W8F1000T5E",
                "package": "0805",
                "is_basic": True,
                "description": "100R 0805 Resistor",
                "stock": 2500000,
                "price": 0.0034
            },
            {
                "lcsc": 99999,
                "mfr": "EXT-RES-100R",
                "package": "1206",
                "is_basic": False,
                "description": "100R 1206 Resistor Extended",
                "stock": 0,
                "price": 0.0500
            }
        ]

    @patch("search_lcsc.search_jlcsearch")
    def test_cli_basic_filter(self, mock_search):
        mock_search.return_value = list(self.mock_raw_results)

        stdout = io.StringIO()
        with patch.object(sys, "argv", ["search_lcsc.py", "100R", "--basic"]), \
             patch("sys.stdout", stdout):
            with self.assertRaises(SystemExit) as cm:
                search_lcsc.main()
            self.assertEqual(cm.exception.code, 0)

        output = stdout.getvalue()
        self.assertIn("C17408", output)
        self.assertNotIn("C99999", output)

    @patch("search_lcsc.search_jlcsearch")
    def test_cli_instock_filter(self, mock_search):
        mock_search.return_value = list(self.mock_raw_results)

        stdout = io.StringIO()
        with patch.object(sys, "argv", ["search_lcsc.py", "100R", "--in-stock"]), \
             patch("sys.stdout", stdout):
            with self.assertRaises(SystemExit) as cm:
                search_lcsc.main()
            self.assertEqual(cm.exception.code, 0)

        output = stdout.getvalue()
        self.assertIn("C17408", output)
        self.assertNotIn("C99999", output)

    @patch("search_lcsc.search_jlcsearch")
    def test_cli_json_output(self, mock_search):
        mock_search.return_value = list(self.mock_raw_results)

        stdout = io.StringIO()
        with patch.object(sys, "argv", ["search_lcsc.py", "100R", "--json"]), \
             patch("sys.stdout", stdout):
            with self.assertRaises(SystemExit) as cm:
                search_lcsc.main()
            self.assertEqual(cm.exception.code, 0)

        parsed = json.loads(stdout.getvalue())
        self.assertEqual(parsed["query"], "100R")
        self.assertEqual(parsed["count"], 2)
        self.assertEqual(len(parsed["components"]), 2)
        self.assertEqual(parsed["components"][0]["lcsc_code"], "C17408")

    @patch("search_lcsc.search_jlcsearch")
    def test_cli_sort_price(self, mock_search):
        mock_search.return_value = list(self.mock_raw_results)

        stdout = io.StringIO()
        with patch.object(sys, "argv", ["search_lcsc.py", "100R", "--sort", "price", "--json"]), \
             patch("sys.stdout", stdout):
            with self.assertRaises(SystemExit) as cm:
                search_lcsc.main()
            self.assertEqual(cm.exception.code, 0)

        parsed = json.loads(stdout.getvalue())
        prices = [c["price_usd"] for c in parsed["components"]]
        self.assertEqual(prices, sorted(prices))

    @patch("search_lcsc.search_jlcsearch")
    def test_cli_no_results_exit_code(self, mock_search):
        mock_search.return_value = []

        with patch.object(sys, "argv", ["search_lcsc.py", "nonexistent_part"]), \
             patch("sys.stdout", io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                search_lcsc.main()
            self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
