import { useQuery } from "@tanstack/react-query";
import { getOverview } from "../api/endpoints";
import { ProblemAlert } from "../components/ProblemAlert";
import { UsageGuide } from "../components/UsageGuide";
import { useIdentity } from "./auth/useIdentity";
import { Link } from "react-router";
import { PageHeader } from "../components/Field";
import { useI18n, type TranslationKey } from "../lib/i18n";

export function OverviewPage() {
  const { t } = useI18n();
  const identity=useIdentity();
  const overview=useQuery({queryKey:["overview",identity.data?.user_id,identity.data?.tenant_id],queryFn:({signal})=>getOverview(signal),enabled:!!identity.data,retry:false,refetchInterval:15000,refetchIntervalInBackground:false});
  const destinations: [string, TranslationKey][] = [["/assets", "nav.assets"], ["/rulesets", "nav.rulesets"], ["/policies", "nav.policies"], ["/templates", "nav.templates"], ["/runs", "nav.runs"], ["/assessments", "nav.assessments"]];
  return <div className="space-y-6"><PageHeader title={t("nav.overview")} description={t("overview.desc")} /><UsageGuide /><ProblemAlert error={overview.error} onRetry={()=>void overview.refetch()} />
    {overview.data && <><div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"><Link className="card" to="/assets">{t("nav.assets")}: {overview.data.counts.assets} · {overview.data.counts.snapshots}</Link><Link className="card" to="/runs">QUEUED: {overview.data.counts.runs.QUEUED} · RUNNING: {overview.data.counts.runs.RUNNING} · FAILED: {overview.data.counts.runs.FAILED}</Link><Link className="card" to="/rulesets">{t("nav.rulesets")}: {overview.data.counts.rulesets_pending}</Link><Link className="card" to="/policies">{t("nav.policies")}: {overview.data.counts.policies_pending}</Link></div><section className="card"><h2>{t("nav.runs")}</h2>{overview.data.recent_runs.map(run=><p key={run.run_id}><Link className="text-action" to={`/runs/${run.run_id}`}>{run.run_id} · {run.status}</Link></p>)}{!overview.data.recent_runs.length && <p>{t("common.empty")}</p>}</section>{overview.data.recent_imports && <section className="card">{overview.data.recent_imports.filter(row=>["VERIFIED","REJECTED","FAILED"].includes(row.status)).map(row=><p key={row.upload_id}><Link className="text-action" to={`/assets?import=${row.upload_id}`}>{row.original_filename} · {row.status}</Link></p>)}</section>}</>}
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{destinations.map(([path, key]) => <Link key={path} className="card hover:border-action focus-visible:outline-2 focus-visible:outline-action" to={path}><h2>{t(key)}</h2><p className="text-action mt-3">{t("btn.open")}</p></Link>)}</div></div>;
}
