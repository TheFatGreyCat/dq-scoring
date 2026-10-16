import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle,
  Play,
  Plus,
  RefreshCw,
  Shield,
  XCircle,
} from "lucide-react";
import { useEffect, useState } from "react";
import { session } from "../../api/client";
import {
  createPrivacyRule,
  createPrivacyScan,
  getPrivacyScan,
  getPrivacyScanFindings,
  getSensitiveFindings,
  listPrivacyRules,
  updatePrivacyRule,
} from "../../api/endpoints";
import type {
  FindingCategory,
  Page,
  PrivacyMatchMode,
  PrivacyRule,
  PrivacyRuleCreateRequest,
  PrivacyRuleKind,
  PrivacyRuleUpdateRequest,
  PrivacyScan,
  PrivacyScanFindingSummary,
  PrivacyScanRequest,
  UUID,
} from "../../api/types";
import { ProblemAlert } from "../../components/ProblemAlert";
import { formatCount, formatTimestamp } from "../../lib/format";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { POLICY_WRITE_ROLES, useIdentity } from "../auth/useIdentity";

interface PrivacyRulesPanelProps {
  assetId: UUID;
  snapshotId: UUID;
  snapshotColumns: string[];
}

const CATEGORY_OPTIONS: { id: FindingCategory; labelKey: TranslationKey }[] = [
  { id: "BASIC_PERSONAL_DATA", labelKey: "privacy.cat.BASIC_PERSONAL_DATA" },
  { id: "SENSITIVE_PERSONAL_DATA", labelKey: "privacy.cat.SENSITIVE_PERSONAL_DATA" },
  { id: "CONFIDENTIAL_BUSINESS_DATA", labelKey: "privacy.cat.CONFIDENTIAL_BUSINESS_DATA" },
];

