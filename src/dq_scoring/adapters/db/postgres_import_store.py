"""Database repository for dataset upload and import sessions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb


class PostgresImportStore:
    """Manages dataset_upload_sessions persistence in PostgreSQL."""

    @staticmethod
    def _hash_advisory_lock(upload_id: UUID, part_number: int) -> int:
        # PostgreSQL advisory lock key: 64-bit signed int
        h = (upload_id.int ^ (part_number * 2654435761)) & 0x7FFFFFFFFFFFFFFF
        return h

    @classmethod
    def create_session(
        cls,
        conn: psycopg.Connection,
        *,
        upload_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
        asset_id: UUID | None,
        asset_name: str | None,
        client_request_id: UUID,
        format: str,
        original_filename: str,
        size_bytes: int,
        staging_key: str,
        destination_location: str | None,
        multipart_id: str | None,
        status: str,
        manifest: dict[str, Any],
        expires_in_hours: int = 24,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        expires_at = now + timedelta(hours=expires_in_hours)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO dataset_upload_sessions (
                    upload_id, tenant_id, asset_id, asset_name, client_request_id,
                    format, original_filename, size_bytes, staging_key, destination_location,
                    multipart_id, status, manifest, created_by, created_at, expires_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING upload_id, tenant_id, asset_id, asset_name, client_request_id,
                          format, original_filename, size_bytes, staging_key, destination_location,
                          multipart_id, status, manifest, error_reason, lease_generation,
                          created_at, expires_at, updated_at, registered_snapshot_id;
                """,
                (
                    upload_id,
                    tenant_id,
                    asset_id,
                    asset_name,
                    client_request_id,
                    format,
                    original_filename,
                    size_bytes,
                    staging_key,
                    destination_location,
                    multipart_id,
                    status,
                    Jsonb(manifest),
                    user_id,
                    now,
                    expires_at,
                    now,
                ),
            )
            row = cur.fetchone()
            return cls._row_to_dict(row)

    @classmethod
    def get_by_client_request(
        cls,
        conn: psycopg.Connection,
        *,
        tenant_id: UUID,
        user_id: UUID,
        client_request_id: UUID,
    ) -> dict[str, Any] | None:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT upload_id, tenant_id, asset_id, asset_name, client_request_id,
                       format, original_filename, size_bytes, staging_key, destination_location,
                       multipart_id, status, manifest, error_reason, lease_generation,
                       created_at, expires_at, updated_at, registered_snapshot_id
                FROM dataset_upload_sessions
                WHERE tenant_id = %s AND created_by = %s AND client_request_id = %s;
                """,
                (tenant_id, user_id, client_request_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            return cls._row_to_dict(row)

    @classmethod
    def get_by_id(
        cls,
        conn: psycopg.Connection,
        *,
        upload_id: UUID,
        tenant_id: UUID,
    ) -> dict[str, Any] | None:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT upload_id, tenant_id, asset_id, asset_name, client_request_id,
                       format, original_filename, size_bytes, staging_key, destination_location,
                       multipart_id, status, manifest, error_reason, lease_generation,
                       created_at, expires_at, updated_at, registered_snapshot_id
                FROM dataset_upload_sessions
                WHERE upload_id = %s AND tenant_id = %s;
                """,
                (upload_id, tenant_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            return cls._row_to_dict(row)

    @classmethod
    def record_part(
        cls,
        conn: psycopg.Connection,
        *,
        upload_id: UUID,
        part_number: int,
        etag: str,
        sha256: str,
        size_bytes: int,
    ) -> None:
        lock_id = cls._hash_advisory_lock(upload_id, part_number)
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s);", (lock_id,))

            part_payload = {
                "part_number": part_number,
                "etag": etag,
                "sha256": sha256,
                "size_bytes": size_bytes,
            }
            cur.execute(
                """
                UPDATE dataset_upload_sessions
                SET manifest = jsonb_set(
                    CASE
                        WHEN manifest ? 'parts' THEN manifest
                        ELSE jsonb_set(COALESCE(manifest, '{}'::jsonb), '{parts}', '{}'::jsonb, true)
                    END,
                    ARRAY['parts', %s::text],
                    %s::jsonb,
                    true
                ),
                status = CASE WHEN status = 'INITIATED' THEN 'UPLOADING' ELSE status END,
                updated_at = now()
                WHERE upload_id = %s;
                """,
                (str(part_number), Jsonb(part_payload), upload_id),
            )

    @classmethod
    def transition_staged(
        cls,
        conn: psycopg.Connection,
        *,
        upload_id: UUID,
        tenant_id: UUID,
        computed_sha256: str | None = None,
        destination_location: str | None = None,
    ) -> dict[str, Any]:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE dataset_upload_sessions
                SET status = 'STAGED',
                    computed_sha256 = COALESCE(%s, computed_sha256),
                    destination_location = COALESCE(%s, destination_location),
                    updated_at = now()
                WHERE upload_id = %s AND tenant_id = %s
                RETURNING upload_id, tenant_id, asset_id, asset_name, client_request_id,
                          format, original_filename, size_bytes, staging_key, destination_location,
                          multipart_id, status, manifest, error_reason, lease_generation,
                          created_at, expires_at, updated_at, registered_snapshot_id;
                """,
                (computed_sha256, destination_location, upload_id, tenant_id),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("Session not found or tenant mismatch")
            return cls._row_to_dict(row)

    @classmethod
    def update_status(
        cls,
        conn: psycopg.Connection,
        *,
        upload_id: UUID,
        tenant_id: UUID,
        status: str,
        error_reason: str | None = None,
        manifest_patch: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with conn.cursor() as cur:
            if manifest_patch:
                cur.execute(
                    """
                    UPDATE dataset_upload_sessions
                    SET status = %s,
                        error_reason = %s,
                        manifest = COALESCE(manifest, '{}'::jsonb) || %s::jsonb,
                        updated_at = now()
                    WHERE upload_id = %s AND tenant_id = %s
                    RETURNING upload_id, tenant_id, asset_id, asset_name, client_request_id,
                              format, original_filename, size_bytes, staging_key, destination_location,
                              multipart_id, status, manifest, error_reason, lease_generation,
                              created_at, expires_at, updated_at, registered_snapshot_id;
                    """,
                    (status, error_reason, Jsonb(manifest_patch), upload_id, tenant_id),
                )
            else:
                cur.execute(
                    """
                    UPDATE dataset_upload_sessions
                    SET status = %s,
                        error_reason = %s,
                        updated_at = now()
                    WHERE upload_id = %s AND tenant_id = %s
                    RETURNING upload_id, tenant_id, asset_id, asset_name, client_request_id,
                              format, original_filename, size_bytes, staging_key, destination_location,
                              multipart_id, status, manifest, error_reason, lease_generation,
                              created_at, expires_at, updated_at, registered_snapshot_id;
                    """,
                    (status, error_reason, upload_id, tenant_id),
                )
            row = cur.fetchone()
            if not row:
                raise ValueError("Session not found or tenant mismatch")
            return cls._row_to_dict(row)

    @classmethod
    def _row_to_dict(cls, row: Any) -> dict[str, Any]:
        manifest = row[12] or {}
        return {
            "upload_id": row[0],
            "tenant_id": row[1],
            "asset_id": row[2],
            "asset_name": row[3],
            "client_request_id": row[4],
            "format": row[5],
            "original_filename": row[6],
            "size_bytes": row[7],
            "staging_key": row[8],
            "destination_location": row[9],
            "multipart_id": row[10],
            "status": row[11],
            "manifest": manifest,
            "error_reason": row[13],
            "lease_generation": row[14],
            "created_at": row[15],
            "expires_at": row[16],
            "updated_at": row[17],
            "registered_snapshot_id": row[18],
        }
