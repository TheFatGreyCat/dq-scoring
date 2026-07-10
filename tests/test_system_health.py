from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from dq_core.health import get_system_health


class FakeCursor:
    def __init__(self) -> None:
        self.sql = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, sql: str, params=None) -> None:
        self.sql = sql

    def fetchone(self):
        if "current_database" in self.sql:
            return ("dq_scoring",)
        if "to_regclass('public.schema_migration')" in self.sql:
            return ("schema_migration",)
        if "migration_name" in self.sql:
            return ("001_core.sql",)
        if "count(*) FROM schema_migration" in self.sql:
            return (1,)
        if "to_regclass('public.rule_template')" in self.sql:
            return ("rule_template",)
        if "count(*) FROM rule_template" in self.sql:
            return (6,)
        return (None,)


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return FakeCursor()


class SystemHealthTests(unittest.TestCase):
    def test_missing_database_url_reports_not_configured(self) -> None:
        with patch("dq_core.health.database_url_from_env", side_effect=RuntimeError("missing")):
            health = get_system_health(upload_dir=Path.cwd())

        self.assertEqual(health["postgresql"]["status"], "not_configured")
        self.assertIn("DQ_DATABASE_URL", health["postgresql"]["error"])

    def test_health_masks_connection_and_detects_schema_catalog(self) -> None:
        with patch("dq_core.health.connect", return_value=FakeConnection()):
            health = get_system_health("postgresql://dq:secret@localhost:5432/dq_scoring", upload_dir=Path.cwd())

        self.assertEqual(health["postgresql"]["status"], "reachable")
        self.assertEqual(health["postgresql"]["host"], "localhost:5432")
        self.assertEqual(health["postgresql"]["database"], "dq_scoring")
        self.assertNotIn("secret", str(health))
        self.assertEqual(health["schema"]["status"], "ready")
        self.assertEqual(health["schema"]["latest_migration"], "001_core.sql")
        self.assertEqual(health["rule_catalog"]["status"], "ready")
        self.assertEqual(health["rule_catalog"]["template_count"], 6)
        self.assertEqual(health["local_llm"]["status"], "not_configured")


if __name__ == "__main__":
    unittest.main()
