"""Translate host connection settings into container networking without logging secrets."""

from __future__ import annotations

import logging
import os

from psycopg import ProgrammingError
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from dq_scoring.common.protected_transport import (
    ProtectedTransportError,
    require_protected_dsn,
)
from dq_scoring.workers.daemon import run_daemon


def main() -> None:
    try:
        dsn = os.environ["DQ_WORKER_POSTGRES_DSN"]
        if not dsn:
            raise ValueError("missing DSN")
        parameters = conninfo_to_dict(dsn)
        parameters.update(
            host=os.environ.get("DQ_WORKER_POSTGRES_HOST", "postgres"),
            port=os.environ.get("DQ_WORKER_POSTGRES_PORT", "5432"),
        )
        final_dsn = make_conninfo(**parameters)
        final_dsn = require_protected_dsn(final_dsn)
        os.environ["DQ_WORKER_POSTGRES_DSN"] = final_dsn
    except (KeyError, ValueError, ProgrammingError, ProtectedTransportError):
        logging.getLogger(__name__).error("CONFIGURATION_ERROR")
        raise SystemExit(1) from None
    run_daemon()


if __name__ == "__main__":
    main()
