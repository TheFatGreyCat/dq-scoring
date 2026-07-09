from __future__ import annotations

import argparse
import json
from pathlib import Path

from persistence.postgres import apply_migrations
from persistence.repository import DqPostgresRepository
from persistence.seed import build_seed_plan


DEFAULT_DATASETS = [
    "customer_master",
    "amazon",
    "bank_transaction_fraud_detection",
    "retail_sales_dataset",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage DQ Scoring V2 PostgreSQL storage")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("migrate", help="Apply PostgreSQL migrations")

    seed_parser = subparsers.add_parser("seed", help="Seed V2 metadata from legacy sample YAML")
    seed_parser.add_argument("--root", default=".", help="Repository root")
    seed_parser.add_argument("--dataset", action="append", dest="datasets", help="Dataset id to seed; repeatable")

    reset_parser = subparsers.add_parser("reset", help="Truncate V2 runtime tables")
    reset_parser.add_argument("--yes", action="store_true", help="Required confirmation for destructive local reset")

    args = parser.parse_args()
    if args.command == "migrate":
        print(json.dumps({"applied": apply_migrations()}, indent=2))
        return
    if args.command == "seed":
        datasets = args.datasets or DEFAULT_DATASETS
        plan = build_seed_plan(Path(args.root), datasets)
        counts = DqPostgresRepository().save_seed_plan(plan)
        print(json.dumps({"seeded": counts}, indent=2))
        return
    if args.command == "reset":
        if not args.yes:
            raise SystemExit("Refusing to reset without --yes")
        DqPostgresRepository().reset_v2_data()
        print(json.dumps({"reset": True}, indent=2))


if __name__ == "__main__":
    main()