export function PrivacyRulesPanel({
  snapshotId,
  snapshotColumns,
}: PrivacyRulesPanelProps) {
  const { t, lang } = useI18n();
  const queryClient = useQueryClient();
  const identity = useIdentity();
  const role = identity.data?.role;
  const canEdit = !!role && !!POLICY_WRITE_ROLES[role];

  // Pagination for rules list
  const [page, setPage] = useState(1);
  const pageSize = 50;

  // Form states
  const [showCreate, setShowCreate] = useState(false);
  const [editingRule, setEditingRule] = useState<PrivacyRule | null>(null);
  const [formError, setFormError] = useState<unknown | null>(null);

  // Active scan polling state (Preview or Apply)
  const [activeScanId, setActiveScanId] = useState<UUID | null>(null);
  const [previewFindingPage, setPreviewFindingPage] = useState(1);
  const [scanActionError, setScanActionError] = useState<unknown | null>(null);

  // Rules Query (only for editors)
  const rulesQuery = useQuery({
    queryKey: ["privacy-rules", session.email(), page, pageSize],
    queryFn: ({ signal }) => listPrivacyRules({ page, page_size: pageSize }, signal),
    enabled: canEdit,
  });

  const snapshotScanQuery = useQuery({
    queryKey: ["sensitive-findings", session.email(), snapshotId, "scan-metadata"],
    queryFn: ({ signal }) => getSensitiveFindings(snapshotId, { page: 1, page_size: 1 }, signal),
    enabled: canEdit,
  });

  // Polling active scan
  const scanQuery = useQuery({
    queryKey: ["privacy-scan", session.email(), activeScanId],
    queryFn: ({ signal }) => getPrivacyScan(activeScanId!, signal),
    enabled: !!activeScanId,
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      return state === "QUEUED" || state === "RUNNING" ? 2000 : false;
    },
    refetchIntervalInBackground: false,
  });

  const scanData: PrivacyScan | undefined = scanQuery.data;
  const isScanTerminal = scanData?.state === "COMPLETE" || scanData?.state === "FAILED";

  // When APPLY scan completes, invalidate classification, findings, and preview
  useEffect(() => {
    if (scanData?.purpose === "APPLY" && scanData.state === "COMPLETE") {
      void queryClient.invalidateQueries({ queryKey: ["column-classifications"] });
      void queryClient.invalidateQueries({ queryKey: ["sensitive-findings"] });
      void queryClient.invalidateQueries({ queryKey: ["preview"] });
    }
  }, [scanData?.state, scanData?.purpose, queryClient]);

  // Paginated Preview findings query
  const previewFindingsQuery = useQuery({
    queryKey: ["privacy-scan-findings", session.email(), activeScanId, previewFindingPage],
    queryFn: ({ signal }) =>
      getPrivacyScanFindings(activeScanId!, { page: previewFindingPage, page_size: 25 }, signal),
    enabled: !!activeScanId && scanData?.state === "COMPLETE" && scanData?.purpose === "PREVIEW",
  });

  // Mutations
  const createRuleMutation = useMutation({
    mutationFn: (body: PrivacyRuleCreateRequest) => createPrivacyRule(body),
    onSuccess: () => {
      setFormError(null);
      setShowCreate(false);
      void queryClient.invalidateQueries({ queryKey: ["privacy-rules"] });
      void queryClient.invalidateQueries({ queryKey: ["column-classifications"] });
      void queryClient.invalidateQueries({ queryKey: ["sensitive-findings"] });
    },
    onError: (err) => {
      setFormError(err);
    },
  });

  const updateRuleMutation = useMutation({
    mutationFn: ({ ruleId, body }: { ruleId: UUID; body: PrivacyRuleUpdateRequest }) =>
      updatePrivacyRule(ruleId, body),
    onSuccess: () => {
      setFormError(null);
      setEditingRule(null);
      void queryClient.invalidateQueries({ queryKey: ["privacy-rules"] });
      void queryClient.invalidateQueries({ queryKey: ["column-classifications"] });
      void queryClient.invalidateQueries({ queryKey: ["sensitive-findings"] });
    },
    onError: (err) => {
      setFormError(err);
      void queryClient.invalidateQueries({ queryKey: ["privacy-rules"] });
    },
  });

  const triggerScanMutation = useMutation({
    mutationFn: (body: PrivacyScanRequest) => createPrivacyScan(snapshotId, body),
    onSuccess: (job) => {
      setScanActionError(null);
      setActiveScanId(job.scan_id);
      setPreviewFindingPage(1);
    },
    onError: (err) => {
      setScanActionError(err);
    },
  });

  // Toggle quick enable/disable
  const handleToggle = (rule: PrivacyRule) => {
    updateRuleMutation.mutate({
      ruleId: rule.rule_id,
      body: {
        expected_revision: rule.revision,
        category: rule.category,
        enabled: !rule.enabled,
        pattern: rule.kind === "BUILTIN" ? null : rule.pattern,
        match_mode: rule.match_mode,
        case_sensitive: rule.case_sensitive,
        columns: rule.columns,
      },
    });
  };

  // Run preview on this snapshot
  const handleTryRule = (rule: PrivacyRule) => {
    setScanActionError(null);
    triggerScanMutation.mutate({
      purpose: "PREVIEW",
      rule_id: rule.rule_id,
      revision: rule.revision,
    });
  };

  // Run apply on this snapshot
  const handleApplyRescan = () => {
    setScanActionError(null);
    triggerScanMutation.mutate({ purpose: "APPLY" });
  };

  if (!canEdit) {
    return (
      <section className="card p-6" data-testid="privacy-rules-panel">
        <div className="flex items-start gap-3 text-fg-muted">
          <Shield className="size-5 shrink-0 text-amber-500 mt-0.5" />
          <div>
            <h2 className="text-base font-semibold text-fg">{t("privacy.rules.title")}</h2>
            <p className="text-sm mt-1">{t("privacy.rules.no_permission")}</p>
          </div>
        </div>
      </section>
    );
  }

  const rules: PrivacyRule[] = rulesQuery.data?.items ?? [];
  const totalRules = rulesQuery.data?.total ?? 0;
  const totalPages = Math.ceil(totalRules / pageSize) || 1;

  return (
    <div className="space-y-6" data-testid="privacy-rules-panel">
      {/* 1. Header & Actions */}
      <section className="card space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-4">
          <div>
            <div className="flex items-center gap-2">
              <Shield className="size-5 text-action" />
              <h2 className="text-base font-semibold">{t("privacy.rules.title")}</h2>
            </div>
            <p className="text-xs text-fg-muted mt-1">{t("privacy.rules.subtitle")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="btn-secondary text-xs"
              onClick={handleApplyRescan}
              disabled={triggerScanMutation.isPending || (scanData && !isScanTerminal)}
            >
              <RefreshCw
                className={`size-3.5 ${
                  scanData && !isScanTerminal ? "animate-spin" : ""
                }`}
              />
              {t("privacy.rules.btn_rescan")}
            </button>
            <button
              type="button"
              className="btn-primary text-xs"
              onClick={() => {
                setEditingRule(null);
                setShowCreate(true);
              }}
              disabled={rules.filter((r) => r.enabled).length >= 100}
            >
              <Plus className="size-3.5" />
              {t("privacy.rules.btn_new")}
            </button>
          </div>
        </div>
        {snapshotScanQuery.data && (
          <div className="text-xs text-fg-muted space-y-1">
            <p>{t("privacy.scan.status_label")}: {snapshotScanQuery.data.scan_status}</p>
            <p>{t("privacy.scan.last_scanned")}: {snapshotScanQuery.data.scanned_at ? formatTimestamp(snapshotScanQuery.data.scanned_at, lang).local : "—"}</p>
            <p>{t("privacy.scan.config_version", { version: snapshotScanQuery.data.config_version ?? "—" })}</p>
            {snapshotScanQuery.data.scan_stale && <p className="text-amber-700 dark:text-amber-400">{t("privacy.scan.stale_warning")}</p>}
          </div>
        )}

        {/* Global actions/alerts */}
        <ProblemAlert error={rulesQuery.error} />
        <ProblemAlert error={scanActionError} />
        {formError ? <ProblemAlert error={formError} /> : null}

        {/* Create / Edit Form */}
        {(showCreate || editingRule) && (
          <div className="p-4 rounded border border-border bg-surface-muted/60 space-y-4">
            <h3 className="text-sm font-semibold">
              {editingRule
                ? t("privacy.rules.form.edit_title", {
                    code: editingRule.code,
                    rev: editingRule.revision,
                  })
                : t("privacy.rules.form.create_title")}
            </h3>
            <RuleEditorForm
              rule={editingRule}
              snapshotColumns={snapshotColumns}
              isSubmitting={createRuleMutation.isPending || updateRuleMutation.isPending}
              onCancel={() => {
                setShowCreate(false);
                setEditingRule(null);
                setFormError(null);
              }}
              onSubmit={(values) => {
                setFormError(null);
                if (editingRule) {
                  updateRuleMutation.mutate({
                    ruleId: editingRule.rule_id,
                    body: {
                      expected_revision: editingRule.revision,
                      category: values.category,
                      enabled: values.enabled,
                      pattern: editingRule.kind === "BUILTIN" ? null : values.pattern,
                      match_mode: values.match_mode,
                      case_sensitive: values.case_sensitive,
                      columns: values.columns,
                    },
                  });
                } else {
                  createRuleMutation.mutate({
                    code: values.code,
                    kind: values.kind as "COLUMN_NAME" | "VALUE_PATTERN",
                    category: values.category,
                    enabled: values.enabled,
                    pattern: values.pattern,
                    match_mode: values.match_mode,
                    case_sensitive: values.case_sensitive,
                    columns: values.columns,
                  });
                }
              }}
            />
          </div>
        )}

        {/* Active Scan Results Banner / Dialog */}
        {activeScanId && scanData && (
          <ActiveScanCard
            scan={scanData}
            findingsPage={previewFindingsQuery.data}
            findingsLoading={previewFindingsQuery.isLoading}
            page={previewFindingPage}
            onPageChange={setPreviewFindingPage}
            onDismiss={() => setActiveScanId(null)}
          />
        )}

        {/* 2. Rules Table */}
        <div className="overflow-x-auto rounded border border-border">
          <table className="w-full text-left text-sm">
            <thead className="bg-surface-muted text-xs text-fg-muted">
              <tr>
                <th className="p-2.5">{t("privacy.rules.col.code")}</th>
                <th className="p-2.5">{t("privacy.rules.col.kind")}</th>
                <th className="p-2.5">{t("privacy.rules.col.category")}</th>
                <th className="p-2.5">{t("privacy.rules.col.pattern")}</th>
                <th className="p-2.5">{t("privacy.rules.col.scope")}</th>
                <th className="p-2.5 text-center">{t("privacy.rules.col.revision")}</th>
                <th className="p-2.5 text-center">{t("privacy.rules.col.status")}</th>
                <th className="p-2.5 text-right">{t("privacy.rules.col.actions")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rules.length === 0 ? (
                <tr>
                  <td colSpan={8} className="p-4 text-center text-sm text-fg-muted">
                    {t("common.empty")}
                  </td>
                </tr>
              ) : (
                rules.map((rule) => {
                  const isBuiltin = rule.kind === "BUILTIN";
                  return (
                    <tr key={rule.rule_id} className="hover:bg-surface-muted/50">
                      <td className="p-2.5 font-medium">
                        <div className="flex items-center gap-1.5">
                          <span className="mono text-xs">{rule.code}</span>
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                              isBuiltin
                                ? "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
                                : "bg-purple-100 text-purple-800 dark:bg-purple-950/60 dark:text-purple-300"
                            }`}
                          >
                            {isBuiltin
                              ? t("privacy.rules.builtin_badge")
                              : t("privacy.rules.custom_badge")}
                          </span>
                        </div>
                      </td>
                      <td className="p-2.5 text-xs text-fg-muted">
                        {t(`privacy.rules.kind.${rule.kind}` as TranslationKey)}
                      </td>
                      <td className="p-2.5 text-xs">
                        <span className="inline-block px-1.5 py-0.5 rounded text-[11px] font-medium bg-blue-100 text-blue-800 dark:bg-blue-950/60 dark:text-blue-300">
                          {t(`privacy.cat.${rule.category}` as TranslationKey)}
                        </span>
                      </td>
                      <td className="p-2.5 text-xs">
                        {rule.pattern ? (
                          <div className="space-y-0.5">
                            <span className="mono text-[11px] bg-surface-muted px-1 py-0.5 rounded border border-border inline-block max-w-[200px] truncate" title={rule.pattern}>
                              {rule.pattern}
                            </span>
                            <div className="text-[10px] text-fg-muted">
                              {t(`privacy.rules.match.${rule.match_mode}` as TranslationKey)}
                              {rule.case_sensitive
                                ? ` · ${t("privacy.rules.case_sensitive")}`
                                : ""}
                            </div>
                          </div>
                        ) : (
                          <span className="text-fg-muted italic text-xs">—</span>
                        )}
                      </td>
                      <td className="p-2.5 text-xs">
                        {rule.columns && rule.columns.length > 0 ? (
                          <span
                            className="mono text-xs cursor-help underline decoration-dotted"
                            title={rule.columns.join(", ")}
                          >
                            {t("privacy.rules.scope_count", {
                              count: rule.columns.length,
                            })}
                          </span>
                        ) : (
                          <span className="text-fg-muted text-xs">
                            {t("privacy.rules.scope_all")}
                          </span>
                        )}
                      </td>
                      <td className="p-2.5 text-center mono text-xs">r{rule.revision}</td>
                      <td className="p-2.5 text-center">
                        <span
                          className={`inline-block px-1.5 py-0.5 rounded text-[11px] font-medium ${
                            rule.enabled
                              ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300"
                              : "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400"
                          }`}
                        >
                          {rule.enabled
                            ? t("privacy.rules.btn_toggle_disable") === "Tắt"
                              ? "Bật"
                              : "Enabled"
                            : t("privacy.rules.btn_toggle_disable") === "Tắt"
                            ? "Tắt"
                            : "Disabled"}
                        </span>
                      </td>
                      <td className="p-2.5 text-right space-x-1">
                        <button
                          type="button"
                          className="btn-secondary text-xs px-2 py-1"
                          onClick={() => handleTryRule(rule)}
                          disabled={triggerScanMutation.isPending || (scanData && !isScanTerminal)}
                          title={t("privacy.rules.btn_try")}
                        >
                          <Play className="size-3 text-action inline" />
                          <span className="ml-1">{t("privacy.rules.btn_try")}</span>
                        </button>
                        <button
                          type="button"
                          className="btn-secondary text-xs px-2 py-1"
                          onClick={() => {
                            setShowCreate(false);
                            setEditingRule(rule);
                          }}
                        >
                          {t("privacy.rules.btn_edit")}
                        </button>
                        <button
                          type="button"
                          className="btn-secondary text-xs px-2 py-1"
                          onClick={() => handleToggle(rule)}
                          disabled={updateRuleMutation.isPending}
                        >
                          {rule.enabled
                            ? t("privacy.rules.btn_toggle_disable")
                            : t("privacy.rules.btn_toggle_enable")}
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pager */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between text-xs text-fg-muted pt-2">
            <span>
              {t("privacy.findings.pagination", { page, total: totalPages })}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                className="btn-secondary text-xs px-2 py-1"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                {t("common.previous")}
              </button>
              <button
                type="button"
                className="btn-secondary text-xs px-2 py-1"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                {t("common.next")}
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Rule Editor Form (Shared for Create & Edit)
// ---------------------------------------------------------------------------

interface FormValues {
  code: string;
  kind: PrivacyRuleKind;
  category: FindingCategory;
  pattern: string;
  match_mode: PrivacyMatchMode;
  case_sensitive: boolean;
  enabled: boolean;
  columns: string[];
}

function RuleEditorForm({
  rule,
  snapshotColumns,
  isSubmitting,
  onSubmit,
  onCancel,
}: {
  rule: PrivacyRule | null;
  snapshotColumns: string[];
  isSubmitting: boolean;
  onSubmit: (values: FormValues) => void;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  const isBuiltin = rule?.kind === "BUILTIN";

  const [code, setCode] = useState(rule?.code ?? "");
  const [kind, setKind] = useState<PrivacyRuleKind>(rule?.kind ?? "VALUE_PATTERN");
  const [category, setCategory] = useState<FindingCategory>(
    rule?.category ?? "BASIC_PERSONAL_DATA"
  );
  const [pattern, setPattern] = useState(rule?.pattern ?? "");
  const [matchMode, setMatchMode] = useState<PrivacyMatchMode>(
    rule?.match_mode ?? "FULL"
  );
  const [caseSensitive, setCaseSensitive] = useState(rule?.case_sensitive ?? true);
  const [enabled, setEnabled] = useState(rule?.enabled ?? true);
  const [selectedColumns, setSelectedColumns] = useState<string[]>(rule?.columns ?? []);

  // Code validation: ^[A-Z][A-Z0-9_]{0,63}$
  const isCodeValid = /^[A-Z][A-Z0-9_]{0,63}$/.test(code);
  const isPatternValid = isBuiltin || (pattern.trim().length > 0 && pattern.length <= 512);

  const canSubmit =
    !isSubmitting &&
    (rule ? true : isCodeValid) &&
    isPatternValid;

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (!canSubmit) return;
        onSubmit({
          code,
          kind,
          category,
          pattern: pattern.trim(),
          match_mode: matchMode,
          case_sensitive: caseSensitive,
          enabled,
          columns: selectedColumns,
        });
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {/* Code */}
        <div>
          <label className="label text-xs">
            {t("privacy.rules.form.code")}
          </label>
          <input
            className="input text-xs mono"
            aria-label={t("privacy.rules.form.code")}
            disabled={!!rule}
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            maxLength={64}
            required
            pattern="^[A-Z][A-Z0-9_]{0,63}$"
          />
        </div>

        {/* Kind */}
        <div>
          <label className="label text-xs">{t("privacy.rules.form.kind")}</label>
          {rule ? (
            <input
              className="input text-xs"
              aria-label={t("privacy.rules.form.kind")}
              disabled
              value={t(`privacy.rules.kind.${rule.kind}` as TranslationKey)}
            />
          ) : (
            <select
              className="input text-xs"
              aria-label={t("privacy.rules.form.kind")}
              value={kind}
              onChange={(e) => setKind(e.target.value as PrivacyRuleKind)}
            >
              <option value="VALUE_PATTERN">
                {t("privacy.rules.kind.VALUE_PATTERN")}
              </option>
              <option value="COLUMN_NAME">
                {t("privacy.rules.kind.COLUMN_NAME")}
              </option>
            </select>
          )}
        </div>

        {/* Category */}
        <div>
          <label className="label text-xs">{t("privacy.rules.form.category")}</label>
          <select
            className="input text-xs"
            aria-label={t("privacy.rules.form.category")}
            value={category}
            onChange={(e) => setCategory(e.target.value as FindingCategory)}
          >
            {CATEGORY_OPTIONS.map((cat) => (
              <option key={cat.id} value={cat.id}>
                {t(cat.labelKey)}
              </option>
            ))}
          </select>
        </div>

        {/* Enabled */}
        <div className="flex items-center pt-6">
          <label className="flex items-center gap-2 text-xs cursor-pointer">
            <input
              type="checkbox"
              className="rounded accent-action"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            <span>{t("privacy.rules.form.enabled")}</span>
          </label>
        </div>
      </div>

      {/* Pattern details (Custom rules only) */}
      {!isBuiltin && (
        <div className="space-y-3 rounded border border-border p-3 bg-surface">
          <div>
            <label className="label text-xs">
              {t("privacy.rules.form.pattern")}
            </label>
            <input
              className="input text-xs mono"
              aria-label={t("privacy.rules.form.pattern")}
              value={pattern}
              onChange={(e) => setPattern(e.target.value)}
              maxLength={512}
              required
              placeholder="e.g. ^[0-9]{3}-[0-9]{2}-[0-9]{4}$"
            />
            <p className="text-[11px] text-amber-700 dark:text-amber-400 mt-1">
              {t("privacy.security.pattern_caution")}
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label text-xs">
                {t("privacy.rules.form.match_mode")}
              </label>
              <select
                className="input text-xs"
                aria-label={t("privacy.rules.form.match_mode")}
                value={matchMode}
                onChange={(e) => setMatchMode(e.target.value as PrivacyMatchMode)}
              >
                <option value="FULL">{t("privacy.rules.match.FULL")}</option>
                <option value="SEARCH">{t("privacy.rules.match.SEARCH")}</option>
              </select>
            </div>
            <div className="flex items-center pt-4">
              <label className="flex items-center gap-2 text-xs cursor-pointer">
                <input
                  type="checkbox"
                  className="rounded accent-action"
                  checked={caseSensitive}
                  onChange={(e) => setCaseSensitive(e.target.checked)}
                />
                <span>{t("privacy.rules.form.case_sensitive")}</span>
              </label>
            </div>
          </div>
        </div>
      )}

      {/* Column Scope Selector */}
      <div className="space-y-1">
        <label className="label text-xs">{t("privacy.rules.form.scope")}</label>
        {snapshotColumns.length > 0 ? (
          <div className="max-h-36 overflow-y-auto rounded border border-border p-2 bg-surface grid grid-cols-2 sm:grid-cols-3 gap-1.5 text-xs">
            {snapshotColumns.map((colName) => {
              const isChecked = selectedColumns.includes(colName);
              return (
                <label
                  key={colName}
                  className="flex items-center gap-1.5 truncate cursor-pointer hover:text-action"
                >
                  <input
                    type="checkbox"
                    className="rounded accent-action"
                    checked={isChecked}
                    onChange={(e) => {
                      if (e.target.checked) {
                        setSelectedColumns([...selectedColumns, colName]);
                      } else {
                        setSelectedColumns(selectedColumns.filter((c) => c !== colName));
                      }
                    }}
                  />
                  <span className="truncate" title={colName}>
                    {colName}
                  </span>
                </label>
              );
            })}
          </div>
        ) : (
          <p className="text-xs text-fg-muted italic">—</p>
        )}
        <div className="flex items-center justify-between text-[11px] text-fg-muted">
          <span>
            {selectedColumns.length === 0
              ? t("privacy.rules.scope_all")
              : t("privacy.rules.scope_count", { count: selectedColumns.length })}
          </span>
          {selectedColumns.length > 0 && (
            <button
              type="button"
              className="text-action underline"
              onClick={() => setSelectedColumns([])}
            >
              {t("common.reset")}
            </button>
          )}
        </div>
      </div>

      <div className="flex justify-end gap-2 pt-2">
        <button
          type="button"
          className="btn-secondary text-xs"
          onClick={onCancel}
          disabled={isSubmitting}
        >
          {t("privacy.rules.form.cancel")}
        </button>
        <button
          type="submit"
          className="btn-primary text-xs"
          disabled={!canSubmit}
        >
          {isSubmitting
            ? t("common.loading")
            : rule
            ? t("privacy.rules.form.submit_update")
            : t("privacy.rules.form.submit_create")}
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Active Scan Results Banner / Card
// ---------------------------------------------------------------------------

function ActiveScanCard({
  scan,
  findingsPage,
  findingsLoading,
  page,
  onPageChange,
  onDismiss,
}: {
  scan: PrivacyScan;
  findingsPage?: Page<PrivacyScanFindingSummary>;
  findingsLoading: boolean;
  page: number;
  onPageChange: (p: number) => void;
  onDismiss: () => void;
}) {
  const { t, lang } = useI18n();
  const summary = scan.result_summary;
  const isPreview = scan.purpose === "PREVIEW";
  const isComplete = scan.state === "COMPLETE";
  const isFailed = scan.state === "FAILED";

  const totalFindings = summary?.finding_count ?? findingsPage?.total ?? summary?.findings?.length ?? 0;
  const totalPages = findingsPage
    ? Math.ceil(findingsPage.total / findingsPage.page_size) || 1
    : 1;

  return (
    <div className="rounded border border-border p-4 bg-surface space-y-3">
      <div className="flex items-center justify-between border-b border-border pb-2">
        <div className="flex items-center gap-2">
          {isComplete ? (
            <CheckCircle className="size-4 text-emerald-600" />
          ) : isFailed ? (
            <XCircle className="size-4 text-red-600" />
          ) : (
            <RefreshCw className="size-4 text-action animate-spin" />
          )}
          <h3 className="text-sm font-semibold">
            {isPreview
              ? t("privacy.scan_job.preview_title")
              : t("privacy.scan_job.apply_title")}
          </h3>
          <span className="mono text-xs text-fg-muted">[{scan.state}]</span>
        </div>
        <button
          type="button"
          className="btn-secondary text-xs px-2 py-0.5"
          onClick={onDismiss}
        >
          {t("privacy.scan_job.dismiss_preview")}
        </button>
      </div>

      {/* State or Error */}
      {scan.state === "QUEUED" && (
        <p className="text-xs text-fg-muted">{t("privacy.scan_job.state.QUEUED")}</p>
      )}
      {scan.state === "RUNNING" && (
        <p className="text-xs text-fg-muted">{t("privacy.scan_job.state.RUNNING")}</p>
      )}
      {isFailed && (
        <div className="rounded border border-red-200 bg-red-50 p-2.5 text-xs text-red-800 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-300">
          <p className="font-semibold">{t("privacy.scan_job.state.FAILED")}</p>
          <p className="mt-0.5">
            {scan.error_code
              ? t(`privacy.scan_error.${scan.error_code}` as TranslationKey)
              : "Scan failed"}
          </p>
        </div>
      )}

      {/* Missing scope warning */}
      {summary?.scope_missing_columns && summary.scope_missing_columns.length > 0 && (
        <div className="rounded border border-amber-200 bg-amber-50 p-2.5 text-xs text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300 flex items-start gap-2">
          <AlertTriangle className="size-4 shrink-0 mt-0.5" />
          <div>
            {summary.scope_missing_columns.map((m, i) => (
              <p key={i}>
                {t("privacy.scan_job.scope_missing", {
                  columns: m.missing_columns.join(", "),
                })}
              </p>
            ))}
          </div>
        </div>
      )}

      {/* Findings Preview Table */}
      {isComplete && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-fg-muted">
            <span className="font-medium">
              {t("privacy.scan_job.total_findings", {
                count: formatCount(totalFindings, lang),
              })}
            </span>
            {isPreview && (
              <span className="text-[11px] text-amber-600 dark:text-amber-400">
                {t("privacy.scan_job.purpose.PREVIEW")}
              </span>
            )}
          </div>

          {findingsLoading ? (
            <p className="text-xs text-fg-muted" aria-busy="true">
              {t("common.loading")}
            </p>
          ) : totalFindings === 0 ? (
            <p className="text-xs text-fg-muted italic">
              {t("privacy.scan_job.no_findings")}
            </p>
          ) : isPreview ? (
            <div className="overflow-x-auto rounded border border-border">
              <table className="w-full text-left text-xs">
                <thead className="bg-surface-muted text-fg-muted">
                  <tr>
                    <th className="p-2">{t("privacy.class.col.name")}</th>
                    <th className="p-2">Path</th>
                    <th className="p-2">Detector</th>
                    <th className="p-2">{t("privacy.rules.col.category")}</th>
                    <th className="p-2 text-right">Matched / Obs</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {(findingsPage?.items ?? summary?.findings ?? []).map(
                    (f: PrivacyScanFindingSummary, i: number) => (
                      <tr key={i} className="hover:bg-surface-muted/50">
                        <td className="p-2 font-medium">{f.column_name}</td>
                        <td className="p-2 mono text-[11px] text-fg-muted">
                          {f.path || "/"}
                        </td>
                        <td className="p-2 mono text-[11px]">{f.detector_code}</td>
                        <td className="p-2">
                          <span className="inline-block px-1 py-0.5 rounded text-[10px] font-medium bg-blue-100 text-blue-800 dark:bg-blue-950/60 dark:text-blue-300">
                            {t(`privacy.cat.${f.category}` as TranslationKey)}
                          </span>
                        </td>
                        <td className="p-2 text-right mono text-[11px]">
                          {f.matched_count} / {f.observed_count}
                        </td>
                      </tr>
                    )
                  )}
                </tbody>
              </table>
            </div>
          ) : null}

          {/* Findings pager */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between text-xs text-fg-muted pt-1">
              <span>
                {t("privacy.findings.pagination", { page, total: totalPages })}
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  className="btn-secondary text-xs px-2 py-0.5"
                  disabled={page <= 1}
                  onClick={() => onPageChange(page - 1)}
                >
                  {t("common.previous")}
                </button>
                <button
                  type="button"
                  className="btn-secondary text-xs px-2 py-0.5"
                  disabled={page >= totalPages}
                  onClick={() => onPageChange(page + 1)}
                >
                  {t("common.next")}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
