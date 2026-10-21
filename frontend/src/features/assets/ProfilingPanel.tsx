import { ChevronDown, ChevronRight, Shield, ShieldAlert, ShieldCheck } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type KeyboardEvent } from "react";
import type {
  ColumnClassification,
  DatasetPreview as PreviewData,
  ProfileMode,
  SchemaColumn,
  SnapshotResponse,
} from "../../api/types";
import { session } from "../../api/client";
import { getSnapshotProfile, submitFullProfile } from "../../api/endpoints";
import { CopyId } from "../../components/CopyId";
import { ProblemAlert } from "../../components/ProblemAlert";
import { EMPTY, formatCount, formatRatio, formatTimestamp } from "../../lib/format";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { DatasetPreview } from "./DatasetPreview";

interface ProfilingPanelProps {
  snapshot: SnapshotResponse;
  classifications?: ColumnClassification[];
  previewData?: PreviewData | null;
  previewLoading?: boolean;
  previewError?: unknown;
}

const SUBVIEWS = ["sample", "columns", "info"] as const;
type Subview = (typeof SUBVIEWS)[number];
const SUBVIEW_LABEL: Record<Subview, TranslationKey> = {
  sample: "privacy.profiling.subview.sample",
  columns: "privacy.profiling.subview.columns",
  info: "privacy.profiling.subview.info",
};

interface ViewColumn {
  name: string;
  type_hint?: string;
  non_null_count: number | null;
  distinct_count: number | null;
  parse_success_count: number | null;
  sample_rows?: number;
  timestamp_format?: string;
  min?: string | number;
  max?: string | number;
}
interface ViewProfile { sample_rows: number; columns: ViewColumn[]; }

const PROFILE_MODES: readonly ProfileMode[] = ["SAMPLE", "FULL"];
const FULL_POLL_MS = 3000;

/** Rows column measured over: its own denominator when producer emits one, else profile's. */
function sampleDenominator(cp: ViewColumn, profile: ViewProfile): number | null {
  const n = cp.sample_rows ?? profile.sample_rows;
  return typeof n === "number" && n > 0 ? n : null;
}

/** Ratio or null when a side is unknown or the denominator is zero (unavailable, never 0% or 100%). */
function ratio(numerator: number | null, denominator: number | null): number | null {
  return numerator == null || !denominator ? null : numerator / denominator;
}

/** Weighted fill across all columns, only when every column has a profile with denominator. */
function weightedFill(columnNames: string[], profileByName: Map<string, ViewColumn>, profile?: ViewProfile) {
  if (!profile || columnNames.length === 0) return null;
  let filled = 0;
  let cells = 0;
  for (const name of columnNames) {
    const cp = profileByName.get(name);
    const n = cp ? sampleDenominator(cp, profile) : null;
    if (!cp || n == null || cp.non_null_count == null) return null;
    filled += cp.non_null_count;
    cells += n;
  }
  return ratio(filled, cells);
}

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card min-w-0">
      <dt className="text-xs text-fg-muted">{label}</dt>
      <dd className="text-2xl font-semibold">{value}</dd>
      {hint && <p className="text-xs text-fg-muted">{hint}</p>}
    </div>
  );
}

