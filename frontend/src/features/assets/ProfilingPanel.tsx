import { Shield, ShieldAlert, ShieldCheck } from "lucide-react";
import type {
  ColumnClassification,
  ColumnProfile,
  DatasetPreview as PreviewData,
  DatasetProfile,
  SchemaColumn,
  SnapshotResponse,
} from "../../api/types";
import { CopyId } from "../../components/CopyId";
import { ProblemAlert } from "../../components/ProblemAlert";
import { formatCount, formatRatio, formatTimestamp } from "../../lib/format";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { DatasetPreview } from "./DatasetPreview";

interface ProfilingPanelProps {
  snapshot: SnapshotResponse;
  classifications?: ColumnClassification[];
  previewData?: PreviewData | null;
  previewLoading?: boolean;
  previewError?: unknown;
}

export function ProfilingPanel({
  snapshot,
  classifications,
  previewData,
  previewLoading,
  previewError,
}: ProfilingPanelProps) {
  const { t, lang } = useI18n();

  // Extract source descriptor metadata
  const desc = snapshot.source_descriptor || {};
  const canonical = (desc.canonical as Record<string, unknown> | undefined) || {};
  const rawSize = typeof desc.size_bytes === "number" ? desc.size_bytes : null;
  const canonicalSize = typeof canonical.size_bytes === "number" ? canonical.size_bytes : null;
  const rawSha = typeof desc.content_sha256 === "string" ? desc.content_sha256 : null;
  const normVersion =
    desc.normalization_version ?? canonical.normalization_version ?? "—";
  const capturedAt = formatTimestamp(snapshot.captured_at, lang);

  // Extract schema and profile
  const rawSchemaCols = (snapshot.schema_definition?.columns ?? []) as (
    | SchemaColumn
    | string
  )[];
  const schemaCols: SchemaColumn[] = rawSchemaCols.map((col) =>
    typeof col === "string" ? { name: col } : col
  );

  const profile = (previewData?.profile as DatasetProfile | undefined) || undefined;
  const sampleRows = profile?.sample_rows ?? 0;
  const isSample = profile?.is_sample ?? false;
  const colProfilesMap = new Map<string, ColumnProfile>();
  for (const cp of profile?.columns ?? []) {
    colProfilesMap.set(cp.name, cp);
  }

  // Map of column classifications for quick lookup
  const classMap = new Map<string, ColumnClassification>();
  for (const c of classifications ?? []) {
    classMap.set(c.column_name, c);
  }

  // Combined column list (schema order, supplemented by profile if schema empty)
  const columnNames = schemaCols.length > 0
    ? schemaCols.map((c) => c.name)
    : Array.from(colProfilesMap.keys());

  return (
    <div className="space-y-6" data-testid="profiling-panel">
      {/* 1. Metadata Summary Card */}
      <section className="card space-y-4">
        <h2 className="text-base font-semibold">{t("privacy.profiling.title")}</h2>
        <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 text-sm">
          <CopyId label="Snapshot ID" value={snapshot.snapshot_id} />
          <CopyId label="Asset ID" value={snapshot.asset_id} />
          <div>
            <dt className="text-xs text-fg-muted">{t("privacy.profiling.format")}</dt>
            <dd className="font-medium">
              {String(desc.format ?? snapshot.source_kind ?? "—")}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-fg-muted">{t("privacy.profiling.captured_at")}</dt>
            <dd title={capturedAt.utc}>{capturedAt.local}</dd>
          </div>
          <div>
            <dt className="text-xs text-fg-muted">{t("privacy.profiling.dimensions")}</dt>
            <dd className="font-medium">
              {formatCount(snapshot.total_rows, lang)} × {formatCount(snapshot.total_columns, lang)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-fg-muted">{t("privacy.profiling.raw_size")}</dt>
            <dd className="mono">
              {rawSize != null ? `${formatCount(rawSize, lang)} B` : "—"}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-fg-muted">{t("privacy.profiling.canonical_size")}</dt>
            <dd className="mono">
              {canonicalSize != null ? `${formatCount(canonicalSize, lang)} B` : "—"}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-fg-muted">
              {t("privacy.profiling.normalization_version")}
            </dt>
            <dd className="mono">{String(normVersion)}</dd>
          </div>
        </dl>

        {rawSha && (
          <div className="rounded border border-border p-3 bg-surface-muted text-xs space-y-1">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">{t("preview.hash")}</span>
              <span className="text-fg-muted text-[11px]">
                {t("privacy.profiling.checksum_note")}
              </span>
            </div>
            <p className="mono break-all">{rawSha}</p>
          </div>
        )}
      </section>

      {/* 2. Column Profiling Table */}
      <section className="card space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
          <div>
            <h3 className="font-semibold text-base">{t("privacy.class.col.name")} Profiling</h3>
            {profile && sampleRows > 0 ? (
              <p className="text-xs text-fg-muted">
                {t("privacy.profiling.sample_note", {
                  sample: formatCount(sampleRows, lang),
                  total: formatCount(snapshot.total_rows, lang),
                })}
                {isSample && " · sample only"}
              </p>
            ) : null}
          </div>
        </div>

        {previewLoading ? (
          <p className="text-sm text-fg-muted" aria-busy="true">
            {t("common.loading")}
          </p>
        ) : previewError ? (
          <ProblemAlert error={previewError} />
        ) : columnNames.length === 0 || !profile ? (
          <p className="text-sm text-fg-muted italic">
            {t("privacy.profiling.no_profile")}
          </p>
        ) : (
          <div className="overflow-x-auto rounded border border-border">
            <table className="w-full text-left text-sm">
              <thead className="bg-surface-muted text-xs text-fg-muted">
                <tr>
                  <th className="p-2.5">{t("privacy.profiling.col.name")}</th>
                  <th className="p-2.5">{t("privacy.profiling.col.type")}</th>
                  <th className="p-2.5">{t("privacy.profiling.col.logical_types")}</th>
                  <th className="p-2.5">{t("privacy.profiling.col.encoding")}</th>
                  <th className="p-2.5 text-right">{t("privacy.profiling.col.null_ratio")}</th>
                  <th className="p-2.5 text-right">{t("privacy.profiling.col.distinct")}</th>
                  <th className="p-2.5 text-right">{t("privacy.profiling.col.parse_success")}</th>
                  <th className="p-2.5">{t("privacy.profiling.col.timestamp_format")}</th>
                  <th className="p-2.5">{t("privacy.profiling.col.range")}</th>
                  <th className="p-2.5">{t("privacy.profiling.col.status")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {columnNames.map((name) => {
                  const schemaCol = schemaCols.find((c) => c.name === name);
                  const cp = colProfilesMap.get(name);
                  const cls = classMap.get(name);
                  const isProtected = cls?.protected ?? false;

                  const nullRatio =
                    cp && sampleRows > 0
                      ? `${cp.null_count} / ${sampleRows} (${formatRatio(cp.null_count / sampleRows)})`
                      : "—";

                  const parseSuccess =
                    cp && cp.non_null_count > 0
                      ? `${cp.parse_success_count} / ${cp.non_null_count} (${formatRatio(
                          cp.parse_success_count / cp.non_null_count
                        )})`
                      : cp
                      ? `${cp.parse_success_count} / 0`
                      : "—";

                  return (
                    <tr key={name} className="hover:bg-surface-muted/50">
                      <td className="p-2.5 font-medium">{name}</td>
                      <td className="p-2.5 mono text-xs">
                        {cp?.type_hint ?? schemaCol?.type ?? "STRING"}
                      </td>
                      <td className="p-2.5 text-xs text-fg-muted">
                        {schemaCol?.logical_types?.length
                          ? schemaCol.logical_types.join(", ")
                          : "—"}
                      </td>
                      <td className="p-2.5 text-xs text-fg-muted">
                        {schemaCol?.structural_encoding ?? "—"}
                      </td>
                      <td className="p-2.5 text-right mono text-xs">{nullRatio}</td>
                      <td className="p-2.5 text-right mono text-xs">
                        {cp ? formatCount(cp.distinct_count, lang) : "—"}
                      </td>
                      <td className="p-2.5 text-right mono text-xs">{parseSuccess}</td>
                      <td className="p-2.5 text-xs text-fg-muted">
                        {cp?.timestamp_format ?? "—"}
                      </td>
                      <td className="p-2.5 text-xs">
                        {isProtected ? (
                          <span className="inline-flex items-center gap-1 text-xs text-amber-700 dark:text-amber-400">
                            <ShieldAlert className="size-3.5 inline" />
                            {t("privacy.profiling.protected_hidden")}
                          </span>
                        ) : cp?.min != null || cp?.max != null ? (
                          <span className="mono">
                            {String(cp.min ?? "—")} … {String(cp.max ?? "—")}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="p-2.5">
                        <div className="flex flex-wrap items-center gap-1.5">
                          {isProtected ? (
                            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-medium bg-red-100 text-red-800 dark:bg-red-950/60 dark:text-red-300">
                              <Shield className="size-3" />
                              {t("privacy.class.protected_badge")}
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-medium bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                              <ShieldCheck className="size-3 text-zinc-400" />
                              {t("privacy.class.unprotected_badge")}
                            </span>
                          )}
                          {cls?.declared_category ? (
                            <span className="inline-flex px-1.5 py-0.5 rounded text-[11px] font-medium bg-blue-100 text-blue-800 dark:bg-blue-950/60 dark:text-blue-300">
                              {t(`privacy.cat.${cls.declared_category}` as TranslationKey)}
                            </span>
                          ) : (
                            <span className="inline-flex px-1.5 py-0.5 rounded text-[11px] text-fg-muted bg-surface-muted">
                              {t("privacy.cat.UNDECLARED")}
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* 3. Redacted Dataset Preview */}
      {previewData && <DatasetPreview data={previewData} />}
    </div>
  );
}
