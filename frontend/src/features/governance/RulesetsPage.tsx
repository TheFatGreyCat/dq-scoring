import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, CheckCircle2, ChevronRight, Layers, Lightbulb, ListFilter, Plus, Save, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";
import { session } from "../../api/client";
import {
  createRuleset,
  getRecommendations,
  getRulesetTemplate,
  getSnapshot,
  listAssets,
  listRulesets,
  listSnapshots,
} from "../../api/endpoints";
import type { QualityRuleInput, RulesetResponse } from "../../api/types";
import { CopyId } from "../../components/CopyId";
import { Field, PageHeader } from "../../components/Field";
import { isUuid } from "../../components/IdLookup";
import { ProblemAlert } from "../../components/ProblemAlert";
import { GovernanceBadge } from "../../components/StatusBadge";
import { useI18n } from "../../lib/i18n";
import type { GovernanceKey } from "../../lib/governanceTranslations";
import { recent, useRecent } from "../../lib/recent";
import { ApprovalPanel } from "./ApprovalPanel";
import { RuleRow } from "./RuleRow";
import {
  extractTemplatePlaceholders,
  instantiateTemplateRules,
  mergeAndDedupeRules,
  newRule,
  normalizeRulesPayload,
  toRuleInput,
  validateRule,
  type RuleDraft,
} from "./ruleForm";

