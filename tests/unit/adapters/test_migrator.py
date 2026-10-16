"""Unit tests for the migration runner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dq_scoring.adapters.db.migrator import apply_all_migrations


def test_missing_migrations_dir_fails_instead_of_using_another_copy(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        apply_all_migrations(MagicMock(), tmp_path / "missing")
