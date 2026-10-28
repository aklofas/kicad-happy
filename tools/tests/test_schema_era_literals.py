# tools/tests/test_schema_era_literals.py
"""Every finding emit site carries a literal schema_era."""
import ast, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FACTORIES = {"make_finding", "_make_finding"}
DICT_RULES = {"RS-001", "PP-001"}


def _sources():
    yield from sorted((ROOT / "skills" / "kicad" / "scripts").rglob("*.py"))
    yield ROOT / "skills" / "emc" / "scripts" / "emc_rules.py"


def _scan():
    """Return (missing, values): emit sites lacking a literal era, and every literal era value found."""
    missing, values = [], []
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
                if name not in FACTORIES:
                    continue
                kw = {k.arg: k.value for k in node.keywords}
                v = kw.get("schema_era")
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    values.append(v.value)
                else:
                    missing.append(f"{path.relative_to(ROOT)}:{node.lineno}")
            elif isinstance(node, ast.Dict):
                keys = {k.value: v for k, v in zip(node.keys, node.values)
                        if isinstance(k, ast.Constant)}
                rid = keys.get("rule_id")
                if isinstance(rid, ast.Constant) and rid.value in DICT_RULES and "detector" in keys:
                    v = keys.get("schema_era")
                    if isinstance(v, ast.Constant) and isinstance(v.value, str):
                        values.append(v.value)
                    else:
                        missing.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return missing, values


class SchemaEraLiterals(unittest.TestCase):
    def test_every_site_tagged(self):
        missing, _ = _scan()
        self.assertEqual(missing, [])

    def test_value_set(self):
        _, values = _scan()
        self.assertEqual(set(values), {"v1.4", "v3.0"})

    def test_v3_site_count(self):
        _, values = _scan()
        self.assertEqual(values.count("v3.0"), 97)


if __name__ == "__main__":
    unittest.main()
