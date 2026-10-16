import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, ChevronRight, ListFilter, Save, SlidersHorizontal, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";
import { session } from "../../api/client";
import { createPolicy, getPolicyTemplate, listPolicies } from "../../api/endpoints";
import { DIMENSIONS, type PolicyResponse } from "../../api/types";
import { CopyId } from "../../components/CopyId";
import { Field, PageHeader } from "../../components/Field";
import { ProblemAlert } from "../../components/ProblemAlert";
import { GovernanceBadge } from "../../components/StatusBadge";
import { humanize } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { recent } from "../../lib/recent";
import { ApprovalPanel } from "./ApprovalPanel";

// Form defaults mirror CreatePolicyRequest defaults in presentation/api/schemas/policy_schemas.py.
const DEFAULTS = { fail: "60", warn: "80", coveragePct: "80", weight: "1" };

const inRange = (v: string, lo: number, hi: number) => v.trim() !== "" && Number(v) >= lo && Number(v) <= hi;

export function PoliciesPage() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();

  // List filter state
  const filters = useMemo(
    () => ({
      q: params.get("q") ?? "",
      status: params.get("status") ?? "",
      page: Number(params.get("page") ?? 1),
      page_size: 25,
    }),
    [params],
  );

  const initialTemplateParam = params.get("template") ?? "";

  const [selectedPolicy, setSelectedPolicy] = useState<PolicyResponse | null>(null);

  const updateParam = (key: string, value: string) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value) next.set(key, value);
      else next.delete(key);
      if (key !== "page") next.delete("page");
      return next;
    });
  };

  // Policies query
  const policiesQuery = useQuery({
    queryKey: ["policies", session.email(), filters],
    queryFn: ({ signal }) => listPolicies(filters, signal),
  });

  const serverItems = useMemo(
    () =>
      policiesQuery.data?.items.map((p) => ({
        id: p.policy_id,
        label: p.name,
        status: p.status,
      })) ?? [],
    [policiesQuery.data],
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("gov.policies.title")}
        description={t("gov.policies.subtitle")}
      />

      {/* Persistent List Section */}
      <section className="card space-y-4" aria-labelledby="policies-list-heading">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="policies-list-heading" className="flex items-center gap-2 text-lg font-bold">
            <ListFilter className="size-5 text-action" aria-hidden />
            {t("gov.policies.list")}
          </h2>
          <span className="text-sm text-fg-muted">
            {t("common.count", { count: policiesQuery.data?.total ?? 0 })}
          </span>
        </div>

        {/* Filter bar */}
        <div className="grid gap-3 sm:grid-cols-2">
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

          <Field label={t("gov.policies.filter_status")}>
            {(id) => (
              <select
                id={id}
                className="input"
                value={filters.status}
                onChange={(e) => updateParam("status", e.target.value)}
              >
                <option value="">{t("gov.policies.all_statuses")}</option>
                <option value="PENDING_APPROVAL">{t("status.PENDING_APPROVAL")}</option>
                <option value="ACTIVE">{t("status.ACTIVE")}</option>
                <option value="DRAFT">{t("status.DRAFT")}</option>
              </select>
            )}
          </Field>
        </div>

        <ProblemAlert error={policiesQuery.error} />

        {policiesQuery.isPending ? (
          <p className="py-4 text-center text-fg-muted">{t("common.loading")}</p>
        ) : policiesQuery.data?.items.length === 0 ? (
          <p className="py-4 text-center text-fg-muted">{t("gov.policies.no_policies")}</p>
        ) : (
          <div className="overflow-x-auto rounded-control border border-border">
            <table className="w-full text-left text-sm">
              <thead className="bg-surface-muted text-xs uppercase text-fg-muted border-b border-border">
                <tr>
                  <th className="px-4 py-3">{t("common.name")}</th>
                  <th className="px-4 py-3">{t("common.status")}</th>
                  <th className="px-4 py-3">{t("gov.policies.coverage")}</th>
                  <th className="px-4 py-3">{t("gov.policies.gate_title")}</th>
                  <th className="px-4 py-3">{t("common.created")}</th>
                  <th className="px-4 py-3 text-right"></th>
                </tr>
              </thead>
              <tbody className="divide-y border-border">
                {policiesQuery.data?.items.map((p) => {
                  const isSelected = selectedPolicy?.policy_id === p.policy_id;
                  return (
                    <tr
                      key={p.policy_id}
                      onClick={() => setSelectedPolicy(p)}
                      className={`cursor-pointer transition-colors hover:bg-surface-muted/60 ${
                        isSelected ? "bg-action/10 font-medium" : ""
                      }`}
                    >
                      <td className="px-4 py-3">
                        <div className="font-semibold text-fg">{p.name}</div>
                        <div className="mono text-xs text-fg-muted">v{p.current_version}</div>
                      </td>
                      <td className="px-4 py-3">
                        <GovernanceBadge status={p.status} />
                      </td>
                      <td className="px-4 py-3 font-mono">
                        {(p.min_coverage_threshold * 100).toFixed(0)}%
                      </td>
                      <td className="px-4 py-3 text-xs text-fg-muted">
                        Fail &lt; {p.gate_fail_threshold} · Warn &lt; {p.gate_warn_threshold}
                      </td>
                      <td className="px-4 py-3 text-xs text-fg-muted">
                        {p.created_at ? new Date(p.created_at).toLocaleString() : ""}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          type="button"
                          className="btn-secondary text-xs"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedPolicy(p);
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
              {filters.page} / {Math.ceil((policiesQuery.data?.total ?? 0) / filters.page_size) || 1}
            </span>
            <button
              type="button"
              className="btn-secondary text-xs"
              disabled={filters.page * filters.page_size >= (policiesQuery.data?.total ?? 0)}
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
              updateParam("page", "1");
            }}
          >
            {t("common.reset")}
          </button>
        </div>
      </section>

      {/* Editor & Approval Panel layout */}
      <div className="grid gap-6 2xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] items-start">
        <PolicyEditor
          initialTemplateId={initialTemplateParam}
          onSaved={(newlyCreated) => {
            policiesQuery.refetch();
            setSelectedPolicy(newlyCreated);
          }}
        />

        <ApprovalPanel<PolicyResponse>
          kind="policies"
          recentKind="policy"
          noun="Policy"
          idOf={(p) => p.policy_id}
          selectedEntity={selectedPolicy}
          serverItems={serverItems}
          onActionSuccess={() => policiesQuery.refetch()}
        />
      </div>
    </div>
  );
}

function PolicyEditor({
  initialTemplateId,
  onSaved,
}: {
  initialTemplateId: string;
  onSaved: (policy: PolicyResponse) => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const [fail, setFail] = useState(DEFAULTS.fail);
  const [warn, setWarn] = useState(DEFAULTS.warn);
  const [coveragePct, setCoveragePct] = useState(DEFAULTS.coveragePct);
  const [critical, setCritical] = useState("");
  const [weights, setWeights] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    for (const d of DIMENSIONS) {
      init[d] = DEFAULTS.weight;
    }
    return init;
  });
  const [showErrors, setShowErrors] = useState(false);
  const [templateName, setTemplateName] = useState("");

  // Query template if templateId is present
  const templateQuery = useQuery({
    queryKey: ["policy-template", session.email(), initialTemplateId],
    queryFn: () => getPolicyTemplate(initialTemplateId),
    enabled: Boolean(initialTemplateId),
  });

  // Prefill when template loads
  useEffect(() => {
    if (templateQuery.data) {
      const tmpl = templateQuery.data;
      setTemplateName(tmpl.name);
      if (!name.trim()) setName(tmpl.name);

      const gateRules = tmpl.gate_rules;
      if (gateRules && typeof gateRules === "object") {
        if ("gate_fail_threshold" in gateRules && typeof gateRules.gate_fail_threshold === "number") {
          setFail(String(gateRules.gate_fail_threshold));
        } else if ("warn_min" in gateRules && typeof gateRules.warn_min === "number") {
          setFail(String(gateRules.warn_min));
        }

        if ("gate_warn_threshold" in gateRules && typeof gateRules.gate_warn_threshold === "number") {
          setWarn(String(gateRules.gate_warn_threshold));
        } else if ("pass_min" in gateRules && typeof gateRules.pass_min === "number") {
          setWarn(String(gateRules.pass_min));
        }

        if (
          "critical_acceptance_threshold" in gateRules &&
          gateRules.critical_acceptance_threshold !== null &&
          gateRules.critical_acceptance_threshold !== undefined
        ) {
          setCritical(String(gateRules.critical_acceptance_threshold));
        }
      }

      if (typeof tmpl.publication_threshold === "number") {
        setCoveragePct(String(Math.round(tmpl.publication_threshold * 100)));
      }

      if (tmpl.dimension_weights && typeof tmpl.dimension_weights === "object") {
        const nextWeights: Record<string, string> = {};
        for (const d of DIMENSIONS) {
          if (d in tmpl.dimension_weights) {
            nextWeights[d] = String(tmpl.dimension_weights[d]);
          } else {
            nextWeights[d] = "1";
          }
        }
        setWeights(nextWeights);
      }
    }
  }, [templateQuery.data, name]);

  const errors = {
    name: !name.trim() ? t("gov.err.required") : undefined,
    fail: !inRange(fail, 0, 100) ? t("gov.err.threshold_range") : undefined,
    warn: !inRange(warn, 0, 100)
      ? t("gov.err.threshold_range")
      : Number(warn) < Number(fail)
        ? t("gov.err.warn_ge_fail")
        : undefined,
    coverage: !inRange(coveragePct, 0, 100) ? t("gov.err.threshold_range") : undefined,
    critical: critical !== "" && !inRange(critical, 0, 100) ? t("gov.err.threshold_range") : undefined,
    weights: Object.values(weights).some((w) => !(w.trim() !== "" && Number(w) >= 0))
      ? t("gov.err.weights_ge_zero")
      : undefined,
  };
  const valid = Object.values(errors).every((e) => !e);

  const mutation = useMutation({
    mutationFn: () =>
      createPolicy({
        name: name.trim(),
        gate_fail_threshold: Number(fail),
        gate_warn_threshold: Number(warn),
        min_coverage_threshold: Number(coveragePct) / 100,
        critical_acceptance_threshold: critical === "" ? null : Number(critical),
        dimension_weights: Object.fromEntries(Object.entries(weights).map(([d, w]) => [d, Number(w)])),
      }),
    onSuccess: (p) => {
      recent.remember({ kind: "policy", id: p.policy_id, label: p.name, status: p.status });
      onSaved(p);
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setShowErrors(true);
    if (valid) mutation.mutate();
  };

  const err = (key: keyof typeof errors) => (showErrors ? errors[key] : undefined);
  const numberInput =
    (value: string, set: (v: string) => void, key: keyof typeof errors, unit: string) =>
    (id: string, hint?: string) => (
      <div className="relative">
        <input
          id={id}
          aria-describedby={hint}
          aria-invalid={!!err(key)}
          className="input mono pr-12"
          inputMode="decimal"
          value={value}
          onChange={(e) => set(e.target.value)}
        />
        <span aria-hidden className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-fg-muted">
          {unit}
        </span>
        {err(key) && <p className="mt-1 text-xs font-medium text-fail">{err(key)}</p>}
      </div>
    );

  return (
    <form onSubmit={submit} className="card space-y-6" noValidate>
      <div className="flex items-center justify-between border-b border-border pb-3">
        <h2 className="text-xl font-bold flex items-center gap-2">
          <SlidersHorizontal className="size-5 text-action" aria-hidden />
          {t("gov.policies.editor")}
        </h2>
        <span className="text-xs text-fg-muted font-mono">{t("status.DRAFT")}</span>
      </div>

      {templateName && (
        <div className="rounded-control border border-brand/40 bg-brand/5 p-3 flex items-center gap-2 text-xs text-brand font-medium">
          <Sparkles className="size-4 shrink-0" aria-hidden />
          <span>{t("gov.policies.from_template", { name: templateName })}</span>
        </div>
      )}

      <Field label={t("gov.policies.name")}>
        {(id) => (
          <>
            <input
              id={id}
              className="input"
              maxLength={255}
              value={name}
              placeholder={t("gov.policies.name")}
              aria-invalid={!!err("name")}
              onChange={(e) => setName(e.target.value)}
            />
            {err("name") && <p className="mt-1 text-xs font-medium text-fail">{err("name")}</p>}
          </>
        )}
      </Field>

      <fieldset className="grid gap-4 sm:grid-cols-2">
        <legend className="label sm:col-span-2">{t("gov.policies.gate_title")}</legend>
        <Field label={t("gov.policies.fail_below")} hint={t("gov.policies.fail_hint")}>
          {numberInput(fail, setFail, "fail", "pts")}
        </Field>
        <Field label={t("gov.policies.warn_below")} hint={t("gov.policies.warn_hint")}>
          {numberInput(warn, setWarn, "warn", "pts")}
        </Field>
        <Field label={t("gov.policies.coverage")} hint={t("gov.policies.coverage_hint")}>
          {numberInput(coveragePct, setCoveragePct, "coverage", "%")}
        </Field>
        <Field label={t("gov.policies.critical")} hint={t("gov.policies.critical_hint")}>
          {numberInput(critical, setCritical, "critical", "pts")}
        </Field>
      </fieldset>

      <fieldset>
        <legend className="label">{t("gov.policies.weights_title")}</legend>
        <p className="text-xs text-fg-muted mb-3">{t("gov.policies.weights_hint")}</p>
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-3">
          {DIMENSIONS.map((d) => (
            <Field key={d} label={humanize(d)}>
              {(id) => (
                <input
                  id={id}
                  className="input mono"
                  inputMode="decimal"
                  value={weights[d] ?? "1"}
                  onChange={(e) => setWeights((w) => ({ ...w, [d]: e.target.value }))}
                />
              )}
            </Field>
          ))}
        </div>
        {err("weights") && <p className="mt-1 text-xs font-medium text-fail">{err("weights")}</p>}
      </fieldset>

      <ProblemAlert error={mutation.error} />
      {mutation.data && <CreatedPolicy policy={mutation.data} />}

      <button type="submit" className="btn-primary" disabled={mutation.isPending}>
        <Save aria-hidden className="size-4" />{" "}
        {mutation.isPending ? t("common.loading") : t("btn.save")}
      </button>
    </form>
  );
}

function CreatedPolicy({ policy }: { policy: PolicyResponse }) {
  const { t } = useI18n();
  return (
    <div role="status" className="rounded-control border border-pass/40 bg-pass-bg p-4 space-y-2">
      <p className="flex items-center gap-2 font-semibold text-pass">
        <CheckCircle2 className="size-5" aria-hidden />
        {t("gov.policies.saved_draft", { name: policy.name })} <GovernanceBadge status={policy.status} />
      </p>
      <dl className="text-fg">
        <CopyId label="Policy ID" value={policy.policy_id} />
      </dl>
    </div>
  );
}
