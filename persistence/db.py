from __future__ import annotations

import argparse
import json

from persistence.postgres import apply_migrations
from persistence.repository import DqPostgresRepository


DEFAULT_DATASETS = [
    "customer_master",
    "amazon",
    "bank_transaction_fraud_detection",
    "retail_sales_dataset",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage DQ Scoring PostgreSQL storage")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("migrate", help="Apply PostgreSQL migrations")

    reset_parser = subparsers.add_parser("reset", help="Truncate runtime tables")
    reset_parser.add_argument("--yes", action="store_true", help="Required confirmation for destructive local reset")

    args = parser.parse_args()
    if args.command == "migrate":
        print(json.dumps({"applied": apply_migrations()}, indent=2))
        return
    if args.command == "reset":
        if not args.yes:
            raise SystemExit("Refusing to reset without --yes")
        DqPostgresRepository().reset_v2_data()
        print(json.dumps({"reset": True}, indent=2))


if __name__ == "__main__":
    main()
