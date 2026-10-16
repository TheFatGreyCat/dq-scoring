"""Unit tests for protected transport validation and runtime checks."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from dq_scoring.common.protected_transport import (
    ProtectedTransportError,
    is_protected_processing_enabled,
    protected_connect,
    require_protected_dsn,
    validate_protected_runtime,
)


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [
        "DQ_PROTECTED_PROCESSING_ENABLED",
        "DQ_SECURITY_DIR",
        "DQ_IMPORT_TEMP_ROOT",
        "DQ_S3_CA_BUNDLE",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_is_protected_processing_disabled_by_default() -> None:
    assert not is_protected_processing_enabled()


@pytest.mark.parametrize("val", ["true", "1", "yes", "True", "TRUE"])
def test_is_protected_processing_enabled_truthy(monkeypatch: pytest.MonkeyPatch, val: str) -> None:
    monkeypatch.setenv("DQ_PROTECTED_PROCESSING_ENABLED", val)
    assert is_protected_processing_enabled()


@pytest.mark.parametrize("val", ["false", "0", "no", "", "other"])
def test_is_protected_processing_falsy(monkeypatch: pytest.MonkeyPatch, val: str) -> None:
    monkeypatch.setenv("DQ_PROTECTED_PROCESSING_ENABLED", val)
    assert not is_protected_processing_enabled()


def test_require_protected_dsn_passes_through_when_disabled() -> None:
    dsn = "postgresql://myuser:mypassword@localhost:5432/mydb"
    assert require_protected_dsn(dsn) == dsn


def test_require_protected_dsn_rejects_missing_sslmode_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DQ_PROTECTED_PROCESSING_ENABLED", "true")
    dsn = "postgresql://myuser:supersecretpass@localhost:5432/mydb"

    with pytest.raises(ProtectedTransportError) as exc_info:
        require_protected_dsn(dsn)

    msg = str(exc_info.value)
    assert "PROTECTED_TRANSPORT_CONFIGURATION_REQUIRED" in msg
    assert "supersecretpass" not in msg
    assert "myuser" not in msg
    assert "localhost" not in msg


@pytest.mark.parametrize("sslmode", ["disable", "allow", "prefer", "require", "verify-ca"])
def test_require_protected_dsn_rejects_non_verify_full_sslmode(
    monkeypatch: pytest.MonkeyPatch, sslmode: str
) -> None:
    monkeypatch.setenv("DQ_PROTECTED_PROCESSING_ENABLED", "true")
    dsn = f"postgresql://myuser:supersecretpass@localhost:5432/mydb?sslmode={sslmode}"

    with pytest.raises(ProtectedTransportError) as exc_info:
        require_protected_dsn(dsn)

    msg = str(exc_info.value)
    assert "PROTECTED_TRANSPORT_CONFIGURATION_REQUIRED" in msg
    assert "supersecretpass" not in msg


def test_require_protected_dsn_rejects_missing_rootcert_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DQ_PROTECTED_PROCESSING_ENABLED", "true")
    missing_cert = tmp_path / "nonexistent-ca.pem"
    dsn = f"postgresql://myuser:supersecretpass@db.internal:5432/mydb?sslmode=verify-full&sslrootcert={missing_cert}"

    with pytest.raises(ProtectedTransportError) as exc_info:
        require_protected_dsn(dsn)

    msg = str(exc_info.value)
    assert "PROTECTED_TRANSPORT_CONFIGURATION_REQUIRED" in msg
    assert "supersecretpass" not in msg


def test_require_protected_dsn_accepts_valid_verify_full_with_rootcert(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DQ_PROTECTED_PROCESSING_ENABLED", "true")
    cert_file = tmp_path / "postgres-ca.pem"
    cert_file.write_text("-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----")

    dsn = f"postgresql://myuser:supersecretpass@db.internal:5432/mydb?sslmode=verify-full&sslrootcert={cert_file}"
    validated = require_protected_dsn(dsn)
    assert validated == dsn


def test_require_protected_dsn_falls_back_to_default_rootcert_if_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DQ_PROTECTED_PROCESSING_ENABLED", "true")
    monkeypatch.setenv("DQ_SECURITY_DIR", str(tmp_path))
    default_ca = tmp_path / "postgres-ca.pem"
    default_ca.write_text("-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----")

    dsn = "postgresql://myuser:supersecretpass@db.internal:5432/mydb?sslmode=verify-full"
    validated = require_protected_dsn(dsn)
    # The validated DSN attaches or verifies sslrootcert
    assert "sslmode=verify-full" in validated


def test_validate_protected_runtime_noop_when_disabled() -> None:
    # All roles return cleanly without checking filesystem when disabled
    validate_protected_runtime("api")
    validate_protected_runtime("worker")
    validate_protected_runtime("import")


def test_validate_protected_runtime_api_checks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DQ_PROTECTED_PROCESSING_ENABLED", "true")
    sec_dir = tmp_path / "security"
    scratch_dir = tmp_path / "scratch"
    sec_dir.mkdir()
    monkeypatch.setenv("DQ_SECURITY_DIR", str(sec_dir))
    monkeypatch.setenv("DQ_IMPORT_TEMP_ROOT", str(scratch_dir))

    # Missing scratch and certs
    with pytest.raises(ProtectedTransportError, match="PROTECTED_TRANSPORT_CONFIGURATION_REQUIRED"):
        validate_protected_runtime("api")

    # Create scratch
    scratch_dir.mkdir()
    with pytest.raises(ProtectedTransportError, match="PROTECTED_TRANSPORT_CONFIGURATION_REQUIRED"):
        validate_protected_runtime("api")

    # Create API certs
    (sec_dir / "tls.crt").write_text("cert")
    (sec_dir / "tls.key").write_text("key")
    (sec_dir / "postgres-ca.pem").write_text("ca")
    (sec_dir / "s3-ca.pem").write_text("ca")

    # Now all required files for API exist
    validate_protected_runtime("api")


def test_validate_protected_runtime_worker_checks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DQ_PROTECTED_PROCESSING_ENABLED", "true")
    sec_dir = tmp_path / "security"
    scratch_dir = tmp_path / "scratch"
    sec_dir.mkdir()
    scratch_dir.mkdir()
    monkeypatch.setenv("DQ_SECURITY_DIR", str(sec_dir))
    monkeypatch.setenv("DQ_IMPORT_TEMP_ROOT", str(scratch_dir))

    (sec_dir / "postgres-ca.pem").write_text("ca")
    (sec_dir / "s3-ca.pem").write_text("ca")

    # Missing spark rpc-auth / keystore / truststore / spark-defaults.conf
    with pytest.raises(ProtectedTransportError, match="PROTECTED_TRANSPORT_CONFIGURATION_REQUIRED"):
        validate_protected_runtime("worker")

    (sec_dir / "rpc-auth").write_text("secret")
    (sec_dir / "keystore.jks").write_bytes(b"jks")
    (sec_dir / "truststore.jks").write_bytes(b"jks")
    (sec_dir / "spark-defaults.conf").write_text("conf")

    validate_protected_runtime("worker")


def test_validate_protected_runtime_import_checks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DQ_PROTECTED_PROCESSING_ENABLED", "true")
    sec_dir = tmp_path / "security"
    scratch_dir = tmp_path / "scratch"
    sec_dir.mkdir()
    scratch_dir.mkdir()
    monkeypatch.setenv("DQ_SECURITY_DIR", str(sec_dir))
    monkeypatch.setenv("DQ_IMPORT_TEMP_ROOT", str(scratch_dir))

    # Missing CAs
    with pytest.raises(ProtectedTransportError, match="PROTECTED_TRANSPORT_CONFIGURATION_REQUIRED"):
        validate_protected_runtime("import")

    (sec_dir / "postgres-ca.pem").write_text("ca")
    (sec_dir / "s3-ca.pem").write_text("ca")

    # Import role doesn't need Spark keystore / rpc-auth
    validate_protected_runtime("import")


def test_protected_connect_blocks_insecure_dsn_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DQ_PROTECTED_PROCESSING_ENABLED", "true")
    dsn = "postgresql://user:pass@127.0.0.1:5432/db"

    with patch("psycopg.connect") as mock_conn:
        with pytest.raises(ProtectedTransportError):
            protected_connect(dsn)
        mock_conn.assert_not_called()