export function RulesetsPage() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();

  // URL Query state
  const filters = useMemo(
    () => ({
      q: params.get("q") ?? "",
      status: params.get("status") ?? "",
      asset_id: params.get("asset_id") ?? "",
      page: Number(params.get("page") ?? 1),
      page_size: 25,
    }),
    [params],
  );

  const initialSnapshotParam = params.get("snapshot") ?? "";
  const initialTemplateParam = params.get("template") ?? "";
  const initialAssetParam = params.get("asset") ?? "";

  const [selectedRuleset, setSelectedRuleset] = useState<RulesetResponse | null>(null);

  const updateParam = (key: string, value: string) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value) next.set(key, value);
      else next.delete(key);
      if (key !== "page") next.delete("page");
      return next;
    });
  };

  // Queries
  const rulesetsQuery = useQuery({
    queryKey: ["rulesets", session.email(), filters],
    queryFn: ({ signal }) => listRulesets(filters, signal),
  });

  const assetsQuery = useQuery({
    queryKey: ["assets", session.email(), { page_size: 100 }],
    queryFn: ({ signal }) => listAssets({ page_size: 100 }, signal),
  });

  const serverItems = useMemo(
    () =>
      rulesetsQuery.data?.items.map((r) => ({
        id: r.ruleset_id,
        label: r.name,
        status: r.status,
      })) ?? [],
    [rulesetsQuery.data],
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("gov.rulesets.title")}
        description={t("gov.rulesets.subtitle")}
      />

      {/* Persistent List Section */}
      <section className="card space-y-4" aria-labelledby="rulesets-list-heading">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="rulesets-list-heading" className="flex items-center gap-2 text-lg font-bold">
            <ListFilter className="size-5 text-action" aria-hidden />
            {t("gov.rulesets.list")}
          </h2>
          <span className="text-sm text-fg-muted">
            {t("common.count", { count: rulesetsQuery.data?.total ?? 0 })}
          </span>
        </div>

        {/* Filter controls */}
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t("common.search")}>
            {(id) => (
              <input
                id={id}
                className="input"
                placeholder={t("common.search")}
                value={filters.q}
                onChange={(e) => updateParam("q", e.target.value)}
              />
            )}
          </Field>

          <Field label={t("gov.rulesets.filter_status")}>
            {(id) => (
              <select
                id={id}
                className="input"
                value={filters.status}
                onChange={(e) => updateParam("status", e.target.value)}
              >
                <option value="">{t("common.all")}</option>
                <option value="DRAFT">{t("status.DRAFT")}</option>
                <option value="PENDING_APPROVAL">{t("status.PENDING_APPROVAL")}</option>
                <option value="ACTIVE">{t("status.ACTIVE")}</option>
              </select>
            )}
          </Field>

          <Field label={t("gov.rulesets.filter_asset")}>
            {(id) => (
              <select
                id={id}
                className="input"
                value={filters.asset_id}
                onChange={(e) => updateParam("asset_id", e.target.value)}
              >
                <option value="">{t("gov.rulesets.all_assets")}</option>
                {assetsQuery.data?.items.map((asset) => (
                  <option key={asset.asset_id} value={asset.asset_id}>
                    {asset.name}
                  </option>
                ))}
              </select>
            )}
          </Field>
        </div>

        <ProblemAlert error={rulesetsQuery.error} />

        {rulesetsQuery.isPending ? (
          <p className="py-4 text-center text-fg-muted">{t("common.loading")}</p>
        ) : rulesetsQuery.data?.items.length === 0 ? (
          <p className="py-4 text-center text-fg-muted">{t("gov.rulesets.no_rulesets")}</p>
        ) : (
          <div className="overflow-x-auto rounded-control border border-border">
            <table className="w-full text-left text-sm">
              <thead className="bg-surface-muted text-xs uppercase text-fg-muted border-b border-border">
                <tr>
                  <th className="px-4 py-3">{t("common.name")}</th>
                  <th className="px-4 py-3">{t("gov.rulesets.asset")}</th>
                  <th className="px-4 py-3">{t("common.status")}</th>
                  <th className="px-4 py-3">{t("gov.rulesets.rules_count", { count: "" })}</th>
                  <th className="px-4 py-3">{t("common.created")}</th>
                  <th className="px-4 py-3 text-right"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {rulesetsQuery.data?.items.map((r) => {
                  const isSelected = selectedRuleset?.ruleset_id === r.ruleset_id;
                  const assetName =
                    assetsQuery.data?.items.find((a) => a.asset_id === r.asset_id)?.name ?? r.asset_id;
                  return (
                    <tr
                      key={r.ruleset_id}
                      onClick={() => setSelectedRuleset(r)}
                      className={`cursor-pointer transition-colors hover:bg-surface-muted/60 ${
                        isSelected ? "bg-action/10 font-medium" : ""
                      }`}
                    >
                      <td className="px-4 py-3">
                        <div className="font-semibold text-fg">{r.name}</div>
                        <div className="mono text-xs text-fg-muted">v{r.current_version}</div>
                      </td>
                      <td className="px-4 py-3 text-fg-muted">{assetName}</td>
                      <td className="px-4 py-3">
                        <GovernanceBadge status={r.status} />
                      </td>
                      <td className="px-4 py-3 font-mono">{r.rules?.length ?? 0}</td>
                      <td className="px-4 py-3 text-xs text-fg-muted">
                        {r.created_at ? new Date(r.created_at).toLocaleString() : ""}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          type="button"
                          className="btn-secondary text-xs"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedRuleset(r);
                          }}
                        >
                          {t("btn.open")} <ChevronRight className="size-3.5" aria-hidden />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination & Reset */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn-secondary text-xs"
              disabled={filters.page <= 1}
              onClick={() => updateParam("page", String(filters.page - 1))}
            >
              {t("common.previous")}
            </button>
            <span className="text-xs text-fg-muted">
              {filters.page} / {Math.ceil((rulesetsQuery.data?.total ?? 0) / filters.page_size) || 1}
            </span>
            <button
              type="button"
              className="btn-secondary text-xs"
              disabled={filters.page * filters.page_size >= (rulesetsQuery.data?.total ?? 0)}
              onClick={() => updateParam("page", String(filters.page + 1))}
            >
              {t("common.next")}
            </button>
          </div>
          <button
            type="button"
            className="btn-secondary text-xs"
            onClick={() => {
              updateParam("q", "");
              updateParam("status", "");
              updateParam("asset_id", "");
              updateParam("page", "1");
            }}
          >
            {t("common.reset")}
          </button>
        </div>
      </section>

      {/* Editor & Approval Panel layout */}
      <div className="grid gap-6 2xl:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)] items-start">
        <RulesetEditor
          initialSnapshotId={initialSnapshotParam}
          initialTemplateId={initialTemplateParam}
          initialAssetId={initialAssetParam}
          onSaved={(newlyCreated) => {
            rulesetsQuery.refetch();
            setSelectedRuleset(newlyCreated);
          }}
        />

        <ApprovalPanel<RulesetResponse>
          kind="rulesets"
          recentKind="ruleset"
          noun="Ruleset"
          idOf={(r) => r.ruleset_id}
          selectedEntity={selectedRuleset}
          serverItems={serverItems}
          onActionSuccess={() => rulesetsQuery.refetch()}
        />
      </div>
    </div>
  );
}

function RulesetEditor({
  initialSnapshotId,
  initialTemplateId,
  initialAssetId,
  onSaved,
}: {
  initialSnapshotId: string;
  initialTemplateId: string;
  initialAssetId: string;
  onSaved: (ruleset: RulesetResponse) => void;
}) {
  const { t } = useI18n();
  const recentAssets = useRecent("asset");

  const [assetId, setAssetId] = useState(initialAssetId || recentAssets[0]?.id || "");
  const [snapshotId, setSnapshotId] = useState(initialSnapshotId);
  const [templateId] = useState(initialTemplateId);
  const [name, setName] = useState("");
  const [rules, setRules] = useState<RuleDraft[]>([newRule()]);
  const [showErrors, setShowErrors] = useState(false);

  // Template mapping state
  const [placeholderMapping, setPlaceholderMapping] = useState<Record<string, string>>({});
  const [templateApplied, setTemplateApplied] = useState(false);

  // Recommendations state
  const [selectedRecRules, setSelectedRecRules] = useState<Record<string, boolean>>({});

  // Query server assets
  const assetsQuery = useQuery({
    queryKey: ["assets", session.email(), { page_size: 100 }],
    queryFn: ({ signal }) => listAssets({ page_size: 100 }, signal),
  });

  // Query server snapshots for this asset (or all snapshots)
  const snapshotsQuery = useQuery({
    queryKey: ["snapshots", session.email(), { asset_id: assetId || undefined, page_size: 100 }],
    queryFn: ({ signal }) => listSnapshots({ asset_id: assetId || undefined, page_size: 100 }, signal),
    enabled: Boolean(assetId),
  });

  // Snapshot schema query
  const snapshotQuery = useQuery({
    queryKey: ["snapshot", session.email(), snapshotId],
    queryFn: ({ signal }) => getSnapshot(snapshotId, signal),
    enabled: Boolean(snapshotId),
  });

  // Extract columns from snapshot schema
  const schemaColumns = useMemo<string[]>(() => {
    const def = snapshotQuery.data?.schema_definition;
    if (!def) return [];
    if ("columns" in def && Array.isArray(def.columns)) {
      return def.columns
        .map((c) => {
          if (typeof c === "string") return c;
          if (c && typeof c === "object" && "name" in c && typeof c.name === "string") return c.name;
          return "";
        })
        .filter(Boolean);
    }
    return Object.keys(def);
  }, [snapshotQuery.data]);

  // Query recommendations when snapshot is loaded
  const recommendationsQuery = useQuery({
    queryKey: ["recommendations", session.email(), snapshotId],
    queryFn: () => getRecommendations(snapshotId),
    enabled: Boolean(snapshotId),
  });

  // Query template if templateId is present
  const templateQuery = useQuery({
    queryKey: ["ruleset-template", session.email(), templateId],
    queryFn: () => getRulesetTemplate(templateId),
    enabled: Boolean(templateId),
  });

  // Template placeholders extraction
  const templatePayload = useMemo(
    () => normalizeRulesPayload(templateQuery.data?.rules_payload),
    [templateQuery.data],
  );

  const templatePlaceholders = useMemo(
    () => extractTemplatePlaceholders(templatePayload),
    [templatePayload],
  );

  // Initialize placeholder mapping and prefill name
  useEffect(() => {
    if (templateQuery.data) {
      if (!name.trim()) {
        setName(templateQuery.data.name);
      }
      setPlaceholderMapping((prev) => {
        const next: Record<string, string> = { ...prev };
        for (const p of templatePlaceholders) {
          if (!(p in next)) {
            // Auto match if a schema column name matches placeholder without leading $
            const bare = p.replace(/^\$/, "").toLowerCase();
            const matched = schemaColumns.find((c) => c.toLowerCase() === bare);
            next[p] = matched ?? "";
          }
        }
        return next;
      });
    }
  }, [templateQuery.data, templatePlaceholders, schemaColumns, name]);

  // If snapshot changes, update assetId if snapshot has asset_id
  useEffect(() => {
    if (snapshotQuery.data?.asset_id && !assetId) {
      setAssetId(snapshotQuery.data.asset_id);
    }
  }, [snapshotQuery.data, assetId]);

  // Check unmapped placeholders
  const hasUnmappedPlaceholders = useMemo(() => {
    if (!templateId || templatePlaceholders.length === 0) return false;
    return templatePlaceholders.some((p) => !placeholderMapping[p] || !placeholderMapping[p].trim());
  }, [templateId, templatePlaceholders, placeholderMapping]);

  // Apply template mapping
  const applyTemplate = () => {
    if (hasUnmappedPlaceholders) {
      setShowErrors(true);
      return;
    }
    const instantiated = instantiateTemplateRules(templatePayload, placeholderMapping);
    setRules((prev) => mergeAndDedupeRules(prev, instantiated));
    setTemplateApplied(true);
  };

  // Merge selected recommendations
  const mergeRecommendations = () => {
    if (!recommendationsQuery.data?.rules) return;
    const selectedInputs: QualityRuleInput[] = [];
    for (const item of recommendationsQuery.data.rules) {
      if (selectedRecRules[item.rule.rule_code]) {
        selectedInputs.push(item.rule);
      }
    }
    if (selectedInputs.length > 0) {
      setRules((prev) => mergeAndDedupeRules(prev, selectedInputs));
    }
  };

  // Validation
  const codes = rules.map((r) => r.rule_code.trim()).filter(Boolean);
  const duplicateCodes = codes.length !== new Set(codes).size;
  const rulesValid = rules.every((r) => Object.keys(validateRule(r)).length === 0) && !duplicateCodes;
  const valid =
    isUuid(assetId) &&
    name.trim() !== "" &&
    rules.length > 0 &&
    rulesValid &&
    (!templateId || !hasUnmappedPlaceholders || templateApplied);

  const mutation = useMutation({
    mutationFn: () =>
      createRuleset({
        asset_id: assetId.trim(),
        name: name.trim(),
        rules: rules.map(toRuleInput),
      }),
    onSuccess: (rs) => {
      recent.remember({ kind: "ruleset", id: rs.ruleset_id, label: rs.name, status: rs.status });
      onSaved(rs);
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setShowErrors(true);
    if (valid) mutation.mutate();
  };

  const summary = {
    required: rules.filter((r) => r.is_required).length,
    critical: rules.filter((r) => r.is_critical && !r.is_advisory).length,
    advisory: rules.filter((r) => r.is_advisory).length,
  };

  return (
    <form onSubmit={submit} className="card space-y-6" noValidate>
      <div className="flex items-center justify-between border-b border-border pb-3">
        <h2 className="text-xl font-bold flex items-center gap-2">
          <Layers className="size-5 text-action" aria-hidden />
          {t("gov.rulesets.editor")}
        </h2>
        <span className="text-xs text-fg-muted font-mono">{t("status.DRAFT")}</span>
      </div>

      {/* Asset and Snapshot Selection */}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("gov.rulesets.asset")}>
          {(id) => (
            <>
              <select
                id={id}
                className="input"
                value={assetId}
                aria-invalid={showErrors && !isUuid(assetId)}
                onChange={(e) => {
                  setAssetId(e.target.value);
                  setSnapshotId("");
                }}
              >
                <option value="">{t("gov.rulesets.select_asset")}</option>
                {assetsQuery.data?.items.map((a) => (
                  <option key={a.asset_id} value={a.asset_id}>
                    {a.name}
                  </option>
                ))}
                {/* Fallback to recent if not loaded */}
                {recentAssets
                  .filter((ra) => !assetsQuery.data?.items.some((a) => a.asset_id === ra.id))
                  .map((ra) => (
                    <option key={ra.id} value={ra.id}>
                      {ra.label}
                    </option>
                  ))}
              </select>
            </>
          )}
        </Field>

        <Field label={t("gov.rulesets.snapshot")}>
          {(id) => (
            <select
              id={id}
              className="input"
              value={snapshotId}
              onChange={(e) => setSnapshotId(e.target.value)}
            >
              <option value="">{t("gov.rulesets.select_snapshot")}</option>
              {snapshotsQuery.data?.items.map((s) => (
                <option key={s.snapshot_id} value={s.snapshot_id}>
                  {s.snapshot_id.slice(0, 8)}… ({s.total_rows} rows, {s.total_columns} cols)
                </option>
              ))}
            </select>
          )}
        </Field>

        <Field label={t("gov.rulesets.name")}>
          {(id) => (
            <input
              id={id}
              className="input sm:col-span-2"
              maxLength={255}
              value={name}
              placeholder={t("gov.rulesets.name")}
              aria-invalid={showErrors && !name.trim()}
              onChange={(e) => setName(e.target.value)}
            />
          )}
        </Field>
      </div>

      {/* Template Mapping Block */}
      {templateQuery.data && (
        <div className="rounded-control border border-brand/40 bg-brand/5 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-sm flex items-center gap-2 text-brand">
              <Sparkles className="size-4" aria-hidden />
              {t("gov.template.loaded", { name: templateQuery.data.name })}
            </h3>
            {templateApplied && (
              <span className="flex items-center gap-1 text-xs text-pass font-semibold">
                <Check className="size-3.5" aria-hidden />
                {t("gov.template.mapped_success", { count: templatePayload.length })}
              </span>
            )}
          </div>
          <p className="text-xs text-fg-muted">{t("gov.template.mapping_desc")}</p>

          {templatePlaceholders.length > 0 && (
            <div className="space-y-2 pt-2">
              <p className="text-xs font-semibold uppercase text-fg-muted">
                {t("gov.template.mapping_title")}
              </p>
              <div className="grid gap-2 sm:grid-cols-2">
                {templatePlaceholders.map((ph) => (
                  <div key={ph} className="flex items-center gap-2 text-xs">
                    <span className="mono font-bold text-brand min-w-24">{ph}</span>
                    <span className="text-fg-muted">→</span>
                    <select
                      className="input py-1 text-xs"
                      value={placeholderMapping[ph] ?? ""}
                      onChange={(e) =>
                        setPlaceholderMapping((prev) => ({ ...prev, [ph]: e.target.value }))
                      }
                    >
                      <option value="">{t("gov.template.select_column")}</option>
                      {schemaColumns.map((col) => (
                        <option key={col} value={col}>
                          {col}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>

              {showErrors && hasUnmappedPlaceholders && (
                <p className="text-xs font-medium text-fail">
                  {t("gov.rulesets.unmapped_placeholders")}
                </p>
              )}

              <button
                type="button"
                className="btn-secondary text-xs mt-2"
                disabled={hasUnmappedPlaceholders}
                onClick={applyTemplate}
              >
                {t("gov.template.apply_mapping")}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Snapshot Recommendations Block */}
      {snapshotId && recommendationsQuery.data && recommendationsQuery.data.rules?.length > 0 && (
        <div className="rounded-control border border-border bg-surface-muted/40 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-sm flex items-center gap-2">
              <Lightbulb className="size-4 text-warn" aria-hidden />
              {t("gov.rec.title")}
            </h3>
            <span className="text-xs text-fg-muted">
              {recommendationsQuery.data.rules.length} {t("recommend.rules").toLowerCase()}
            </span>
          </div>
          <p className="text-xs text-fg-muted">{t("gov.rec.disclaimer")}</p>

          <div className="max-h-48 overflow-y-auto space-y-2 border border-border rounded-control p-2 bg-surface">
            {recommendationsQuery.data.rules.map((item) => {
              const checked = !!selectedRecRules[item.rule.rule_code];
              const reasonKey = `reason.${item.reason_code}` as GovernanceKey;
              const reasonText = t(reasonKey) || item.reason_code;
              return (
                <label
                  key={item.rule.rule_code}
                  className="flex items-start gap-2 text-xs p-1.5 rounded hover:bg-surface-muted cursor-pointer"
                >
                  <input
                    type="checkbox"
                    className="size-4 mt-0.5 accent-[var(--action)]"
                    checked={checked}
                    onChange={(e) =>
                      setSelectedRecRules((prev) => ({
                        ...prev,
                        [item.rule.rule_code]: e.target.checked,
                      }))
                    }
                  />
                  <div className="flex-1">
                    <div className="flex items-center gap-2 font-mono">
                      <span className="font-semibold">{item.rule.rule_code}</span>
                      <span className="text-fg-muted">[{item.rule.dimension}]</span>
                      <span>{String(item.rule.parameters?.column ?? "")}</span>
                    </div>
                    <p className="text-[11px] text-fg-muted">
                      {t("gov.rec.reason", { reason: reasonText })}
                    </p>
                  </div>
                </label>
              );
            })}
          </div>

          <div className="flex flex-wrap items-center gap-2 pt-1">
            <button
              type="button"
              className="btn-secondary text-xs"
              onClick={() => {
                const all: Record<string, boolean> = {};
                recommendationsQuery.data?.rules.forEach((r) => {
                  all[r.rule.rule_code] = true;
                });
                setSelectedRecRules(all);
              }}
            >
              {t("gov.rec.select_all")}
            </button>
            <button
              type="button"
              className="btn-secondary text-xs"
              onClick={() => setSelectedRecRules({})}
            >
              {t("gov.rec.deselect_all")}
            </button>
            <button
              type="button"
              className="btn-primary text-xs"
              disabled={!Object.values(selectedRecRules).some(Boolean)}
              onClick={mergeRecommendations}
            >
              {t("gov.rec.merge_selected", {
                count: Object.values(selectedRecRules).filter(Boolean).length,
              })}
            </button>
          </div>
        </div>
      )}

      {/* Rules list */}
      <div className="space-y-4">
        {rules.map((rule, i) => (
          <RuleRow
            key={rule.key}
            index={i}
            rule={rule}
            showErrors={showErrors}
            columns={schemaColumns}
            onChange={(patch) =>
              setRules((rs) => rs.map((r) => (r.key === rule.key ? { ...r, ...patch } : r)))
            }
            onRemove={
              rules.length > 1
                ? () => setRules((rs) => rs.filter((r) => r.key !== rule.key))
                : undefined
            }
          />
        ))}

        <button
          type="button"
          className="btn-secondary"
          onClick={() => setRules((rs) => [...rs, newRule()])}
        >
          <Plus aria-hidden className="size-4" /> {t("gov.rule.add")}
        </button>
      </div>

      {/* Review summary */}
      <div className="rounded-control bg-surface-muted p-4 text-sm" aria-live="polite">
        <p className="font-semibold">{t("gov.rulesets.editor")}</p>
        <p className="text-fg-muted">
          {t("gov.rulesets.review_summary", {
            count: rules.length,
            required: summary.required,
            critical: summary.critical,
            advisory: summary.advisory,
          })}{" "}
          {t("gov.rulesets.review_draft_notice")}
        </p>
        {showErrors && duplicateCodes && (
          <p className="mt-1 font-medium text-fail">{t("gov.rulesets.duplicate_codes")}</p>
        )}
        {showErrors && !valid && !duplicateCodes && (
          <p className="mt-1 font-medium text-fail">{t("gov.rulesets.fix_errors")}</p>
        )}
      </div>

      <ProblemAlert error={mutation.error} />
      {mutation.data && <CreatedRevision ruleset={mutation.data} />}

      <button type="submit" className="btn-primary" disabled={mutation.isPending}>
        <Save aria-hidden className="size-4" />{" "}
        {mutation.isPending ? t("common.loading") : t("btn.save")}
      </button>
    </form>
  );
}

function CreatedRevision({ ruleset }: { ruleset: RulesetResponse }) {
  const { t } = useI18n();
  return (
    <div role="status" className="rounded-control border border-pass/40 bg-pass-bg p-4 space-y-2">
      <p className="flex items-center gap-2 font-semibold text-pass">
        <CheckCircle2 className="size-5" aria-hidden />
        {t("gov.rulesets.saved_draft", { name: ruleset.name })} <GovernanceBadge status={ruleset.status} />
      </p>
      <dl className="text-fg">
        <CopyId label="Ruleset ID" value={ruleset.ruleset_id} />
      </dl>
      <p className="text-sm text-fg">{t("gov.rulesets.next_steps")}</p>
    </div>
  );
}
