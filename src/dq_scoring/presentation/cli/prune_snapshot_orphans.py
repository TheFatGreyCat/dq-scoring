"""Delete orphaned object versions of expired terminal import sessions without touching live snapshot roots.

Dry-run lists candidates; apply deletes exact non-null versions after rechecking live roots and HEAD.
Historical snapshots, reports and WORM retention are never rewritten or bypassed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg
from botocore.exceptions import BotoCoreError, ClientError

from dq_scoring.adapters.db.postgres_import_store import PostgresImportStore
from dq_scoring.adapters.db.tenant_context import set_tenant_context
from dq_scoring.adapters.storage.s3_object_store import S3ObjectStoreAdapter
from dq_scoring.adapters.storage.s3_settings import S3Settings, get_s3_settings
from dq_scoring.adapters.storage.source_settings import SourceStoreSettings
from dq_scoring.ports.object_store import IObjectStorePort, ObjectRef

MIN_AGE_HOURS = 24
LOCK_TIMEOUT = "5s"
TERMINAL = ("REGISTERED", "FAILED", "REJECTED", "ABORTED")
ACTIVE = ("INITIATED", "UPLOADING", "STAGED", "VERIFYING", "VERIFIED")

Root = tuple[str, str, str | None]


class PruneAborted(Exception):
    """Fail-closed condition carrying the fixed status code reported to the operator."""

    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


def _version(value: Any) -> str | None:
    return value if isinstance(value, str) and value not in ("", "null") else None


def _collect_roots(node: Any, out: set[Root]) -> None:
    """Recursively gather every {bucket,key[,version_id]} dict found in JSON."""
    if isinstance(node, dict):
        bucket, key = node.get("bucket"), node.get("key")
        if isinstance(bucket, str) and isinstance(key, str):
            out.add((bucket, key, _version(node.get("version_id"))))
        for child in node.values():
            _collect_roots(child, out)
    elif isinstance(node, list):
        for child in node:
            _collect_roots(child, out)


def load_live_roots(conn: psycopg.Connection, tenant_id: UUID, s3: S3Settings, now: datetime) -> set[Root]:
    """Every object reference that a snapshot, run or still-usable session can read."""
    roots: set[Root] = set()
    with conn.cursor() as cur:
        cur.execute("SELECT source_descriptor, manifest FROM dataset_snapshots WHERE tenant_id = %s", (tenant_id,))
        for row in cur.fetchall():
            _collect_roots(list(row), roots)
        cur.execute(
            "SELECT outlier_config->'_run_spec'->'snapshot' FROM evaluation_runs WHERE tenant_id = %s", (tenant_id,)
        )
        for (snapshot,) in cur.fetchall():
            _collect_roots(snapshot, roots)
        cur.execute(
            "SELECT staging_key, manifest FROM dataset_upload_sessions "
            "WHERE tenant_id = %s AND (expires_at >= %s OR status = ANY(%s))",
            (tenant_id, now, list(ACTIVE)),
        )
        for staging_key, manifest in cur.fetchall():
            manifest = manifest or {}
            _collect_roots(manifest, roots)
            selected = manifest.get("source_ref") or {}
            bucket = manifest.get("staging_bucket")
            buckets = [bucket] if isinstance(bucket, str) else [s3.bucket_staging, s3.bucket_snapshots]
            for b in buckets:
                roots.add((b, staging_key, _version(selected.get("version_id"))))
    return roots


def _is_live(roots: set[Root], ref: ObjectRef) -> bool:
    # A key root without a version conservatively protects every version of the key.
    return (ref.bucket, ref.key, None) in roots or (ref.bucket, ref.key, ref.version_id) in roots


def _scan_targets(session: dict[str, Any], tenant_id: UUID, s3: S3Settings, source: SourceStoreSettings) -> list[tuple[str, str, bool]]:
    """(bucket, prefix-or-key, is_exact_key) pairs owned by this session only."""
    upload_id = session["upload_id"]
    manifest = session["manifest"] or {}
    targets = [(s3.bucket_snapshots, f"snapshots/{tenant_id}/{upload_id}/", False)]
    bucket = manifest.get("staging_bucket") or s3.bucket_staging
    key = session["staging_key"]
    owned_prefixes = (f"snapshots/{tenant_id}/{upload_id}/", f"staging/{tenant_id}/{upload_id}/", f"imports/{tenant_id}/{upload_id}/")
    if (
        not manifest.get("source_ref")
        and bucket in (s3.bucket_staging, s3.bucket_snapshots)
        and not (source.enabled and bucket == source.bucket)
        and key.startswith(owned_prefixes)
        and ".." not in key.split("/")
    ):
        targets.append((bucket, key, True))
    return targets


def prune_orphans(
    conn: psycopg.Connection,
    store: IObjectStorePort,
    s3: S3Settings,
    source: SourceStoreSettings,
    *,
    tenant_id: UUID,
    apply: bool,
    older_than_hours: int = MIN_AGE_HOURS,
    now: datetime | None = None,
) -> tuple[int, dict[str, Any]]:
    """Run inside a caller-managed transaction. Returns (exit_code, report)."""
    if older_than_hours < MIN_AGE_HOURS:
        raise PruneAborted("OLDER_THAN_TOO_SMALL")
    try:
        source.validate_owned_separation(s3)
    except ValueError as exc:
        raise PruneAborted("SOURCE_BUCKET_OVERLAP") from exc
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=older_than_hours)

    conn.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
    set_tenant_context(conn, tenant_id)
    if apply:
        PostgresImportStore.lock_tenant_storage(conn, tenant_id, exclusive=True)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT upload_id, status, staging_key, manifest FROM dataset_upload_sessions "
            "WHERE tenant_id = %s AND status = ANY(%s) AND expires_at < %s AND updated_at < %s AND created_at < %s "
            "ORDER BY created_at, upload_id" + (" FOR UPDATE" if apply else ""),
            (tenant_id, list(TERMINAL), now, cutoff, cutoff),
        )
        sessions = [
            {"upload_id": r[0], "status": r[1], "staging_key": r[2], "manifest": r[3]} for r in cur.fetchall()
        ]

    roots = load_live_roots(conn, tenant_id, s3, now)
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str | None]] = set()
    unreclaimed = 0
    try:
        for session in sessions:
            for bucket, target, exact in _scan_targets(session, tenant_id, s3, source):
                for meta in store.list_versions(bucket, target):
                    ref = meta.ref
                    if (exact and ref.key != target) or (ref.bucket, ref.key, ref.version_id) in seen:
                        continue
                    seen.add((ref.bucket, ref.key, ref.version_id))
                    item = {
                        "upload_id": str(session["upload_id"]),
                        "bucket": ref.bucket,
                        "key": ref.key,
                        "version_id": ref.version_id,
                        "size_bytes": meta.size_bytes,
                    }
                    if ref.version_id is None:
                        unreclaimed += meta.size_bytes
                        item["status"] = "UNVERSIONED_SKIPPED"
                    elif meta.last_modified is None or meta.last_modified >= cutoff:
                        item["status"] = "SKIPPED_RECENT"
                    elif _is_live(roots, ref):
                        item["status"] = "SKIPPED_LIVE_ROOT"
                    else:
                        item["status"] = "CANDIDATE"
                        item["_ref"] = ref
                    items.append(item)
    except (FileNotFoundError, PermissionError, ClientError, BotoCoreError, OSError) as exc:
        raise PruneAborted("STORAGE_UNAVAILABLE") from exc

    for item in items:
        ref = item.pop("_ref", None)
        if ref is None:
            continue
        if not apply:
            item["status"] = "WOULD_DELETE"
            continue
        item["status"] = _delete_checked(conn, store, tenant_id, s3, now, cutoff, ref)

    counts: dict[str, int] = {}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    failed = counts.get("BLOCKED", 0) + counts.get("FAILED", 0)
    status = "BLOCKED" if counts.get("BLOCKED") else "FAILED" if counts.get("FAILED") else "OK"
    report = {
        "status": status,
        "mode": "apply" if apply else "dry-run",
        "tenant_id": str(tenant_id),
        "older_than_hours": older_than_hours,
        "sessions": len(sessions),
        "counts": counts,
        "unversioned_bytes_not_reclaimed": unreclaimed,
        "candidates": items,
    }
    return (1 if failed else 0), report


def _delete_checked(
    conn: psycopg.Connection,
    store: IObjectStorePort,
    tenant_id: UUID,
    s3: S3Settings,
    now: datetime,
    cutoff: datetime,
    ref: ObjectRef,
) -> str:
    # Roots re-read and exact version re-HEADed immediately before each delete.
    if _is_live(load_live_roots(conn, tenant_id, s3, now), ref):
        return "SKIPPED_LIVE_ROOT"
    try:
        head = store.head(ref)
        if head.last_modified is None or head.last_modified >= cutoff:
            return "SKIPPED_RECENT"
        store.delete_version(ref)
        return "DELETED"
    except FileNotFoundError:
        return "ALREADY_ABSENT"
    except PermissionError:
        return "BLOCKED"
    except (ClientError, BotoCoreError, OSError):
        return "FAILED"


def _hours(value: str) -> int:
    hours = int(value)
    if hours < MIN_AGE_HOURS:
        raise argparse.ArgumentTypeError(f"must be >= {MIN_AGE_HOURS}")
    return hours


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--older-than-hours", type=_hours, default=MIN_AGE_HOURS)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    dsn = os.getenv("DQ_MIGRATION_POSTGRES_DSN")
    if not dsn:
        print(json.dumps({"status": "MIGRATION_DSN_REQUIRED"}))
        return 2
    try:
        s3 = get_s3_settings()
        source = SourceStoreSettings()
        store = S3ObjectStoreAdapter(settings=s3)
        with psycopg.connect(dsn) as conn, conn.transaction():
            code, report = prune_orphans(
                conn, store, s3, source, tenant_id=args.tenant_id, apply=args.apply,
                older_than_hours=args.older_than_hours,
            )
    except PruneAborted as exc:
        print(json.dumps({"status": exc.status}))
        return 1
    except psycopg.errors.LockNotAvailable:
        print(json.dumps({"status": "STORAGE_BUSY"}))
        return 1
    except (psycopg.Error, ValueError):
        print(json.dumps({"status": "PRUNE_PRECONDITION_FAILED"}))
        return 1
    print(json.dumps(report))
    return code


if __name__ == "__main__":
    sys.exit(main())