export function ProfilingPanel({
  snapshot,
  classifications,
  previewData,
  previewLoading,
  previewError,
}: ProfilingPanelProps) {
  const { t, lang } = useI18n();
  const baseId = useId();
  const [subview, setSubview] = useState<Subview>("sample");
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());

  const desc = snapshot.source_descriptor || {};
  const canonical = (desc.canonical as Record<string, unknown> | undefined) || {};
  const rawSize = typeof desc.size_bytes === "number" ? desc.size_bytes : null;
  const canonicalSize = typeof canonical.size_bytes === "number" ? canonical.size_bytes : null;
  const rawSha = typeof desc.content_sha256 === "string" ? desc.content_sha256 : null;
  const normVersion = desc.normalization_version ?? canonical.normalization_version ?? EMPTY;
  const storageLabel: TranslationKey | null = desc.storage_mode === "OWNED_RAW"
    ? "privacy.profiling.storage_owned"
    : desc.storage_mode === "EXTERNAL_VERSION"
      ? "privacy.profiling.storage_reference"
      : desc.canonical ? "privacy.profiling.storage_legacy" : null;
  const capturedAt = formatTimestamp(snapshot.captured_at, lang);

  const rawSchemaCols = (snapshot.schema_definition?.columns ?? []) as (SchemaColumn | string)[];
  const schemaCols: SchemaColumn[] = rawSchemaCols.map((col) =>
    typeof col === "string" ? { name: col } : col
  );

  const [mode, setMode] = useState<ProfileMode>("SAMPLE");
  const queryClient = useQueryClient();
  const fullKey = ["snapshot-profile", session.email(), snapshot.snapshot_id, "FULL"];
  const full = useQuery({
    queryKey: fullKey,
    queryFn: ({ signal }) => getSnapshotProfile(snapshot.snapshot_id, "FULL", signal),
    enabled: mode === "FULL",
    refetchInterval: (query) =>
      query.state.data?.state === "QUEUED" || query.state.data?.state === "RUNNING" ? FULL_POLL_MS : false,
  });
  const submitFull = useMutation({
    mutationFn: () => submitFullProfile(snapshot.snapshot_id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: fullKey }),
  });
  const fullData = mode === "FULL" ? full.data : undefined;
  const fullResult = fullData?.result;

  const rawProfile = previewData?.profile as Partial<ViewProfile> | undefined;
  const sampleProfile = Array.isArray(rawProfile?.columns) ? (rawProfile as ViewProfile) : undefined;
  const profile: ViewProfile | undefined = fullResult
    ? {
        sample_rows: fullResult.scanned_rows ?? 0,
        columns: fullResult.columns.map((c) => ({ ...c, type_hint: c.technical_type ?? c.type_hint })),
      }
    : mode === "FULL"
      ? undefined
      : sampleProfile;
  const profileByName = new Map<string, ViewColumn>();
  for (const cp of profile?.columns ?? []) profileByName.set(cp.name, cp);
  const classMap = new Map<string, ColumnClassification>();
  for (const c of classifications ?? []) classMap.set(c.column_name, c);

  const columnNames =
    schemaCols.length > 0 ? schemaCols.map((c) => c.name) : Array.from(profileByName.keys());
  const fill = weightedFill(columnNames, profileByName, profile);
  const sampleRows = sampleProfile?.sample_rows ?? 0;
  const scopeText =
    mode === "FULL"
      ? t("profile.scope.full", { rows: formatCount(fullResult?.total_rows ?? snapshot.total_rows, lang) })
      : sampleRows > 0
        ? t("profile.scope.sample", { rows: formatCount(sampleRows, lang) })
        : undefined;
  const scopeHint = profile && profile.sample_rows > 0 ? scopeText : undefined;
  const generatedAt = formatTimestamp(fullResult?.generated_at, lang);
  const finishedAt = formatTimestamp(fullData?.finished_at, lang);

  const toggle = (name: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (!next.delete(name)) next.add(name);
      return next;
    });

  const onTabKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = SUBVIEWS[(SUBVIEWS.indexOf(subview) + step + SUBVIEWS.length) % SUBVIEWS.length];
    setSubview(next);
    document.getElementById(`${baseId}-tab-${next}`)?.focus();
  };

  const previewState = previewLoading ? (
    <p className="text-sm text-fg-muted" aria-busy="true">
      {t("common.loading")}
    </p>
  ) : previewError ? (
    <ProblemAlert error={previewError} />
  ) : null;

  return (
    <div className="space-y-6" data-testid="profiling-panel">
      <dl className="grid gap-3 sm:grid-cols-3" aria-label={t("privacy.profiling.title")}>
        <Kpi label={t("privacy.profiling.kpi.rows")} value={formatCount(snapshot.total_rows, lang)} />
        <Kpi label={t("privacy.profiling.kpi.fields")} value={formatCount(snapshot.total_columns, lang)} />
        <Kpi
          label={t("privacy.profiling.kpi.fill")}
          value={fill == null ? EMPTY : formatRatio(fill)}
          hint={fill == null ? t("privacy.profiling.unavailable") : scopeHint}
        />
      </dl>
      <section className="card space-y-3" aria-label={t("profile.mode.label")}>
        <div role="radiogroup" aria-label={t("profile.mode.label")} className="flex flex-wrap gap-2">
          {PROFILE_MODES.map((m) => (
            <label
              key={m}
              className={`inline-flex min-h-11 cursor-pointer items-center gap-2 border px-3 focus-within:ring-2 focus-within:ring-action ${
                mode === m ? "border-action font-semibold text-action" : "border-border text-fg-muted"
              }`}
            >
              <input type="radio" name={`${baseId}-mode`} value={m} checked={mode === m} onChange={() => setMode(m)} />
              {t(`profile.mode.${m}` as TranslationKey)}
            </label>
          ))}
        </div>
        {scopeText && <p className="text-xs text-fg-muted">{scopeText}</p>}
        {mode === "FULL" && (
          <div className="min-h-24 space-y-3" aria-busy={full.isPending}>
            {full.isPending ? (
              <p className="text-sm text-fg-muted">{t("common.loading")}</p>
            ) : full.error ? (
              <ProblemAlert error={full.error} />
            ) : (
              fullData && (
                <dl className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
                  <div>
                    <dt className="text-xs text-fg-muted">{t("profile.state")}</dt>
                    <dd className="flex flex-wrap items-center gap-1.5 font-medium">
                      {t(`profile.state.${fullData.state ?? "NONE"}` as TranslationKey)}
                      {fullData.state &&
                        (fullData.stale ? (
                          <span className="bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800 dark:bg-amber-950/60 dark:text-amber-300">
                            {t("profile.stale")}
                          </span>
                        ) : fullData.current ? (
                          <span className="bg-green-100 px-1.5 py-0.5 text-xs text-green-800 dark:bg-green-950/60 dark:text-green-300">
                            {t("profile.current")}
                          </span>
                        ) : null)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-fg-muted">{t("profile.rows")}</dt>
                    <dd className="mono">
                      {fullResult && fullResult.scanned_rows != null && fullResult.total_rows != null
                        ? `${formatCount(fullResult.scanned_rows, lang)} / ${formatCount(fullResult.total_rows, lang)}`
                        : EMPTY}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-fg-muted">{t("profile.generated_at")}</dt>
                    <dd title={generatedAt.utc}>{generatedAt.local}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-fg-muted">{t("profile.finished_at")}</dt>
                    <dd title={finishedAt.utc}>{finishedAt.local}</dd>
                  </div>
                  {fullData.error_code && (
                    <div>
                      <dt className="text-xs text-fg-muted">{t("profile.error_code")}</dt>
                      <dd className="mono text-fail">{fullData.error_code}</dd>
                    </div>
                  )}
                </dl>
              )
            )}
            {(fullData?.state === null || fullData?.state === "FAILED") && (
              <button
                type="button"
                className="btn-primary min-h-11"
                disabled={submitFull.isPending}
                onClick={() => submitFull.mutate()}
              >
                {submitFull.isPending ? t("profile.submitting") : t("profile.run_full")}
              </button>
            )}
            <ProblemAlert error={submitFull.error} />
          </div>
        )}
      </section>
      <div role="tablist" aria-label={t("privacy.profiling.title")} className="flex gap-2 border-b border-border text-sm">
        {SUBVIEWS.map((id) => (
          <button
            key={id}
            type="button"
            role="tab"
            id={`${baseId}-tab-${id}`}
            aria-selected={subview === id}
            aria-controls={`${baseId}-panel-${id}`}
            tabIndex={subview === id ? 0 : -1}
            onClick={() => setSubview(id)}
            onKeyDown={onTabKey}
            className={`min-h-11 px-3 border-b-2 cursor-pointer ${
              subview === id
                ? "border-action text-action font-semibold"
                : "border-transparent text-fg-muted hover:text-fg"
            }`}
          >
            {t(SUBVIEW_LABEL[id])}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`${baseId}-panel-${subview}`} aria-labelledby={`${baseId}-tab-${subview}`}>
        {subview === "sample" &&
          (previewState ??
            (previewData ? (
              <DatasetPreview data={previewData} hideSourceInfo />
            ) : (
              <p className="text-sm text-fg-muted italic">{t("privacy.profiling.no_profile")}</p>
            )))}

        {subview === "columns" && (
          <section className="space-y-3">
            {scopeHint && <p className="text-xs text-fg-muted">{scopeHint}</p>}
            {previewState ??
              (columnNames.length === 0 || !profile ? (
                <p className="text-sm text-fg-muted italic">{t("privacy.profiling.no_profile")}</p>
              ) : (
                <div className="overflow-x-auto rounded border border-border">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-surface-muted text-xs text-fg-muted">
                      <tr>
                        <th className="p-2.5">{t("privacy.profiling.col.name")}</th>
                        <th className="p-2.5">{t("privacy.profiling.col.type")}</th>
                        <th className="p-2.5 text-right">{t("privacy.profiling.col.fill")}</th>
                        <th className="p-2.5 text-right">{t("privacy.profiling.col.distinct")}</th>
                        <th className="p-2.5 text-right">{t("privacy.profiling.col.parse_success")}</th>
                        <th className="p-2.5">{t("privacy.profiling.col.status")}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {columnNames.map((name) => {
                        const schemaCol = schemaCols.find((c) => c.name === name);
                        const cp = profileByName.get(name);
                        const cls = classMap.get(name);
                        // Fail closed: until classifications are known, no column statistics beyond counts.
                        const statsHidden = classifications === undefined || (cls?.protected ?? false);
                        const isProtected = cls?.protected ?? false;
                        const n = cp && profile ? sampleDenominator(cp, profile) : null;
                        const fillRatio = cp ? ratio(cp.non_null_count, n) : null;
                        const parseRatio = cp ? ratio(cp.parse_success_count, cp.non_null_count || null) : null;
                        const isOpen = expanded.has(name);
                        const detailsId = `${baseId}-details-${name}`;
                        return [
                          <tr key={name} className="hover:bg-surface-muted/50">
                            <td className="p-2.5 font-medium">
                              <button
                                type="button"
                                className="inline-flex items-center gap-1 cursor-pointer min-h-11"
                                aria-expanded={isOpen}
                                aria-controls={detailsId}
                                onClick={() => toggle(name)}
                              >
                                {isOpen ? (
                                  <ChevronDown aria-hidden className="size-4" />
                                ) : (
                                  <ChevronRight aria-hidden className="size-4" />
                                )}
                                {name}
                              </button>
                            </td>
                            <td className="p-2.5 mono text-xs">{cp?.type_hint ?? schemaCol?.type ?? "STRING"}</td>
                            <td className="p-2.5 text-right mono text-xs">
                              {fillRatio == null || n == null || cp?.non_null_count == null
                                ? EMPTY
                                : `${formatRatio(fillRatio)} (${formatCount(cp.non_null_count, lang)} / ${formatCount(n, lang)})`}
                            </td>
                            <td className="p-2.5 text-right mono text-xs">
                              {!cp ? EMPTY : statsHidden ? t("privacy.profiling.protected_hidden") : cp.distinct_count == null ? t("profile.unknown") : formatCount(cp.distinct_count, lang)}
                            </td>
                            <td className="p-2.5 text-right mono text-xs">
                              {parseRatio == null || cp?.parse_success_count == null || cp.non_null_count == null
                                ? EMPTY
                                : `${formatRatio(parseRatio)} (${formatCount(cp.parse_success_count, lang)} / ${formatCount(cp.non_null_count, lang)})`}
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
                          </tr>,
                          isOpen && (
                            <tr key={`${name}-details`} id={detailsId} className="bg-surface-muted/40">
                              <td colSpan={6} className="p-2.5">
                                <dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 text-xs">
                                  <div>
                                    <dt className="text-fg-muted">{t("privacy.profiling.col.logical_types")}</dt>
                                    <dd>{schemaCol?.logical_types?.length ? schemaCol.logical_types.join(", ") : EMPTY}</dd>
                                  </div>
                                  <div>
                                    <dt className="text-fg-muted">{t("privacy.profiling.col.encoding")}</dt>
                                    <dd>{schemaCol?.structural_encoding ?? EMPTY}</dd>
                                  </div>
                                  <div>
                                    <dt className="text-fg-muted">{t("privacy.profiling.col.timestamp_format")}</dt>
                                    <dd>{statsHidden ? EMPTY : (cp?.timestamp_format ?? EMPTY)}</dd>
                                  </div>
                                  <div>
                                    <dt className="text-fg-muted">{t("privacy.profiling.col.range")}</dt>
                                    <dd>
                                      {statsHidden ? (
                                        <span className="inline-flex items-center gap-1 text-amber-700 dark:text-amber-400">
                                          <ShieldAlert aria-hidden className="size-3.5" />
                                          {t(
                                            isProtected
                                              ? "privacy.profiling.protected_hidden"
                                              : "privacy.profiling.scan_unverified_hidden"
                                          )}
                                        </span>
                                      ) : cp?.min != null || cp?.max != null ? (
                                        <span className="mono">
                                          {String(cp.min ?? EMPTY)} … {String(cp.max ?? EMPTY)}
                                        </span>
                                      ) : (
                                        EMPTY
                                      )}
                                    </dd>
                                  </div>
                                </dl>
                              </td>
                            </tr>
                          ),
                        ];
                      })}
                    </tbody>
                  </table>
                </div>
              ))}
          </section>
        )}

        {subview === "info" && (
          <section className="card space-y-4">
            <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 text-sm">
              <CopyId label="Snapshot ID" value={snapshot.snapshot_id} />
              <CopyId label="Asset ID" value={snapshot.asset_id} />
              <div>
                <dt className="text-xs text-fg-muted">{t("privacy.profiling.format")}</dt>
                <dd className="font-medium">{String(desc.format ?? snapshot.source_kind ?? EMPTY)}</dd>
              </div>
              <div>
                <dt className="text-xs text-fg-muted">{t("privacy.profiling.kpi.rows")}</dt>
                <dd className="font-medium">{formatCount(snapshot.total_rows, lang)}</dd>
              </div>
              <div>
                <dt className="text-xs text-fg-muted">{t("privacy.profiling.kpi.fields")}</dt>
                <dd className="font-medium">{formatCount(snapshot.total_columns, lang)}</dd>
              </div>
              <div>
                <dt className="text-xs text-fg-muted">{t("privacy.profiling.captured_at")}</dt>
                <dd title={capturedAt.utc}>{capturedAt.local}</dd>
              </div>
              <div>
                <dt className="text-xs text-fg-muted">{t("privacy.profiling.raw_size")}</dt>
                <dd className="mono">{rawSize != null ? `${formatCount(rawSize, lang)} B` : EMPTY}</dd>
              </div>
              {canonicalSize != null && (
                <div>
                  <dt className="text-xs text-fg-muted">{t("privacy.profiling.canonical_size")}</dt>
                  <dd className="mono">{formatCount(canonicalSize, lang)} B</dd>
                </div>
              )}
              {storageLabel && (
                <div>
                  <dt className="text-xs text-fg-muted">{t("privacy.profiling.storage_mode")}</dt>
                  <dd>{t(storageLabel)}</dd>
                </div>
              )}
              {typeof desc.version_id === "string" && (
                <CopyId label={t("privacy.profiling.object_version")} value={desc.version_id} />
              )}
              <div>
                <dt className="text-xs text-fg-muted">{t("privacy.profiling.normalization_version")}</dt>
                <dd className="mono">{String(normVersion)}</dd>
              </div>
            </dl>
            {rawSha && (
              <div className="rounded border border-border p-3 bg-surface-muted text-xs space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{t("preview.hash")}</span>
                  <span className="text-fg-muted text-[11px]">{t("privacy.profiling.checksum_note")}</span>
                </div>
                <p className="mono break-all">{rawSha}</p>
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  );
}
