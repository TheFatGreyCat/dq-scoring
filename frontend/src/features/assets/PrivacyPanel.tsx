import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  ChevronDown,
  Download,
  Filter,
  History,
  Info,
  Shield,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { session } from "../../api/client";
import {
  downloadMaskedExport,
  getColumnClassifications,
  getProtectionPolicy,
  getSensitiveFindings,
  updateColumnClassifications,
  updateFindingStatus,
  updateProtectionPolicy,
} from "../../api/endpoints";
import type {
  ClassificationChange,
  ColumnClassification,
  ColumnClassificationsResponse,
  FindingCategory,
  FindingResponse,
  FindingStatus,
  PrivacyCategory,
  UUID,
} from "../../api/types";
import { ProblemAlert } from "../../components/ProblemAlert";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { POLICY_WRITE_ROLES, useIdentity } from "../auth/useIdentity";

export function useColumnClassifications(snapshotId: UUID) {
  return useQuery({
    queryKey: ["column-classifications", session.email(), snapshotId],
    queryFn: ({ signal }) => getColumnClassifications(snapshotId, signal),
  });
}

const ALL_POLICY_CATEGORIES: { id: FindingCategory; labelKey: TranslationKey }[] = [
  { id: "BASIC_PERSONAL_DATA", labelKey: "privacy.cat.BASIC_PERSONAL_DATA" },
  { id: "SENSITIVE_PERSONAL_DATA", labelKey: "privacy.cat.SENSITIVE_PERSONAL_DATA" },
  { id: "CONFIDENTIAL_BUSINESS_DATA", labelKey: "privacy.cat.CONFIDENTIAL_BUSINESS_DATA" },
];

const CLASSIFICATION_OPTIONS: { id: PrivacyCategory | "UNDECLARED"; labelKey: TranslationKey }[] = [
  { id: "UNDECLARED", labelKey: "privacy.cat.UNDECLARED" },
  { id: "STANDARD_DATA", labelKey: "privacy.cat.STANDARD_DATA" },
  { id: "BASIC_PERSONAL_DATA", labelKey: "privacy.cat.BASIC_PERSONAL_DATA" },
  { id: "SENSITIVE_PERSONAL_DATA", labelKey: "privacy.cat.SENSITIVE_PERSONAL_DATA" },
  { id: "CONFIDENTIAL_BUSINESS_DATA", labelKey: "privacy.cat.CONFIDENTIAL_BUSINESS_DATA" },
];

