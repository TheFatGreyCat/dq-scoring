import { useQuery } from "@tanstack/react-query";
import { getOperationsMonitor } from "../../api/endpoints";
import { PageHeader } from "../../components/Field";
import { ProblemAlert } from "../../components/ProblemAlert";
import { formatTimestamp } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { useIdentity } from "../auth/useIdentity";

export function MonitorPage() {
  const identity = useIdentity();
  const {t, lang} = useI18n();
  const allowed = identity.data?.role === "WORKSPACE_ADMIN";
  const query = useQuery({queryKey:["operations-monitor",identity.data?.user_id,identity.data?.tenant_id],queryFn:({signal})=>getOperationsMonitor(signal),enabled:allowed,retry:false,refetchInterval:5000,refetchIntervalInBackground:false});
  if (!allowed) return <p role="alert">{t("operations.forbidden")}</p>;
  const data=query.data;
  return <div className="space-y-6"><PageHeader title={t("operations.title")} />
    <button className="btn-secondary" onClick={()=>void query.refetch()}>{t("operations.refresh")}</button>
    {query.isError && <><ProblemAlert error={query.error} onRetry={()=>void query.refetch()} /><p>{t("operations.stale")}</p></>}
    {!data ? <p>{t("operations.unknown")}</p> : <>
      <p>{t("operations.updated")}: {formatTimestamp(data.checked_at,lang).local}</p>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{Object.entries(data.components).map(([name,status])=><section className="card" key={name}><h2>{name}</h2><p>{status === "unknown" ? t("operations.unknown") : status}</p></section>)}</div>
      <section className="card overflow-x-auto"><table className="w-full"><tbody>{data.workers.map(worker=><tr key={worker.worker_id}><th className="text-left p-2">{worker.kind}</th><td>{worker.status}</td><td>{formatTimestamp(worker.heartbeat_at,lang).local}</td><td>{worker.last_error_code}</td></tr>)}</tbody></table>{!data.workers.length && <p>{t("operations.unknown")}</p>}</section>
      <section className="card"><h2>Spark</h2><p>{data.spark.active_executors ?? "—"} / {data.spark.expected_executors ?? "—"} executors</p><p>{t("operations.heap")}</p>{data.spark.workers.map(worker=><p key={worker.id}>{worker.id}: {worker.state} · {worker.allocated_cores}/{worker.cores} cores · {worker.allocated_memory_mib}/{worker.memory_mib} MiB</p>)}</section>
      <section className="card"><h2>{t("nav.runs")}</h2><p>QUEUED: {data.queue.queued ?? "—"} · RUNNING: {data.queue.active ?? "—"} · FAILED: {data.queue.failed_24h ?? "—"}</p></section>
    </>}
  </div>;
}
