"""Protected transport and runtime configuration validators."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo


class ProtectedTransportError(RuntimeError):
    """Raised when transport or runtime security requirements are not met."""


def is_protected_processing_enabled() -> bool:
    """Return True if protected processing mode is active."""
    return os.getenv("DQ_PROTECTED_PROCESSING_ENABLED", "").strip().lower() in (
        "true",
        "1",
        "yes",
    )


def require_protected_dsn(dsn: str) -> str:
    """Verify that PostgreSQL DSN satisfies protected transport invariants (verify-full + rootcert).

    Returns the validated DSN, or raises ProtectedTransportError without leaking credentials.
    """
    if not is_protected_processing_enabled():
        return dsn

    try:
        params = conninfo_to_dict(dsn)
    except (psycopg.ProgrammingError, ValueError):
        raise ProtectedTransportError(
            "PROTECTED_TRANSPORT_CONFIGURATION_REQUIRED: invalid database DSN"
        ) from None

    sslmode = params.get("sslmode")
    if sslmode != "verify-full":
        raise ProtectedTransportError(
            "PROTECTED_TRANSPORT_CONFIGURATION_REQUIRED: sslmode must be verify-full in protected processing mode"
        )

    rootcert = params.get("sslrootcert")
    if rootcert:
        if not Path(rootcert).is_file():
            raise ProtectedTransportError(
                "PROTECTED_TRANSPORT_CONFIGURATION_REQUIRED: specified sslrootcert file does not exist"
            )
        return dsn

    sec_dir = os.getenv("DQ_SECURITY_DIR", "/opt/dq/security")
    default_ca = Path(sec_dir) / "postgres-ca.pem"
    if not default_ca.is_file():
        raise ProtectedTransportError(
            "PROTECTED_TRANSPORT_CONFIGURATION_REQUIRED: sslrootcert not specified in DSN and default postgres-ca.pem not found"
        )

    params["sslrootcert"] = str(default_ca)
    return make_conninfo(**params)


def validate_protected_runtime(role: str) -> None:
    """Verify that required TLS certificates, CA bundles, and scratch paths exist for role."""
    if not is_protected_processing_enabled():
        return

    sec_dir = Path(os.getenv("DQ_SECURITY_DIR", "/opt/dq/security"))
    scratch_dir = Path(os.getenv("DQ_IMPORT_TEMP_ROOT", "/opt/dq/scratch"))

    if not scratch_dir.is_dir():
        raise ProtectedTransportError(
            "PROTECTED_TRANSPORT_CONFIGURATION_REQUIRED: scratch directory is missing or not a directory"
        )

    pg_ca = sec_dir / "postgres-ca.pem"
    s3_ca = Path(os.getenv("DQ_S3_CA_BUNDLE", str(sec_dir / "s3-ca.pem")))
    if not pg_ca.is_file() or not s3_ca.is_file():
        raise ProtectedTransportError(
            f"PROTECTED_TRANSPORT_CONFIGURATION_REQUIRED: missing required CA files for role {role}"
        )

    if role == "api":
        api_cert = Path(os.getenv("DQ_API_TLS_CERT", str(sec_dir / "tls.crt")))
        api_key = Path(os.getenv("DQ_API_TLS_KEY", str(sec_dir / "tls.key")))
        if not api_cert.is_file() or not api_key.is_file():
            raise ProtectedTransportError(
                "PROTECTED_TRANSPORT_CONFIGURATION_REQUIRED: API TLS certificate and private key are required"
            )
    elif role in ("worker", "evaluation"):
        spark_files = [
            sec_dir / "rpc-auth",
            sec_dir / "keystore.jks",
            sec_dir / "truststore.jks",
            sec_dir / "spark-defaults.conf",
        ]
        if any(not f.is_file() for f in spark_files):
            raise ProtectedTransportError(
                "PROTECTED_TRANSPORT_CONFIGURATION_REQUIRED: Spark security files are required for worker"
            )
    elif role == "import":
        pass
    else:
        raise ValueError(f"Unknown protected runtime role: {role}")


def protected_connect(dsn: str, **kwargs: Any) -> psycopg.Connection:
    """Validate DSN before connecting to PostgreSQL."""
    validated_dsn = require_protected_dsn(dsn)
    return psycopg.connect(validated_dsn, **kwargs)