function FindingStatusBadge({ status }: { status: FindingStatus }) {
  const styles: Record<FindingStatus, string> = {
    DETECTED: "bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300",
    CONFIRMED: "bg-red-100 text-red-800 dark:bg-red-950/50 dark:text-red-300",
    DISMISSED: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${styles[status]}`}>
      {status}
    </span>
  );
}

interface PrivacyPanelProps {
  assetId: UUID;
  snapshotId: UUID;
  onDirtyChange?: (isDirty: boolean) => void;
}

type FilterType = "all" | "sensitive" | "undeclared" | "conflict";

export function PrivacyPanel({ assetId, snapshotId, onDirtyChange }: PrivacyPanelProps) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const identity = useIdentity();
  const role = identity.data?.role;
  const canWrite = !!role && !!POLICY_WRITE_ROLES[role];

  // 1. Column Classifications Query
  const classQuery = useColumnClassifications(snapshotId);
  const classData: ColumnClassificationsResponse | undefined = classQuery.data;

  // 2. Sensitive Findings Query (paginated)
  const [findingPage, setFindingPage] = useState(1);
  const findingsQuery = useQuery({
    queryKey: ["sensitive-findings", session.email(), snapshotId, findingPage],
    queryFn: ({ signal }) => getSensitiveFindings(snapshotId, { page: findingPage, page_size: 25 }, signal),
  });

  // 3. Asset Protection Policy Query
  const policyQuery = useQuery({
    queryKey: ["protection-policy", session.email(), assetId],
    queryFn: ({ signal }) => getProtectionPolicy(assetId, signal),
  });

  // Classification Draft State: maps column_name -> draft category
  const [draftChanges, setDraftChanges] = useState<Record<string, PrivacyCategory | null>>({});
  const [selectedCols, setSelectedCols] = useState<Set<string>>(new Set());
  const [bulkCategory, setBulkCategory] = useState<string>("");
  const [classReason, setClassReason] = useState("");
  const [classFilter, setClassFilter] = useState<FilterType>("all");
  const [searchCol, setSearchCol] = useState("");

  // Notify parent of dirty changes
  const isDirty = useMemo(() => Object.keys(draftChanges).length > 0, [draftChanges]);
  useEffect(() => {
    onDirtyChange?.(isDirty);
    return () => onDirtyChange?.(false);
  }, [isDirty, onDirtyChange]);

  // Finding review reason state
  const [reviewReason, setReviewReason] = useState("");

  // Policy form state
  const policy = policyQuery.data;
  const [selectedCats, setSelectedCats] = useState<FindingCategory[] | null>(null);
  const categories = selectedCats ?? policy?.categories ?? [];

  // Export State
  const [isDownloading, setIsDownloading] = useState(false);
  const [exportError, setExportError] = useState<unknown | null>(null);

  // Mutations
  const findingMutation = useMutation({
    mutationFn: ({
      findingId,
      expectedStatus,
      newStatus,
    }: {
      findingId: UUID;
      expectedStatus: string;
      newStatus: string;
    }) => updateFindingStatus(findingId, expectedStatus, newStatus, reviewReason.trim()),
    onSuccess: () => {
      setReviewReason("");
      void queryClient.invalidateQueries({ queryKey: ["sensitive-findings"] });
      void queryClient.invalidateQueries({ queryKey: ["column-classifications"] });
      void queryClient.invalidateQueries({ queryKey: ["protection-policy"] });
      void queryClient.invalidateQueries({ queryKey: ["preview"] });
    },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: ["sensitive-findings"] });
    },
  });

  const saveClassificationsMutation = useMutation({
    mutationFn: async () => {
      if (!classData) return;
      const changes: ClassificationChange[] = Object.entries(draftChanges).map(
        ([colName, cat]) => ({
          column_name: colName,
          category: cat,
          reason: classReason.trim(),
        })
      );
      return updateColumnClassifications(assetId, {
        snapshot_id: snapshotId,
        expected_version: classData.version,
        changes,
      });
    },
    onSuccess: (updated) => {
      setDraftChanges({});
      setClassReason("");
      setSelectedCols(new Set());
      if (updated) {
        queryClient.setQueryData(["column-classifications", session.email(), snapshotId], updated);
      }
      void queryClient.invalidateQueries({ queryKey: ["sensitive-findings"] });
      void queryClient.invalidateQueries({ queryKey: ["protection-policy"] });
      void queryClient.invalidateQueries({ queryKey: ["preview"] });
    },
    onError: () => {
      // Preserve draft on conflict / error; refetch server version
      void queryClient.invalidateQueries({ queryKey: ["column-classifications"] });
    },
  });

  const policyMutation = useMutation({
    mutationFn: async () => {
      if (!policy) return;
      return updateProtectionPolicy(assetId, policy.version, categories);
    },
    onSuccess: (updated) => {
      if (updated) setSelectedCats(updated.categories);
      void queryClient.invalidateQueries({ queryKey: ["protection-policy"] });
      void queryClient.invalidateQueries({ queryKey: ["column-classifications"] });
      void queryClient.invalidateQueries({ queryKey: ["preview"] });
    },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: ["protection-policy"] });
    },
  });

  const handleExport = async () => {
    try {
      setIsDownloading(true);
      setExportError(null);
      const blob = await downloadMaskedExport(assetId, snapshotId);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `masked_${snapshotId.slice(0, 8)}.parquet`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err: unknown) {
      setExportError(err);
    } finally {
      setIsDownloading(false);
    }
  };

  // Helper to update one column's draft category
  const handleSetColumnCategory = (col: ColumnClassification, nextValue: string) => {
    const targetCategory = nextValue === "UNDECLARED" ? null : (nextValue as PrivacyCategory);
    setDraftChanges((prev) => {
      const next = { ...prev };
      if (targetCategory === col.declared_category) {
        delete next[col.column_name];
      } else {
        next[col.column_name] = targetCategory;
      }
      return next;
    });
  };

  // Apply bulk category to selected columns
  const handleApplyBulkCategory = () => {
    if (!bulkCategory) return;
    const targetCategory = bulkCategory === "UNDECLARED" ? null : (bulkCategory as PrivacyCategory);
    setDraftChanges((prev) => {
      const next = { ...prev };
      for (const colName of selectedCols) {
        const col = classData?.columns.find((c) => c.column_name === colName);
        if (targetCategory === col?.declared_category) {
          delete next[colName];
        } else {
          next[colName] = targetCategory;
        }
      }
      return next;
    });
    setBulkCategory("");
  };

  // Compute column stats and filtered column list
  const allColumns = classData?.columns ?? [];
  const sensitiveCount = allColumns.filter(
    (c) =>
      c.protected ||
      (c.effective_categories &&
        c.effective_categories.some((cat) => cat !== "STANDARD_DATA"))
  ).length;
  const undeclaredCount = allColumns.filter((c) => c.declared_category == null).length;
  const conflictCount = allColumns.filter((c) => c.conflict).length;

  const filteredColumns = allColumns.filter((col) => {
    if (searchCol && !col.column_name.toLowerCase().includes(searchCol.toLowerCase())) {
      return false;
    }
    if (classFilter === "sensitive") {
      return (
        col.protected ||
        (col.effective_categories &&
          col.effective_categories.some((cat) => cat !== "STANDARD_DATA"))
      );
    }
    if (classFilter === "undeclared") {
      return col.declared_category == null;
    }
    if (classFilter === "conflict") {
      return col.conflict;
    }
    return true;
  });

  // Findings pagination
  const findingsData = findingsQuery.data;
  const findings = findingsData?.findings.items ?? [];
  const totalFindings = findingsData?.findings.total ?? 0;
  const totalFindingPages = Math.ceil(totalFindings / 25) || 1;
  const scanStatus = findingsData?.scan_status ?? classData?.scan_status ?? "UNAVAILABLE";
  const isStale = findingsData?.scan_stale ?? classData?.scan_stale ?? false;

  return (
    <div className="space-y-6" data-testid="privacy-panel">
      {/* 1. Security Statement & Export */}
      <section className="card space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
          <div className="flex items-center gap-2">
            <Shield className="size-5 text-action" />
            <h2 className="text-base font-semibold">{t("privacy.class.title")}</h2>
          </div>
          <button
            type="button"
            className="btn-secondary flex items-center gap-2 text-xs"
            onClick={handleExport}
            disabled={isDownloading}
            data-testid="export-masked-btn"
          >
            <Download className="size-3.5" />
            {isDownloading ? t("privacy.export.exporting") : t("privacy.export.button")}
          </button>
        </div>

        {/* Security Statement */}
        <div className="rounded border border-border bg-surface-muted/60 p-3 space-y-1 text-xs">
          <div className="flex items-center gap-2 text-fg font-medium">
            <Info className="size-3.5 text-action" />
            <span>{t("privacy.security.statement")}</span>
          </div>
          <p className="text-fg-muted pl-5">{t("privacy.security.clarification")}</p>
        </div>

        {/* Scan Status Banner */}
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-fg-muted pt-1">
          <div className="flex items-center gap-2">
            <span>{t("privacy.scan.status_label")}:</span>
            <span
              className={`font-semibold px-2 py-0.5 rounded text-[11px] ${
                scanStatus === "COMPLETE"
                  ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300"
                  : scanStatus === "FAILED"
                  ? "bg-red-100 text-red-800 dark:bg-red-950/60 dark:text-red-300"
                  : "bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300"
              }`}
            >
              {scanStatus}
            </span>
            {isStale && (
              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-medium bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300">
                <AlertTriangle className="size-3" />
                {t("privacy.scan.stale_badge")}
              </span>
            )}
          </div>
          {classData && (
            <span className="mono text-xs">
              {t("privacy.class.version_label", { version: classData.version })}
            </span>
          )}
        </div>

        {isStale && (
          <div className="rounded border border-amber-200 bg-amber-50 p-2.5 text-xs text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300">
            {t("privacy.scan.stale_warning")}
          </div>
        )}

        {exportError ? <ProblemAlert error={exportError} /> : null}
      </section>

      {/* 2. Column Classifications Table */}
      <section className="card space-y-4">
        <ProblemAlert error={classQuery.error} />
        {saveClassificationsMutation.error ? (
          <div className="space-y-2">
            <ProblemAlert error={saveClassificationsMutation.error} />
            <p className="text-xs text-amber-700 dark:text-amber-400">
              {t("privacy.class.stale_conflict")}
            </p>
          </div>
        ) : null}

        {/* Filter Chips & Search */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="text-fg-muted mr-1 flex items-center gap-1">
              <Filter className="size-3" />
            </span>
            {(
              [
                { id: "all", label: t("privacy.class.filter.all", { count: allColumns.length }) },
                { id: "sensitive", label: t("privacy.class.filter.sensitive", { count: sensitiveCount }) },
                { id: "undeclared", label: t("privacy.class.filter.undeclared", { count: undeclaredCount }) },
                { id: "conflict", label: t("privacy.class.filter.conflict", { count: conflictCount }) },
              ] as const
            ).map((filter) => (
              <button
                key={filter.id}
                type="button"
                className={`px-2.5 py-1 rounded text-xs transition-colors ${
                  classFilter === filter.id
                    ? "bg-action text-on-action font-semibold"
                    : "bg-surface-muted text-fg-muted hover:text-fg"
                }`}
                onClick={() => setClassFilter(filter.id)}
              >
                {filter.label}
              </button>
            ))}
          </div>

          <div className="w-full sm:w-64">
            <input
              type="text"
              className="input text-xs"
              placeholder={t("privacy.class.search_placeholder")}
              value={searchCol}
              onChange={(e) => setSearchCol(e.target.value)}
            />
          </div>
        </div>

        {/* Bulk Selection Bar (for editors) */}
        {canWrite && selectedCols.size > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-2 p-2.5 rounded bg-surface-muted border border-border text-xs">
            <span className="font-medium">
              {t("privacy.class.selected_count", { count: selectedCols.size })}
            </span>
            <div className="flex items-center gap-2">
              <select
                className="input text-xs py-1"
                aria-label={t("privacy.class.col.declared")}
                value={bulkCategory}
                onChange={(e) => setBulkCategory(e.target.value)}
              >
                <option value="">{t("privacy.class.bulk_placeholder")}</option>
                {CLASSIFICATION_OPTIONS.map((opt) => (
                  <option key={opt.id} value={opt.id}>
                    {t(opt.labelKey)}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="btn-primary text-xs px-2.5 py-1"
                disabled={!bulkCategory}
                onClick={handleApplyBulkCategory}
              >
                {t("privacy.class.bulk_apply")}
              </button>
              <button
                type="button"
                className="btn-secondary text-xs px-2 py-1"
                onClick={() => setSelectedCols(new Set())}
              >
                {t("common.reset")}
              </button>
            </div>
          </div>
        )}

        {/* Classifications Table */}
        <div className="overflow-x-auto rounded border border-border">
          <table className="w-full text-left text-sm">
            <thead className="bg-surface-muted text-xs text-fg-muted">
              <tr>
                {canWrite && (
                  <th className="p-2.5 w-8">
                    <input
                      type="checkbox"
                      className="rounded accent-action"
                      checked={
                        filteredColumns.length > 0 &&
                        filteredColumns.every((c) => selectedCols.has(c.column_name))
                      }
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSelectedCols(new Set(filteredColumns.map((c) => c.column_name)));
                        } else {
                          setSelectedCols(new Set());
                        }
                      }}
                      aria-label={t("privacy.class.col.select")}
                    />
                  </th>
                )}
                <th className="p-2.5">{t("privacy.class.col.name")}</th>
                <th className="p-2.5">{t("privacy.class.col.declared")}</th>
                <th className="p-2.5">{t("privacy.class.col.detected")}</th>
                <th className="p-2.5">{t("privacy.class.col.protection")}</th>
                <th className="p-2.5 text-center">{t("privacy.class.col.conflict")}</th>
                <th className="p-2.5">{t("privacy.class.col.reason")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {filteredColumns.length === 0 ? (
                <tr>
                  <td colSpan={canWrite ? 7 : 6} className="p-4 text-center text-sm text-fg-muted">
                    {t("common.empty")}
                  </td>
                </tr>
              ) : (
                filteredColumns.map((col) => {
                  const hasDraft = Object.prototype.hasOwnProperty.call(
                    draftChanges,
                    col.column_name
                  );
                  const effectiveVal = hasDraft
                    ? draftChanges[col.column_name]
                    : col.declared_category;
                  const selectValue = effectiveVal == null ? "UNDECLARED" : effectiveVal;

                  return (
                    <tr
                      key={col.column_name}
                      className={`hover:bg-surface-muted/50 ${
                        hasDraft ? "bg-amber-50/40 dark:bg-amber-950/20" : ""
                      }`}
                    >
                      {canWrite && (
                        <td className="p-2.5">
                          <input
                            type="checkbox"
                            className="rounded accent-action"
                            aria-label={`${t("privacy.class.col.select")} ${col.column_name}`}
                            checked={selectedCols.has(col.column_name)}
                            onChange={(e) => {
                              const next = new Set(selectedCols);
                              if (e.target.checked) next.add(col.column_name);
                              else next.delete(col.column_name);
                              setSelectedCols(next);
                            }}
                          />
                        </td>
                      )}
                      <td className="p-2.5 font-medium">
                        <span className="mono text-xs">{col.column_name}</span>
                        {hasDraft && (
                          <span className="ml-1 text-[10px] text-amber-600 dark:text-amber-400 font-normal">
                            *
                          </span>
                        )}
                      </td>
                      <td className="p-2.5">
                        {canWrite ? (
                          <select
                            className={`input text-xs py-1 ${
                              hasDraft ? "border-amber-500 font-medium" : ""
                            }`}
                            aria-label={`${t("privacy.class.col.declared")} ${col.column_name}`}
                            value={selectValue}
                            onChange={(e) => handleSetColumnCategory(col, e.target.value)}
                          >
                            {CLASSIFICATION_OPTIONS.map((opt) => (
                              <option key={opt.id} value={opt.id}>
                                {t(opt.labelKey)}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span className="text-xs">
                            {col.declared_category
                              ? t(`privacy.cat.${col.declared_category}` as TranslationKey)
                              : t("privacy.cat.UNDECLARED")}
                          </span>
                        )}
                      </td>
                      <td className="p-2.5 text-xs">
                        {col.detected_categories && col.detected_categories.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {col.detected_categories.map((cat) => (
                              <span
                                key={cat}
                                className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-100 text-blue-800 dark:bg-blue-950/60 dark:text-blue-300"
                              >
                                {t(`privacy.cat.${cat}` as TranslationKey)}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-fg-muted italic text-xs">—</span>
                        )}
                      </td>
                      <td className="p-2.5">
                        {col.protected ? (
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
                      </td>
                      <td className="p-2.5 text-center">
                        {col.conflict ? (
                          <span
                            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-900 dark:bg-amber-950/60 dark:text-amber-200 cursor-help"
                            title={t("privacy.class.conflict_tooltip")}
                          >
                            <AlertCircle className="size-3 text-amber-600" />
                            {t("privacy.class.conflict_badge")}
                          </span>
                        ) : (
                          <span className="text-fg-muted text-xs">—</span>
                        )}
                      </td>
                      <td className="p-2.5 text-xs text-fg-muted max-w-[200px] truncate" title={col.reason ?? ""}>
                        {col.reason || "—"}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Save Bar (only when draft exists and user can write) */}
        {canWrite && (
          <div className="space-y-3 pt-2 border-t border-border">
            {isDirty && (
              <div className="space-y-2">
                <label className="block text-xs font-medium text-fg">
                  {t("privacy.class.reason_label")}
                  <span className="text-red-500 ml-0.5">*</span>
                  <input
                    type="text"
                    className="input text-xs mt-1"
                    maxLength={500}
                    placeholder={t("privacy.class.reason_placeholder")}
                    value={classReason}
                    onChange={(e) => setClassReason(e.target.value)}
                    required
                  />
                </label>
                <p className="text-[11px] text-amber-700 dark:text-amber-400">
                  {t("privacy.security.reason_caution")}
                </p>
              </div>
            )}

            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs text-fg-muted">
                {isDirty
                  ? `${Object.keys(draftChanges).length} column(s) modified`
                  : !canWrite
                  ? t("privacy.class.readonly_notice")
                  : ""}
              </span>
              <div className="flex items-center gap-2">
                {isDirty && (
                  <button
                    type="button"
                    className="btn-secondary text-xs"
                    onClick={() => {
                      setDraftChanges({});
                      setClassReason("");
                    }}
                    disabled={saveClassificationsMutation.isPending}
                  >
                    {t("privacy.class.reset_draft")}
                  </button>
                )}
                <button
                  type="button"
                  className="btn-primary text-xs"
                  disabled={
                    !isDirty ||
                    !classReason.trim() ||
                    saveClassificationsMutation.isPending
                  }
                  onClick={() => saveClassificationsMutation.mutate()}
                >
                  {saveClassificationsMutation.isPending
                    ? t("privacy.class.saving")
                    : t("privacy.class.save_button")}
                </button>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* 3. Sensitive Data Scan Findings Table */}
      <section className="card space-y-4">
        <div className="flex items-center justify-between border-b border-border pb-3">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-sm">
              {t("privacy.findings.title")}
            </h3>
            {findingsQuery.data?.detector_revision && (
              <span className="mono text-xs text-fg-muted">
                Rev: {findingsQuery.data.detector_revision}
              </span>
            )}
          </div>
          <span className="text-xs text-fg-muted">
            {t("privacy.findings.pagination", {
              page: findingPage,
              total: totalFindingPages,
            })}
          </span>
        </div>

        <ProblemAlert error={findingsQuery.error} />
        {findingMutation.error ? <ProblemAlert error={findingMutation.error} /> : null}

        {scanStatus === "UNAVAILABLE" ? (
          <p className="text-sm text-fg-muted italic">
            {t("privacy.findings.unverified_note")}
          </p>
        ) : findings.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("privacy.findings.empty")}</p>
        ) : (
          <>
            {canWrite && (
              <label className="flex flex-col gap-1 text-xs font-medium text-fg-muted">
                {t("privacy.findings.review_reason_label")}
                <input
                  className="input w-full text-xs"
                  maxLength={500}
                  placeholder={t("privacy.findings.review_reason_placeholder")}
                  value={reviewReason}
                  onChange={(e) => setReviewReason(e.target.value)}
                />
              </label>
            )}

            <div className="overflow-x-auto rounded border border-border">
              <table className="w-full text-left text-sm">
                <thead className="bg-surface-muted text-xs text-fg-muted">
                  <tr>
                    <th className="p-2.5">Column</th>
                    <th className="p-2.5">Path</th>
                    <th className="p-2.5">Detector</th>
                    <th className="p-2.5">Category</th>
                    <th className="p-2.5 text-right">Matched / Obs</th>
                    <th className="p-2.5">Status</th>
                    {canWrite && <th className="p-2.5 text-right">Actions</th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {findings.map((f: FindingResponse) => (
                    <tr key={f.finding_id} className="hover:bg-surface-muted/50">
                      <td className="p-2.5 font-medium">
                        <div className="flex items-center gap-1.5">
                          <span>{f.column_name}</span>
                          {f.historical && (
                            <span
                              className="inline-flex items-center gap-0.5 px-1 py-0.2 rounded text-[10px] font-medium bg-amber-50 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 border border-amber-200 dark:border-amber-800"
                              title={t("privacy.findings.historical_badge")}
                            >
                              <History className="size-3" />
                              <span>{t("privacy.findings.historical_badge")}</span>
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="p-2.5 mono text-xs text-fg-muted">
                        {f.path || "/"}
                      </td>
                      <td className="p-2.5 mono text-xs">
                        <span>{f.detector_code}</span>
                        {f.rule_revision != null && (
                          <span className="text-[10px] text-fg-muted ml-1">
                            (r{f.rule_revision})
                          </span>
                        )}
                      </td>
                      <td className="p-2.5 text-xs">{f.category}</td>
                      <td className="p-2.5 text-right mono text-xs">
                        {f.matched_count} / {f.observed_count}
                      </td>
                      <td className="p-2.5">
                        <FindingStatusBadge status={f.status} />
                      </td>
                      {canWrite && (
                        <td className="p-2.5 text-right space-x-1">
                          {f.status !== "CONFIRMED" && (
                            <button
                              type="button"
                              className="btn-secondary text-xs px-2 py-1"
                              disabled={findingMutation.isPending || !reviewReason.trim()}
                              onClick={() =>
                                findingMutation.mutate({
                                  findingId: f.finding_id,
                                  expectedStatus: f.status,
                                  newStatus: "CONFIRMED",
                                })
                              }
                            >
                              {t("privacy.findings.confirm_btn")}
                            </button>
                          )}
                          {f.status !== "DISMISSED" && (
                            <button
                              type="button"
                              className="btn-secondary text-xs px-2 py-1 text-red-600"
                              disabled={findingMutation.isPending || !reviewReason.trim()}
                              onClick={() =>
                                findingMutation.mutate({
                                  findingId: f.finding_id,
                                  expectedStatus: f.status,
                                  newStatus: "DISMISSED",
                                })
                              }
                            >
                              {t("privacy.findings.dismiss_btn")}
                            </button>
                          )}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Findings Pager */}
            {totalFindingPages > 1 && (
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  className="btn-secondary text-xs px-2.5 py-1"
                  disabled={findingPage <= 1}
                  onClick={() => setFindingPage((p) => p - 1)}
                >
                  {t("common.previous")}
                </button>
                <button
                  type="button"
                  className="btn-secondary text-xs px-2.5 py-1"
                  disabled={findingPage >= totalFindingPages}
                  onClick={() => setFindingPage((p) => p + 1)}
                >
                  {t("common.next")}
                </button>
              </div>
            )}
          </>
        )}
      </section>

      {/* 4. Advanced: Asset Protection Policy Configuration */}
      <details className="card space-y-4 rounded border border-border bg-surface-muted/30">
        <summary className="flex items-center justify-between cursor-pointer select-none font-medium text-sm p-1">
          <div className="flex items-center gap-2">
            <ShieldCheck className="size-4 text-action" />
            <h3>{t("privacy.policy.heading")}</h3>
          </div>
          <div className="flex items-center gap-2 text-xs text-fg-muted">
            <span className="mono">v{policy?.version ?? 0}</span>
            <ChevronDown className="size-4" />
          </div>
        </summary>

        <div className="space-y-4 pt-3 border-t border-border">
          <p className="text-xs text-fg-muted">{t("privacy.policy.note")}</p>

          <ProblemAlert error={policyQuery.error} />
          {policyMutation.error ? <ProblemAlert error={policyMutation.error} /> : null}

          <div className="grid gap-2 sm:grid-cols-3">
            {ALL_POLICY_CATEGORIES.map((cat) => {
              const checked = categories.includes(cat.id);
              return (
                <label
                  key={cat.id}
                  className="flex items-center gap-2 text-xs cursor-pointer select-none"
                >
                  <input
                    type="checkbox"
                    className="rounded accent-action"
                    disabled={!canWrite}
                    checked={checked}
                    onChange={(e) => {
                      if (e.target.checked) {
                        setSelectedCats([...categories, cat.id]);
                      } else {
                        setSelectedCats(categories.filter((c) => c !== cat.id));
                      }
                    }}
                  />
                  <span>{t(cat.labelKey)}</span>
                </label>
              );
            })}
          </div>

          {canWrite && (
            <div className="flex justify-end pt-2">
              <button
                type="button"
                className="btn-primary text-xs"
                disabled={policyMutation.isPending}
                onClick={() => policyMutation.mutate()}
              >
                {policyMutation.isPending
                  ? t("privacy.policy.saving")
                  : t("privacy.policy.save")}
              </button>
            </div>
          )}
        </div>
      </details>
    </div>
  );
}
