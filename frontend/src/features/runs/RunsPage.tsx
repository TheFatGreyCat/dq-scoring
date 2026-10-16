import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";
import { session } from "../../api/client";
import { listRuns } from "../../api/endpoints";
import { Field, PageHeader } from "../../components/Field";
import { ProblemAlert } from "../../components/ProblemAlert";
import { RunBadge } from "../../components/StatusBadge";
import { useI18n, type TranslationKey } from "../../lib/i18n";

export function RunsPage() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const filters = Object.fromEntries(params);
  const page = Number(filters.page ?? 1);
  const runs = useQuery({ queryKey: ["runs", session.email(), filters], queryFn: ({ signal }) => listRuns(filters, signal) });
  const change = (key: string, value: string) => setParams(previous => { value ? previous.set(key, value) : previous.delete(key); if (key !== "page") previous.delete("page"); return previous; });
  return <><PageHeader title={t("run.history")} actions={<Link className="btn-primary" to="/runs/new">{t("recommend.run")}</Link>} />
    <section className="card space-y-4"><div className="grid gap-3 sm:grid-cols-3"><Field label={t("common.status")}>{id => <select id={id} className="input" value={filters.status ?? ""} onChange={e => change("status", e.target.value)}><option value="">{t("common.all")}</option>{["QUEUED", "LEASED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"].map(status => <option key={status} value={status}>{t(`status.${status}` as TranslationKey)}</option>)}</select>}</Field>{(["created_from", "created_to"] as const).map(key => <Field key={key} label={t(key === "created_from" ? "common.from" : "common.to")}>{id => <input id={id} className="input" type="datetime-local" value={filters[key]?.slice(0,16) ?? ""} onChange={e => change(key, e.target.value ? new Date(e.target.value).toISOString() : "")} />}</Field>)}</div>
      <ProblemAlert error={runs.error} />{runs.isPending && <p>{t("common.loading")}</p>}
      <ul className="divide-y divide-border">{runs.data?.items.map(run => <li className="py-3 flex flex-wrap justify-between gap-3" key={run.run_id}><Link className="text-action mono" to={`/runs/${run.run_id}`}>{run.run_id.slice(0,8)}</Link><RunBadge status={run.status} />{run.assessment_id && <Link className="text-action" to={`/assessments/${run.assessment_id}`}>{t("nav.assessments")}</Link>}</li>)}</ul>{runs.data?.total === 0 && <p>{t("common.empty")}</p>}
      <div className="flex flex-wrap gap-3"><button className="btn-secondary" disabled={page <= 1} onClick={() => change("page", String(page-1))}>{t("common.previous")}</button><p>{t("common.count", { count: runs.data?.total ?? 0 })}</p><button className="btn-secondary" disabled={page*25 >= (runs.data?.total ?? 0)} onClick={() => change("page", String(page+1))}>{t("common.next")}</button><button className="btn-secondary" onClick={() => setParams({})}>{t("common.reset")}</button></div>
    </section></>;
}
