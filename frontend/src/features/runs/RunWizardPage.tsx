import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { ApiError, session } from "../../api/client";
import { getSnapshot, listAssets, listPolicies, listRulesets, listSnapshots, triggerRun } from "../../api/endpoints";
import { Field, PageHeader } from "../../components/Field";
import { ProblemAlert } from "../../components/ProblemAlert";
import { useI18n } from "../../lib/i18n";

export function RunWizardPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [assetId, setAssetId] = useState("");
  const [snapshotId, setSnapshotId] = useState(params.get("snapshot") ?? "");
  const [rulesetId, setRulesetId] = useState("");
  const [policyId, setPolicyId] = useState("");
  const [outliers, setOutliers] = useState<string[]>([]);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const assets = useQuery({ queryKey: ["run-assets", session.email()], queryFn: ({ signal }) => listAssets({ page_size: 100 }, signal) });
  const snapshots = useQuery({ queryKey: ["run-snapshots", session.email(), assetId], queryFn: ({ signal }) => listSnapshots({ asset_id: assetId, page_size: 100 }, signal) });
  const snapshot = useQuery({ queryKey: ["snapshot", session.email(), snapshotId], queryFn: ({ signal }) => getSnapshot(snapshotId, signal), enabled: !!snapshotId });
  const rulesets = useQuery({ queryKey: ["run-rulesets", session.email(), snapshot.data?.asset_id], queryFn: ({ signal }) => listRulesets({ status: "ACTIVE", asset_id: snapshot.data?.asset_id, page_size: 100 }, signal), enabled: !!snapshot.data });
  const policies = useQuery({ queryKey: ["run-policies", session.email()], queryFn: ({ signal }) => listPolicies({ status: "ACTIVE", page_size: 100 }, signal) });
  const columns = ((snapshot.data?.schema_definition.columns ?? []) as ({name: string} | string)[]).map(c => typeof c === "string" ? c : c.name);
  const mutation = useMutation({ mutationFn: () => triggerRun({ snapshot_id: snapshotId, ruleset_id: rulesetId, policy_id: policyId, execution_profile: "standard", outlier_columns: outliers, idempotency_key: key }), onSuccess: run => navigate(`/runs/${run.run_id}`) });
  const reset = () => { setKey(crypto.randomUUID()); mutation.reset(); };
  const submit = (event: FormEvent) => { event.preventDefault(); if (snapshotId && rulesetId && policyId && !mutation.isPending) mutation.mutate(); };
  const unknown = mutation.error instanceof ApiError && mutation.error.kind !== "http";
  return <><PageHeader title={t("recommend.run")} description={t("run.active_required")} />
    <form className="card space-y-4" onSubmit={submit}>
      <Field label={t("nav.assets")}>{id => <select id={id} className="input" value={assetId} onChange={e => { setAssetId(e.target.value); setSnapshotId(""); setRulesetId(""); reset(); }}><option value="">{t("common.all")}</option>{assets.data?.items.map(a => <option value={a.asset_id} key={a.asset_id}>{a.name}</option>)}</select>}</Field>
      <Field label={t("run.snapshot")}>{id => <select id={id} className="input" required value={snapshotId} onChange={e => { setSnapshotId(e.target.value); setRulesetId(""); reset(); }}><option value="">{t("btn.open")}</option>{snapshotId && !snapshots.data?.items.some(s => s.snapshot_id === snapshotId) && <option value={snapshotId}>{snapshotId}</option>}{snapshots.data?.items.map(s => <option key={s.snapshot_id} value={s.snapshot_id}>{s.snapshot_id.slice(0, 8)} · {s.total_rows}</option>)}</select>}</Field>
      <Field label={t("nav.rulesets")}>{id => <select id={id} className="input" required value={rulesetId} onChange={e => { setRulesetId(e.target.value); reset(); }}><option value="">{t("status.ACTIVE")}</option>{rulesets.data?.items.map(r => <option key={r.ruleset_id} value={r.ruleset_id}>{r.name}</option>)}</select>}</Field>
      <Field label={t("nav.policies")}>{id => <select id={id} className="input" required value={policyId} onChange={e => { setPolicyId(e.target.value); reset(); }}><option value="">{t("status.ACTIVE")}</option>{policies.data?.items.map(p => <option key={p.policy_id} value={p.policy_id}>{p.name}</option>)}</select>}</Field>
      <fieldset><legend>{t("run.outliers")}</legend><p className="text-sm text-fg-muted">{t("run.advisory")}</p><div className="flex flex-wrap gap-3">{columns.map(name => <label key={name}><input type="checkbox" checked={outliers.includes(name)} onChange={e => { setOutliers(values => e.target.checked ? [...values, name] : values.filter(v => v !== name)); reset(); }} /> {name}</label>)}</div></fieldset>
      <ProblemAlert error={mutation.error ?? assets.error ?? snapshots.error ?? rulesets.error ?? policies.error} />
      {unknown && <p role="alert">{t("run.unknown")}</p>}
      <button className="btn-primary" disabled={!snapshotId || !rulesetId || !policyId || mutation.isPending}>{mutation.isPending ? t("common.loading") : unknown ? t("common.retry") : t("btn.trigger_run")}</button>
    </form></>;
}
