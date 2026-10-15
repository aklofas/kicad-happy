import json, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools import check_refactor as cr


class CompareJson(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(cr.compare_json({"a": [1, {"b": None}]}, {"a": [1, {"b": None}]}, set()), [])

    def test_value_change_reports_path(self):
        d = cr.compare_json({"a": {"b": 1}}, {"a": {"b": 2}}, set())
        self.assertEqual(d, [("a.b", "value", 1, 2)])

    def test_absent_vs_null_differ(self):
        d = cr.compare_json({"a": {}}, {"a": {"b": None}}, set())
        self.assertEqual(d, [("a.b", "added", None, None)])

    def test_bool_vs_int_differ(self):
        d = cr.compare_json({"a": True}, {"a": 1}, set())
        self.assertEqual(d[0][:2], ("a", "type"))

    def test_list_order_matters(self):
        d = cr.compare_json({"a": [1, 2]}, {"a": [2, 1]}, set())
        self.assertEqual([x[1] for x in d], ["value", "value"])
        self.assertEqual(d[0][0], "a[0]")

    def test_list_length(self):
        d = cr.compare_json({"a": [1]}, {"a": [1, 2]}, set())
        self.assertEqual(d, [("a", "length", 1, 2)])

    def test_volatile_leaf_masked(self):
        d = cr.compare_json({"inputs": {"run_id": "x"}}, {"inputs": {"run_id": "y"}}, {"inputs.run_id"})
        self.assertEqual(d, [])

    def test_volatile_wildcard_in_list(self):
        d = cr.compare_json({"f": [{"t": 1}, {"t": 2}]}, {"f": [{"t": 9}, {"t": 8}]}, {"f[*].t"})
        self.assertEqual(d, [])

    def test_key_order_reported_separately(self):
        d = cr.compare_json({"a": 1, "b": 2}, {"b": 2, "a": 1}, set())
        self.assertEqual(d, [("", "order", ["a", "b"], ["b", "a"])])


if __name__ == "__main__":
    unittest.main()
