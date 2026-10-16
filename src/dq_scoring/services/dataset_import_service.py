"""Service for dataset import session finalization and snapshot registration."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from dq_scoring.common.privacy import generate_finding_id
from dq_scoring.core.entities import DatasetSnapshot


class ImportRegistrationError(Exception):
    """Raised when dataset snapshot registration fails business rules or invariant checks."""

    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail

class DatasetImportService:
    """Orchestrates asset creation, snapshot immutability, and import session registration."""

    @classmethod
    def register_snapshot(
        cls,
        conn: psycopg.Connection,
        *,
        upload_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
        acknowledged_warnings: list[str],
    ) -> DatasetSnapshot:
        now = datetime.now(UTC)

        with conn.cursor() as cur:
            # 1. Lock and retrieve upload session
            cur.execute(
                """
                SELECT upload_id, tenant_id, asset_id, asset_name, format, status,
                       staging_key, destination_location, manifest, original_filename,
                       size_bytes, registered_snapshot_id, expires_at
                FROM dataset_upload_sessions
                WHERE upload_id = %s AND tenant_id = %s
                FOR UPDATE;
                """,
                (upload_id, tenant_id),
            )
            row = cur.fetchone()
            if not row:
                raise ImportRegistrationError("RESOURCE_NOT_FOUND", "Import session not found.")

            session_status = row[5]
            registered_snapshot_id = row[11]
            manifest = row[8] or {}

            # Idempotent response if already registered
            if session_status == "REGISTERED" and registered_snapshot_id:
                cur.execute(
                    """
                    SELECT snapshot_id, tenant_id, asset_id, source_kind, source_descriptor,
                           schema_definition, total_rows, total_columns, captured_at
                    FROM dataset_snapshots
                    WHERE snapshot_id = %s AND tenant_id = %s;
                    """,
                    (registered_snapshot_id, tenant_id),
                )
                snap_row = cur.fetchone()
                if snap_row:
                    return DatasetSnapshot(
                        snapshot_id=snap_row[0],
                        tenant_id=snap_row[1],
                        asset_id=snap_row[2],
                        source_kind=snap_row[3],
                        source_descriptor=snap_row[4],
                        schema_definition=snap_row[5],
                        total_rows=snap_row[6],
                        total_columns=snap_row[7],
                        captured_at=snap_row[8],
                    )

            if row[12] and row[12] < now:
                raise ImportRegistrationError("IMPORT_EXPIRED", "Import session has expired.")
            if session_status != "VERIFIED":
                raise ImportRegistrationError("IMPORT_STATE_CONFLICT", f"Session cannot be registered in status '{session_status}'.")

            # Check warning acknowledgment
            warnings = manifest.get("warnings") or []
            if "SINGLE_COLUMN_INPUT" in warnings and "SINGLE_COLUMN_INPUT" not in acknowledged_warnings:
                raise ImportRegistrationError("WARNING_ACKNOWLEDGMENT_REQUIRED", "SINGLE_COLUMN_INPUT requires explicit confirmation.")

            asset_id = row[2]
            asset_name = row[3]
            source_desc = manifest.get("source_descriptor")
            if not source_desc:
                raise ImportRegistrationError("MALFORMED_IMPORT", "Session manifest missing source_descriptor.")

            columns = manifest.get("columns") or []
            total_rows = int(manifest.get("exact_row_count") or 0)
            raw_sha256 = source_desc.get("content_sha256")
            canonical_info = source_desc.get("canonical", {})
            storage_loc = canonical_info.get("s3a_uri") or f"s3a://{canonical_info.get('bucket')}/{canonical_info.get('key')}"

            # 2. Resolve or create asset
            if asset_id is None:
                # Create new asset
                clean_name = asset_name.strip()
                slug_base = re.sub(r"[^a-z0-9]+", "-", clean_name.lower()).strip("-")
                asset_id = uuid4()
                slug = f"{slug_base}-{asset_id.hex[:6]}"

                cur.execute(
                    """
                    INSERT INTO data_assets (
                        asset_id, tenant_id, asset_name, slug, format,
                        owner_user_id, created_by, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s
                    )
                    ON CONFLICT (tenant_id, asset_name) DO NOTHING
                    RETURNING asset_id;
                    """,
                    (asset_id, tenant_id, clean_name, slug, row[4], user_id, user_id, now),
                )
                ins_row = cur.fetchone()
                if not ins_row:
                    raise ImportRegistrationError("ASSET_NAME_CONFLICT", f"Data Asset with name '{clean_name}' already exists.")
            else:
                # Lock existing asset
                cur.execute(
                    "SELECT asset_id FROM data_assets WHERE tenant_id = %s AND asset_id = %s FOR UPDATE;",
                    (tenant_id, asset_id),
                )
                if not cur.fetchone():
                    raise ImportRegistrationError("RESOURCE_NOT_FOUND", "Target Data Asset not found.")

            # 3. Check duplicate raw hash for same asset
            cur.execute(
                """
                SELECT snapshot_id, source_descriptor
                FROM dataset_snapshots
                WHERE tenant_id = %s AND asset_id = %s AND content_sha256 = %s AND source_kind = 'OBJECT_FILE';
                """,
                (tenant_id, asset_id, raw_sha256),
            )
            existing_snap = cur.fetchone()
            if existing_snap:
                existing_desc = existing_snap[1]
                if existing_desc.get("canonical", {}).get("content_sha256") == canonical_info.get("content_sha256"):
                    # Same raw hash + same canonical hash -> return existing snapshot idempotently
                    cur.execute(
                        """
                        UPDATE dataset_upload_sessions
                        SET status = 'REGISTERED',
                            asset_id = %s,
                            registered_snapshot_id = %s,
                            updated_at = now()
                        WHERE upload_id = %s AND tenant_id = %s;
                        """,
                        (asset_id, existing_snap[0], upload_id, tenant_id),
                    )
                    cur.execute(
                        """
                        SELECT snapshot_id, tenant_id, asset_id, source_kind, source_descriptor,
                               schema_definition, total_rows, total_columns, captured_at
                        FROM dataset_snapshots
                        WHERE snapshot_id = %s AND tenant_id = %s;
                        """,
                        (existing_snap[0], tenant_id),
                    )
                    s_row = cur.fetchone()
                    return DatasetSnapshot(
                        snapshot_id=s_row[0],
                        tenant_id=s_row[1],
                        asset_id=s_row[2],
                        source_kind=s_row[3],
                        source_descriptor=s_row[4],
                        schema_definition=s_row[5],
                        total_rows=s_row[6],
                        total_columns=s_row[7],
                        captured_at=s_row[8],
                    )
                else:
                    raise ImportRegistrationError("REIMPORT_MAPPING_CONFLICT", "Same raw data already imported with different column mapping.")

            # 4. Version calculation
            cur.execute(
                "SELECT COALESCE(MAX(version_number), 0) + 1 FROM dataset_snapshots WHERE tenant_id = %s AND asset_id = %s;",
                (tenant_id, asset_id),
            )
            version_num = cur.fetchone()[0]

            snapshot_id = uuid4()
            sensitive_scan = manifest.get("sensitive_scan") or {}
            schema_definition = {
                "columns": columns,
                "privacy": {
                    "detector_revision": sensitive_scan.get("detector_revision", "builtin-v1"),
                    "sensitive_columns": sensitive_scan.get("sensitive_columns", []),
                },
            }
            parent_snapshot_id_raw = manifest.get("parent_snapshot_id")
            parent_snapshot_id = UUID(str(parent_snapshot_id_raw)) if parent_snapshot_id_raw else None

            # 5. Insert immutable Dataset Snapshot
            cur.execute(
                """
                INSERT INTO dataset_snapshots (
                    snapshot_id, tenant_id, asset_id, version_number, version_status,
                    parent_snapshot_id, source_kind, source_descriptor, content_sha256, storage_location,
                    schema_definition, total_rows, total_columns, created_by, captured_at,
                    manifest
                ) VALUES (
                    %s, %s, %s, %s, 'ACTIVE',
                    %s, 'OBJECT_FILE', %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s
                )
                RETURNING snapshot_id, tenant_id, asset_id, source_kind, source_descriptor,
                          schema_definition, total_rows, total_columns, captured_at;
                """,
                (
                    snapshot_id,
                    tenant_id,
                    asset_id,
                    version_num,
                    parent_snapshot_id,
                    Jsonb(source_desc),
                    raw_sha256,
                    storage_loc,
                    Jsonb(schema_definition),
                    total_rows,
                    len(columns),
                    user_id,
                    now,
                    Jsonb(manifest),
                ),
            )
            snap_row = cur.fetchone()

            # Import findings retain the exact pinned detector configuration and scan identity.
            scan_id = None
            if manifest.get("privacy_config_version") is not None:
                scan_id = uuid4()
                cur.execute(
                    """INSERT INTO privacy_scan_jobs(scan_id,tenant_id,snapshot_id,requested_by,state,purpose,
                       pinned_rules,config_version,detector_digest,started_at,finished_at,result_summary)
                       VALUES(%s,%s,%s,%s,'COMPLETE','APPLY',%s,%s,%s,%s,%s,%s)""",
                    (scan_id,tenant_id,snapshot_id,user_id,Jsonb(manifest.get("privacy_rules",[])),
                     manifest["privacy_config_version"],manifest["privacy_detector_digest"],now,now,
                     Jsonb({"total_rows": total_rows, "scope_missing_columns": sensitive_scan.get("scope_missing_columns",[])})),
                )
            for finding in sensitive_scan.get("findings") or []:
                col_name, path = finding["column_name"], finding.get("path", "")
                code, revision = finding.get("detector_code"), finding.get("detector_revision", "builtin-v1")
                finding_id = generate_finding_id(scan_id or snapshot_id, col_name, path, code, revision)
                cur.execute(
                    """INSERT INTO sensitive_data_findings (
                       finding_id,tenant_id,snapshot_id,column_name,path,category,confidence_score,status,detected_at,
                       detector_code,detector_revision,matched_count,observed_count,detection_method,
                       detected_by_rule_id,privacy_rule_revision,scan_id)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,'DETECTED',%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT DO NOTHING""",
                    (finding_id,tenant_id,snapshot_id,col_name,path,finding["category"],finding.get("confidence_score",1.0),now,
                     code,revision,finding.get("matched_count",0),finding.get("observed_count",0),finding.get("method","VALUE_PATTERN"),
                     finding.get("rule_id"),finding.get("rule_revision") if finding.get("rule_id") else None,scan_id),
                )
            # 6. Update data asset version_count and current_snapshot_id
            cur.execute(
                """
                UPDATE data_assets
                SET current_snapshot_id = %s,
                    version_count = version_count + 1
                WHERE tenant_id = %s AND asset_id = %s;
                """,
                (snapshot_id, tenant_id, asset_id),
            )

            # 7. Update dataset_upload_sessions to REGISTERED
            cur.execute(
                """
                UPDATE dataset_upload_sessions
                SET status = 'REGISTERED',
                    asset_id = %s,
                    registered_snapshot_id = %s,
                    updated_at = now()
                WHERE upload_id = %s AND tenant_id = %s;
                """,
                (asset_id, snapshot_id, upload_id, tenant_id),
            )

            return DatasetSnapshot(
                snapshot_id=snap_row[0],
                tenant_id=snap_row[1],
                asset_id=snap_row[2],
                source_kind=snap_row[3],
                source_descriptor=snap_row[4],
                schema_definition=snap_row[5],
                total_rows=snap_row[6],
                total_columns=snap_row[7],
                captured_at=snap_row[8],
            )
