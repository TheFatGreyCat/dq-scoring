import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  Lightbulb,
  ListChecks,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { session } from "../../api/client";
import {
  getPolicyTemplates,
  getRecommendations,
  getRuleCatalogTemplates,
  getRulesetTemplates,
  getTemplateOverview,
  listSnapshots,
} from "../../api/endpoints";
import { DIMENSIONS, type RulesetTemplate, type ScoringPolicyTemplate } from "../../api/types";
import { Field, PageHeader } from "../../components/Field";
import { ProblemAlert } from "../../components/ProblemAlert";
import { humanize } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import type { GovernanceKey } from "../../lib/governanceTranslations";
import { normalizeRulesPayload } from "../governance/ruleForm";

type TabType = "rulesets" | "rules" | "policies" | "survey";

const DOMAIN_OPTIONS = ["ALL", "FINANCE", "RETAIL", "TRANSPORTATION", "HEALTHCARE", "GENERAL"] as const;
const SURVEY_DOMAINS = ["FINANCE", "RETAIL", "TRANSPORTATION", "HEALTHCARE", "GENERAL"] as const;

export function TemplateCatalogPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();

  const activeTab = (params.get("tab") as TabType) || "rulesets";
  const snapshotFromUrl = params.get("snapshot") ?? "";

  const setActiveTab = (tab: TabType) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("tab", tab);
      return next;
    });
  };

  // Overview stats
  const overviewQuery = useQuery({
    queryKey: ["templates", "overview", session.email()],
    queryFn: ({ signal }) => getTemplateOverview(signal),
  });

  // Tab 1: Rulesets filters
  const rulesetFilters = useMemo(
    () => ({
      q: params.get("rs_q") ?? "",
      domain: params.get("rs_domain") && params.get("rs_domain") !== "ALL" ? params.get("rs_domain")! : undefined,
      data_type: params.get("rs_type") ?? undefined,
      page: Number(params.get("rs_page") ?? 1),
      page_size: 20,
    }),
    [params],
  );

  const rulesetsQuery = useQuery({
    queryKey: ["templates", "rulesets", session.email(), rulesetFilters],
    queryFn: ({ signal }) => getRulesetTemplates(rulesetFilters, signal),
    enabled: activeTab === "rulesets",
  });

  // Tab 2: Rules filters
  const ruleFilters = useMemo(
    () => ({
      q: params.get("r_q") ?? "",
      rule_type: params.get("r_type") ?? undefined,
      dimension: params.get("r_dim") ?? undefined,
      page: Number(params.get("r_page") ?? 1),
      page_size: 20,
    }),
    [params],
  );

  const rulesQuery = useQuery({
    queryKey: ["templates", "rules", session.email(), ruleFilters],
    queryFn: ({ signal }) => getRuleCatalogTemplates(ruleFilters, signal),
    enabled: activeTab === "rules",
  });

  // Tab 3: Policies filters
  const policyFilters = useMemo(
    () => ({
      q: params.get("p_q") ?? "",
      domain: params.get("p_domain") && params.get("p_domain") !== "ALL" ? params.get("p_domain")! : undefined,
      page: Number(params.get("p_page") ?? 1),
      page_size: 20,
    }),
    [params],
  );

  const policiesQuery = useQuery({
    queryKey: ["templates", "policies", session.email(), policyFilters],
    queryFn: ({ signal }) => getPolicyTemplates(policyFilters, signal),
    enabled: activeTab === "policies",
  });

  // Tab 4: Survey Wizard state
  const [surveySnapshotId, setSurveySnapshotId] = useState<string>(snapshotFromUrl);
  const [surveyDomain, setSurveyDomain] = useState<string>("FINANCE");
  const [selectedPriorities, setSelectedPriorities] = useState<string[]>([
    "COMPLETENESS",
    "VALIDITY",
    "UNIQUENESS",
  ]);
  const [surveySubmitted, setSurveySubmitted] = useState<boolean>(Boolean(snapshotFromUrl));

  // Snapshots query for survey picker
  const snapshotsQuery = useQuery({
    queryKey: ["snapshots", session.email(), { page_size: 100 }],
    queryFn: ({ signal }) => listSnapshots({ page_size: 100 }, signal),
  });

  // Survey recommendations query
  const recommendationsQuery = useQuery({
    queryKey: [
      "recommendations",
      session.email(),
      surveySnapshotId,
      surveyDomain,
      selectedPriorities.join(","),
    ],
    queryFn: () =>
      getRecommendations(surveySnapshotId, {
        domain: surveyDomain,
        priorities: selectedPriorities.join(","),
      }),
    enabled: Boolean(surveySnapshotId) && surveySubmitted,
  });

  const togglePriority = (dim: string) => {
    setSelectedPriorities((prev) =>
      prev.includes(dim) ? prev.filter((p) => p !== dim) : [...prev, dim],
    );
  };

  const handleApplyRuleset = (rs: RulesetTemplate) => {
    if (surveySnapshotId) {
      navigate(`/rulesets?snapshot=${encodeURIComponent(surveySnapshotId)}&template=${encodeURIComponent(rs.template_id)}`);
    } else {
      navigate(`/rulesets?template=${encodeURIComponent(rs.template_id)}`);
    }
  };

  const handleApplyPolicy = (pol: ScoringPolicyTemplate) => {
    navigate(`/policies?template=${encodeURIComponent(pol.template_id)}`);
  };

  const updateParam = (key: string, value: string) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value) next.set(key, value);
      else next.delete(key);
      return next;
    });
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <PageHeader
          title={t("templates.title")}
          description={t("templates.subtitle")}
        />
        <button
          type="button"
          onClick={() => setActiveTab("survey")}
          className="btn-primary inline-flex items-center gap-2 self-start cursor-pointer shadow-xs"
        >
          <Sparkles className="size-4" aria-hidden />
          <span>{t("templates.wizard.btn")}</span>
        </button>
      </div>

      {/* Overview Stat Cards */}
      {overviewQuery.data && (
        <div className="grid gap-3 sm:grid-cols-4">
          <div className="card py-3 space-y-1">
            <span className="text-xs font-semibold text-fg-muted uppercase">
              {t("templates.tab.rules")}
            </span>
            <p className="text-2xl font-bold text-brand">{overviewQuery.data.total_rule_templates}</p>
          </div>
          <div className="card py-3 space-y-1">
            <span className="text-xs font-semibold text-fg-muted uppercase">
              {t("templates.tab.rulesets")}
            </span>
            <p className="text-2xl font-bold text-blue-600 dark:text-blue-400">
              {overviewQuery.data.total_ruleset_templates}
            </p>
          </div>
          <div className="card py-3 space-y-1">
            <span className="text-xs font-semibold text-fg-muted uppercase">
              {t("templates.tab.policies")}
            </span>
            <p className="text-2xl font-bold text-emerald-600 dark:text-emerald-400">
              {overviewQuery.data.total_policy_templates}
            </p>
          </div>
          <div className="card py-3 space-y-1">
            <span className="text-xs font-semibold text-fg-muted uppercase">
              {t("templates.filter.domain")}
            </span>
            <p className="text-2xl font-bold text-purple-600 dark:text-purple-400">
              {overviewQuery.data.supported_domains.length}
            </p>
          </div>
        </div>
      )}

      {/* Tabs Switcher */}
      <div className="flex items-center gap-2 border-b border-border overflow-x-auto pb-px">
        <button
          type="button"
          onClick={() => setActiveTab("rulesets")}
          className={`flex items-center gap-2 px-4 py-2.5 font-medium text-sm border-b-2 transition-colors cursor-pointer ${
            activeTab === "rulesets"
              ? "border-brand text-brand font-semibold"
              : "border-transparent text-fg-muted hover:text-fg"
          }`}
        >
          <ListChecks className="size-4" aria-hidden />
          <span>{t("templates.tab.rulesets")}</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("rules")}
          className={`flex items-center gap-2 px-4 py-2.5 font-medium text-sm border-b-2 transition-colors cursor-pointer ${
            activeTab === "rules"
              ? "border-brand text-brand font-semibold"
              : "border-transparent text-fg-muted hover:text-fg"
          }`}
        >
          <BookOpen className="size-4" aria-hidden />
          <span>{t("templates.tab.rules")}</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("policies")}
          className={`flex items-center gap-2 px-4 py-2.5 font-medium text-sm border-b-2 transition-colors cursor-pointer ${
            activeTab === "policies"
              ? "border-brand text-brand font-semibold"
              : "border-transparent text-fg-muted hover:text-fg"
          }`}
        >
          <SlidersHorizontal className="size-4" aria-hidden />
          <span>{t("templates.tab.policies")}</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("survey")}
          className={`flex items-center gap-2 px-4 py-2.5 font-medium text-sm border-b-2 transition-colors cursor-pointer ${
            activeTab === "survey"
              ? "border-brand text-brand font-semibold"
              : "border-transparent text-fg-muted hover:text-fg"
          }`}
        >
          <Sparkles className="size-4 text-brand" aria-hidden />
          <span>{t("templates.wizard.title")}</span>
        </button>
      </div>

      {/* Tab 1: Rulesets Templates */}
      {activeTab === "rulesets" && (
        <div className="space-y-4">
          <div className="card space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label={t("common.search")}>
                {(id) => (
                  <input
                    id={id}
                    className="input"
                    placeholder={t("common.search")}
                    value={params.get("rs_q") ?? ""}
                    onChange={(e) => updateParam("rs_q", e.target.value)}
                  />
                )}
              </Field>

              <Field label={t("templates.filter.domain")}>
                {(id) => (
                  <select
                    id={id}
                    className="input"
                    value={params.get("rs_domain") ?? "ALL"}
                    onChange={(e) => updateParam("rs_domain", e.target.value)}
                  >
                    {DOMAIN_OPTIONS.map((d) => (
                      <option key={d} value={d}>
                        {d === "ALL" ? t("common.all") : humanize(d)}
                      </option>
                    ))}
                  </select>
                )}
              </Field>

              <Field label={t("templates.filter.data_type")}>
                {(id) => (
                  <input
                    id={id}
                    className="input"
                    placeholder="TRANSACTION_EVENT, MASTER_DATA…"
                    value={params.get("rs_type") ?? ""}
                    onChange={(e) => updateParam("rs_type", e.target.value)}
                  />
                )}
              </Field>
            </div>
          </div>

          <ProblemAlert error={rulesetsQuery.error} />

          {rulesetsQuery.isPending ? (
            <div className="card py-8 text-center text-fg-muted">{t("common.loading")}</div>
          ) : rulesetsQuery.data?.items.length === 0 ? (
            <div className="card py-8 text-center text-fg-muted">{t("common.empty")}</div>
          ) : (
            <div className="grid gap-6 md:grid-cols-2">
              {rulesetsQuery.data?.items.map((rs) => {
                const rulesInPayload = normalizeRulesPayload(rs.rules_payload);
                return (
                  <div
                    key={rs.template_id}
                    className="card space-y-4 flex flex-col justify-between hover:border-brand/50 transition-colors"
                  >
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-brand/10 text-brand border border-brand/20">
                          {rs.domain}
                        </span>
                        <span className="mono text-xs text-fg-muted">{rs.data_type}</span>
                      </div>
                      <h3 className="font-bold text-lg">{rs.name}</h3>
                      <p className="text-sm text-fg-muted">{rs.description || rs.target_use_case}</p>

                      <div className="pt-2">
                        <span className="text-xs font-semibold uppercase text-fg-muted block mb-1">
                          {t("templates.rules_in_template", { count: rulesInPayload.length })}
                        </span>
                        <ul className="space-y-1 text-xs">
                          {rulesInPayload.map((r, idx) => (
                            <li
                              key={idx}
                              className="flex items-center justify-between p-1.5 rounded bg-surface-muted font-mono"
                            >
                              <span className="font-semibold text-brand">
                                {String(r.rule_code ?? `rule_${idx + 1}`)}
                              </span>
                              <span className="text-fg-muted">
                                [{String(r.dimension ?? "")}] - {String(r.rule_type ?? "")}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    </div>

                    <div className="pt-3 border-t border-border flex items-center justify-between">
                      <span className="text-xs text-fg-muted font-mono">{rs.template_code}</span>
                      <button
                        type="button"
                        onClick={() => handleApplyRuleset(rs)}
                        className="btn-secondary text-xs inline-flex items-center gap-1 cursor-pointer"
                      >
                        {t("templates.apply.ruleset")} <ArrowRight className="size-3.5" aria-hidden />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Pagination */}
          <div className="flex items-center justify-between pt-2">
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="btn-secondary text-xs"
                disabled={rulesetFilters.page <= 1}
                onClick={() => updateParam("rs_page", String(rulesetFilters.page - 1))}
              >
                {t("common.previous")}
              </button>
              <span className="text-xs text-fg-muted">
                {rulesetFilters.page} /{" "}
                {Math.ceil((rulesetsQuery.data?.total ?? 0) / rulesetFilters.page_size) || 1}
              </span>
              <button
                type="button"
                className="btn-secondary text-xs"
                disabled={rulesetFilters.page * rulesetFilters.page_size >= (rulesetsQuery.data?.total ?? 0)}
                onClick={() => updateParam("rs_page", String(rulesetFilters.page + 1))}
              >
                {t("common.next")}
              </button>
            </div>
            <span className="text-xs text-fg-muted">
              {t("common.count", { count: rulesetsQuery.data?.total ?? 0 })}
            </span>
          </div>
        </div>
      )}

      {/* Tab 2: Rule Catalog Templates */}
      {activeTab === "rules" && (
        <div className="space-y-4">
          <div className="card space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label={t("common.search")}>
                {(id) => (
                  <input
                    id={id}
                    className="input"
                    placeholder={t("common.search")}
                    value={params.get("r_q") ?? ""}
                    onChange={(e) => updateParam("r_q", e.target.value)}
                  />
                )}
              </Field>

              <Field label={t("templates.filter.dimension")}>
                {(id) => (
                  <select
                    id={id}
                    className="input"
                    value={params.get("r_dim") ?? ""}
                    onChange={(e) => updateParam("r_dim", e.target.value)}
                  >
                    <option value="">{t("common.all")}</option>
                    {DIMENSIONS.map((d) => (
                      <option key={d} value={d}>
                        {humanize(d)}
                      </option>
                    ))}
                  </select>
                )}
              </Field>

              <Field label={t("templates.filter.rule_type")}>
                {(id) => (
                  <input
                    id={id}
                    className="input"
                    placeholder="NON_NULL, DOMAIN_RANGE…"
                    value={params.get("r_type") ?? ""}
                    onChange={(e) => updateParam("r_type", e.target.value)}
                  />
                )}
              </Field>
            </div>
          </div>

          <ProblemAlert error={rulesQuery.error} />

          {rulesQuery.isPending ? (
            <div className="card py-8 text-center text-fg-muted">{t("common.loading")}</div>
          ) : rulesQuery.data?.items.length === 0 ? (
            <div className="card py-8 text-center text-fg-muted">{t("common.empty")}</div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {rulesQuery.data?.items.map((r) => (
                <div key={r.template_id} className="card space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="mono text-xs font-semibold px-2 py-0.5 rounded bg-action/10 text-action">
                      {r.default_dimension}
                    </span>
                    <span className="mono text-xs text-fg-muted">{r.rule_type}</span>
                  </div>
                  <div>
                    <h3 className="font-bold text-base">{r.name}</h3>
                    <p className="mono text-xs text-fg-muted mt-0.5">{r.template_code}</p>
                  </div>
                  <div className="text-xs text-fg-muted space-y-1 pt-2 border-t border-border">
                    <div>
                      {t("gov.rule.null_policy")}:{" "}
                      <span className="font-mono font-medium">{r.default_null_policy}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Pagination */}
          <div className="flex items-center justify-between pt-2">
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="btn-secondary text-xs"
                disabled={ruleFilters.page <= 1}
                onClick={() => updateParam("r_page", String(ruleFilters.page - 1))}
              >
                {t("common.previous")}
              </button>
              <span className="text-xs text-fg-muted">
                {ruleFilters.page} /{" "}
                {Math.ceil((rulesQuery.data?.total ?? 0) / ruleFilters.page_size) || 1}
              </span>
              <button
                type="button"
                className="btn-secondary text-xs"
                disabled={ruleFilters.page * ruleFilters.page_size >= (rulesQuery.data?.total ?? 0)}
                onClick={() => updateParam("r_page", String(ruleFilters.page + 1))}
              >
                {t("common.next")}
              </button>
            </div>
            <span className="text-xs text-fg-muted">
              {t("common.count", { count: rulesQuery.data?.total ?? 0 })}
            </span>
          </div>
        </div>
      )}

      {/* Tab 3: Scoring Policy Templates */}
      {activeTab === "policies" && (
        <div className="space-y-4">
          <div className="card space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("common.search")}>
                {(id) => (
                  <input
                    id={id}
                    className="input"
                    placeholder={t("common.search")}
                    value={params.get("p_q") ?? ""}
                    onChange={(e) => updateParam("p_q", e.target.value)}
                  />
                )}
              </Field>

              <Field label={t("templates.filter.domain")}>
                {(id) => (
                  <select
                    id={id}
                    className="input"
                    value={params.get("p_domain") ?? "ALL"}
                    onChange={(e) => updateParam("p_domain", e.target.value)}
                  >
                    {DOMAIN_OPTIONS.map((d) => (
                      <option key={d} value={d}>
                        {d === "ALL" ? t("common.all") : humanize(d)}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
            </div>
          </div>

          <ProblemAlert error={policiesQuery.error} />

          {policiesQuery.isPending ? (
            <div className="card py-8 text-center text-fg-muted">{t("common.loading")}</div>
          ) : policiesQuery.data?.items.length === 0 ? (
            <div className="card py-8 text-center text-fg-muted">{t("common.empty")}</div>
          ) : (
            <div className="grid gap-6 md:grid-cols-2">
              {policiesQuery.data?.items.map((pol) => (
                <div key={pol.template_id} className="card space-y-4 flex flex-col justify-between">
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
                        {pol.domain}
                      </span>
                      <span className="text-xs font-bold text-brand">
                        {t("templates.pub_threshold", {
                          pct: Math.round(pol.publication_threshold * 100),
                        })}
                      </span>
                    </div>

                    <div>
                      <h3 className="font-bold text-lg">{pol.name}</h3>
                      <p className="text-sm text-fg-muted mt-1">
                        {pol.description || pol.target_use_case}
                      </p>
                    </div>

                    <div className="space-y-2 pt-2 border-t border-border">
                      <span className="text-xs font-semibold uppercase text-fg-muted block">
                        {t("templates.weights_in_policy")}
                      </span>
                      <div className="grid grid-cols-2 gap-2 text-xs">
                        {Object.entries(pol.dimension_weights).map(([dim, weight]) => (
                          <div
                            key={dim}
                            className="flex justify-between p-1.5 rounded bg-surface-muted font-mono"
                          >
                            <span>{dim}</span>
                            <span className="font-bold text-brand">{weight}x</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="pt-3 border-t border-border flex items-center justify-between">
                    <span className="text-xs text-fg-muted font-mono">{pol.template_code}</span>
                    <button
                      type="button"
                      onClick={() => handleApplyPolicy(pol)}
                      className="btn-secondary text-xs inline-flex items-center gap-1 cursor-pointer"
                    >
                      {t("templates.apply.policy")} <ArrowRight className="size-3.5" aria-hidden />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Pagination */}
          <div className="flex items-center justify-between pt-2">
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="btn-secondary text-xs"
                disabled={policyFilters.page <= 1}
                onClick={() => updateParam("p_page", String(policyFilters.page - 1))}
              >
                {t("common.previous")}
              </button>
              <span className="text-xs text-fg-muted">
                {policyFilters.page} /{" "}
                {Math.ceil((policiesQuery.data?.total ?? 0) / policyFilters.page_size) || 1}
              </span>
              <button
                type="button"
                className="btn-secondary text-xs"
                disabled={policyFilters.page * policyFilters.page_size >= (policiesQuery.data?.total ?? 0)}
                onClick={() => updateParam("p_page", String(policyFilters.page + 1))}
              >
                {t("common.next")}
              </button>
            </div>
            <span className="text-xs text-fg-muted">
              {t("common.count", { count: policiesQuery.data?.total ?? 0 })}
            </span>
          </div>
        </div>
      )}

      {/* Tab 4: Smart Onboarding & Survey Wizard */}
      {activeTab === "survey" && (
        <div className="card space-y-6 max-w-3xl mx-auto border-brand/40 shadow-sm">
          <div className="flex items-center gap-3 border-b border-border pb-4">
            <div className="size-10 rounded-full bg-brand/10 grid place-items-center text-brand">
              <Sparkles className="size-5" aria-hidden />
            </div>
            <div>
              <h2 className="text-xl font-bold">{t("templates.wizard.title")}</h2>
              <p className="text-sm text-fg-muted">{t("templates.wizard.desc")}</p>
            </div>
          </div>

          {/* Step 1: Select Snapshot & Domain */}
          <div className="space-y-4">
            <label className="font-bold text-sm flex items-center gap-2">
              <span className="size-5 rounded-full bg-brand text-white text-xs grid place-items-center">
                1
              </span>
              {t("templates.survey.select_snapshot")}
            </label>

            <Field
              label={t("gov.rulesets.snapshot")}
              hint={t("templates.survey.snapshot_hint")}
            >
              {(id) => (
                <select
                  id={id}
                  className="input"
                  value={surveySnapshotId}
                  onChange={(e) => {
                    setSurveySnapshotId(e.target.value);
                    setSurveySubmitted(false);
                  }}
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

            <div className="space-y-2">
              <span className="text-xs font-semibold uppercase text-fg-muted">
                {t("templates.wizard.step1")}
              </span>
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
                {SURVEY_DOMAINS.map((dom) => (
                  <button
                    key={dom}
                    type="button"
                    onClick={() => {
                      setSurveyDomain(dom);
                      setSurveySubmitted(false);
                    }}
                    className={`p-3 rounded-control border text-left cursor-pointer transition-colors ${
                      surveyDomain === dom
                        ? "border-brand bg-brand/10 text-brand font-semibold shadow-xs"
                        : "border-border hover:bg-surface-muted"
                    }`}
                  >
                    <span className="text-xs font-medium block">{humanize(dom)}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Step 2: Quality Priorities */}
          <div className="space-y-3 pt-4 border-t border-border">
            <label className="font-bold text-sm flex items-center gap-2">
              <span className="size-5 rounded-full bg-brand text-white text-xs grid place-items-center">
                2
              </span>
              {t("templates.wizard.step2")}
            </label>
            <div className="grid sm:grid-cols-3 gap-2 text-xs">
              {DIMENSIONS.map((dim) => {
                const checked = selectedPriorities.includes(dim);
                return (
                  <button
                    key={dim}
                    type="button"
                    onClick={() => {
                      togglePriority(dim);
                      setSurveySubmitted(false);
                    }}
                    className={`p-3 rounded-control border text-left cursor-pointer transition-colors flex items-start gap-2.5 ${
                      checked
                        ? "border-brand bg-brand/5 text-fg font-medium"
                        : "border-border hover:bg-surface-muted text-fg-muted"
                    }`}
                  >
                    <div
                      className={`size-4 rounded-sm border grid place-items-center shrink-0 mt-0.5 ${
                        checked ? "bg-brand border-brand text-white" : "border-border"
                      }`}
                    >
                      {checked && <CheckCircle2 className="size-3" />}
                    </div>
                    <div>
                      <p className="font-semibold text-sm text-fg">{humanize(dim)}</p>
                    </div>
                  </button>
                );
              })}
            </div>

            <div className="pt-2">
              <button
                type="button"
                disabled={!surveySnapshotId || selectedPriorities.length === 0}
                onClick={() => setSurveySubmitted(true)}
                className="btn-primary text-xs inline-flex items-center gap-1.5"
              >
                <Sparkles className="size-4" aria-hidden />
                {t("templates.survey.run_survey")}
              </button>
            </div>
          </div>

          {/* Step 3: Backend Survey Recommendation Results */}
          {surveySubmitted && (
            <div className="space-y-4 pt-4 border-t border-border">
              <label className="font-bold text-sm flex items-center gap-2">
                <span className="size-5 rounded-full bg-emerald-600 text-white text-xs grid place-items-center">
                  3
                </span>
                {t("templates.survey.results_title")}
              </label>

              <ProblemAlert error={recommendationsQuery.error} />

              {recommendationsQuery.isPending && (
                <p className="text-sm text-fg-muted py-4 text-center">{t("common.loading")}</p>
              )}

              {recommendationsQuery.data && (
                <div className="space-y-5">
                  {/* Recommended Generated Rules */}
                  {recommendationsQuery.data.rules?.length > 0 && (
                    <div className="p-4 rounded-control bg-emerald-500/10 border border-emerald-500/20 space-y-3">
                      <div className="flex items-center justify-between text-emerald-800 dark:text-emerald-300 font-semibold">
                        <div className="flex items-center gap-2">
                          <Lightbulb className="size-5" aria-hidden />
                          <span>
                            {t("templates.survey.recommended_rules", {
                              count: recommendationsQuery.data.rules.length,
                            })}
                          </span>
                        </div>
                        <button
                          type="button"
                          onClick={() =>
                            navigate(`/rulesets?snapshot=${encodeURIComponent(surveySnapshotId)}`)
                          }
                          className="btn-primary text-xs inline-flex items-center gap-1 cursor-pointer shadow-xs"
                        >
                          {t("templates.survey.custom_rules_action", {
                            count: recommendationsQuery.data.rules.length,
                          })}
                          <ChevronRight className="size-3.5" aria-hidden />
                        </button>
                      </div>

                      <div className="max-h-36 overflow-y-auto space-y-1.5 text-xs">
                        {recommendationsQuery.data.rules.slice(0, 8).map((r) => {
                          const reasonKey = `reason.${r.reason_code}` as GovernanceKey;
                          const reasonText = t(reasonKey) || r.reason_code;
                          return (
                            <div
                              key={r.rule.rule_code}
                              className="p-1.5 rounded bg-surface/80 flex items-center justify-between font-mono"
                            >
                              <span>
                                {r.rule.rule_code} [{r.rule.dimension}] ({String(r.rule.parameters?.column ?? "")})
                              </span>
                              <span className="text-fg-muted font-sans text-[11px]">{reasonText}</span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* Matching Ruleset Templates */}
                  {recommendationsQuery.data.ruleset_templates?.length > 0 && (
                    <div className="space-y-3">
                      <h4 className="font-semibold text-sm">
                        {t("templates.survey.recommended_rulesets", {
                          count: recommendationsQuery.data.ruleset_templates.length,
                        })}
                      </h4>
                      <div className="grid gap-3 sm:grid-cols-2">
                        {recommendationsQuery.data.ruleset_templates.map((rt) => (
                          <div
                            key={rt.template_id}
                            className="p-3 rounded-control border border-border bg-surface space-y-2 text-xs"
                          >
                            <div className="flex justify-between items-center">
                              <span className="font-mono text-fg-muted text-[11px]">
                                {rt.template_id.slice(0, 8)}…
                              </span>
                              <span className="font-bold text-brand">
                                {t("templates.survey.score_match", {
                                  pct: Math.round(rt.score * 100),
                                })}
                              </span>
                            </div>
                            {rt.matched_columns.length > 0 && (
                              <p className="text-fg-muted">
                                {t("templates.survey.matched_cols", {
                                  cols: rt.matched_columns.join(", "),
                                })}
                              </p>
                            )}
                            {rt.missing_columns.length > 0 && (
                              <p className="text-fail">
                                {t("templates.survey.missing_cols", {
                                  cols: rt.missing_columns.join(", "),
                                })}
                              </p>
                            )}
                            <button
                              type="button"
                              onClick={() =>
                                navigate(
                                  `/rulesets?snapshot=${encodeURIComponent(surveySnapshotId)}&template=${encodeURIComponent(rt.template_id)}`,
                                )
                              }
                              className="btn-secondary text-xs w-full justify-center"
                            >
                              {t("templates.survey.apply_ruleset_action")}{" "}
                              <ArrowRight className="size-3.5" aria-hidden />
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Matching Policy Templates */}
                  {recommendationsQuery.data.policy_templates?.length > 0 && (
                    <div className="space-y-3">
                      <h4 className="font-semibold text-sm">
                        {t("templates.survey.recommended_policies", {
                          count: recommendationsQuery.data.policy_templates.length,
                        })}
                      </h4>
                      <div className="grid gap-3 sm:grid-cols-2">
                        {recommendationsQuery.data.policy_templates.map((pt) => (
                          <div
                            key={pt.template_id}
                            className="p-3 rounded-control border border-border bg-surface space-y-2 text-xs"
                          >
                            <div className="flex justify-between items-center">
                              <span className="font-mono text-fg-muted text-[11px]">
                                {pt.template_id.slice(0, 8)}…
                              </span>
                              <span className="text-fg-muted">{t(`reason.${pt.reason_code}` as GovernanceKey)}</span>
                            </div>
                            <button
                              type="button"
                              onClick={() =>
                                navigate(
                                  `/policies?template=${encodeURIComponent(pt.template_id)}`,
                                )
                              }
                              className="btn-secondary text-xs w-full justify-center"
                            >
                              {t("templates.survey.apply_policy_action")}{" "}
                              <ArrowRight className="size-3.5" aria-hidden />
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
