import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / ".github" / "scripts" / "check-schema-parity.py"
spec = importlib.util.spec_from_file_location("schema_parity", SCRIPT)
schema_parity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(schema_parity)


class SchemaParityTests(unittest.TestCase):
    def test_checked_in_helm_schema_matches_canonical_local_schema(self):
        root = Path(__file__).resolve().parents[1]
        self.assertTrue(schema_parity.check_schema_parity(root))

    def test_schema_mismatch_fails_with_canonical_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / schema_parity.CANONICAL).parent.mkdir(parents=True)
            (root / schema_parity.HELM_MIRROR).parent.mkdir(parents=True)
            (root / schema_parity.CANONICAL).write_text("CREATE TABLE safe;\n", encoding="utf-8")
            (root / schema_parity.HELM_MIRROR).write_text("CREATE TABLE changed;\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"database[\\/]init.sql"):
                schema_parity.check_schema_parity(root)


if __name__ == "__main__":
    unittest.main()
