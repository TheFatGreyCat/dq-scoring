import { useQuery } from "@tanstack/react-query";
import { WifiOff } from "lucide-react";
import { Link, useSearchParams } from "react-router";
import { session } from "../../api/client";
import { listRuns } from "../../api/endpoints";
import { Field, PageHeader } from "../../components/Field";
import { ProblemAlert } from "../../components/ProblemAlert";
import { RunBadge } from "../../components/StatusBadge";
import { TERMINAL_RUN_STATUSES } from "../../api/types";
import { formatTimestamp } from "../../lib/format";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { pollDelay } from "./useRunStatus";
import { useRunText } from "./runText";

/** `mine`: personal job view. Scope is fixed here; nothing in the URL can widen it. */
export function RunsPage({ mine = false }: { mine?: boolean }) {
  const { t, lang } = useI18n();
  const text = useRunText();
  const [params, setParams] = useSearchParams();
  const { scope: _scope, created_by: _creator, ...filters } = Object.fromEntries(params);
  const page = Number(filters.page ?? 1);
  const scope = mine ? "mine" : undefined;
  const runs = useQuery({
    queryKey: ["runs", session.email(), scope ?? "default", filters],
    queryFn: ({ signal }) => listRuns({ ...filters, scope }, signal),
    refetchInterval: query => pollDelay(!query.state.data?.items.some(run => !TERMINAL_RUN_STATUSES.includes(run.status)), query.state.error, query.state.errorUpdateCount),
    refetchIntervalInBackground: false,
  });
  const stale = runs.isError && !!runs.data;
  const detail = (id: string) => `/runs/${id}${mine ? "?scope=mine" : ""}`;
  const change = (key: string, value: string) => setParams(previous => { value ? previous.set(key, value) : previous.delete(key); if (key !== "page") previous.delete("page"); return previous; });
  return <><PageHeader title={mine ? text("mine_title") : t("run.history")} actions={<Link className="btn-primary" to="/runs/new">{t("recommend.run")}</Link>} />
    <section className="card space-y-4"><div className="grid gap-3 sm:grid-cols-3"><Field label={t("common.status")}>{id => <select id={id} className="input" value={filters.status ?? ""} onChange={e => change("status", e.target.value)}><option value="">{t("common.all")}</option>{["QUEUED", "LEASED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"].map(status => <option key={status} value={status}>{t(`status.${status}` as TranslationKey)}</option>)}</select>}</Field>{(["created_from", "created_to"] as const).map(key => <Field key={key} label={t(key === "created_from" ? "common.from" : "common.to")}>{id => <input id={id} className="input" type="datetime-local" value={filters[key]?.slice(0,16) ?? ""} onChange={e => change(key, e.target.value ? new Date(e.target.value).toISOString() : "")} />}</Field>)}</div>
      {mine && <p className="text-sm text-fg-muted">{text("mine_hint")}</p>}
      {stale && <p role="status" className="flex items-center gap-2 rounded-control bg-neutral-bg p-3 text-sm text-neutral"><WifiOff aria-hidden className="size-4" /> {text("stale", { time: formatTimestamp(new Date(runs.dataUpdatedAt).toISOString(), lang).local })} <button className="btn-secondary min-h-11" onClick={() => void runs.refetch()}>{text("refresh")}</button></p>}
      <ProblemAlert error={stale ? null : runs.error} onRetry={() => void runs.refetch()} />{runs.isPending && <p>{t("common.loading")}</p>}
      <ul className="divide-y divide-border" aria-label={mine ? text("mine_title") : t("run.history")}>{runs.data?.items.map(run => <li className="py-3 flex flex-wrap justify-between gap-3" key={run.run_id}><Link className="text-action mono" to={detail(run.run_id)}>{run.run_id.slice(0,8)}</Link><time className="text-sm text-fg-muted" dateTime={run.created_at}>{formatTimestamp(run.created_at, lang).local}</time><RunBadge status={run.status} />{run.assessment_id && <Link className="text-action" to={`/assessments/${run.assessment_id}`}>{t("nav.assessments")}</Link>}</li>)}</ul>{runs.data?.total === 0 && <p>{t("common.empty")}</p>}
      <div className="flex flex-wrap gap-3"><button className="btn-secondary" disabled={page <= 1} onClick={() => change("page", String(page-1))}>{t("common.previous")}</button><p>{t("common.count", { count: runs.data?.total ?? 0 })}</p><button className="btn-secondary" disabled={page*25 >= (runs.data?.total ?? 0)} onClick={() => change("page", String(page+1))}>{t("common.next")}</button><button className="btn-secondary" onClick={() => setParams({})}>{t("common.reset")}</button></div>
    </section></>;
}
