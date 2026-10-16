import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { getOperationsConfig } from "../../api/endpoints";
import { useUiPreferences } from "../../app/useUiPreferences";
import { PageHeader } from "../../components/Field";
import { ProblemAlert } from "../../components/ProblemAlert";
import { UsageGuide } from "../../components/UsageGuide";
import { useI18n } from "../../lib/i18n";
import { useIdentity } from "../auth/useIdentity";

export function SettingsPage() {
  const identity=useIdentity();
  const {theme,collapsed,setTheme,setCollapsed,saveFailed}=useUiPreferences();
  const {lang,setLang,t}=useI18n();
  const admin=identity.data?.role==="WORKSPACE_ADMIN";
  const config=useQuery({queryKey:["operations-config",identity.data?.user_id,identity.data?.tenant_id],queryFn:({signal})=>getOperationsConfig(signal),enabled:admin,retry:false});
  return <div className="space-y-6"><PageHeader title={t("settings.title")} description={t("settings.subtitle")} />
    <section className="card space-y-3"><h2>{t("settings.profile.title")}</h2><ProblemAlert error={identity.error} onRetry={()=>void identity.refetch()} /><p>{identity.data?.email}</p><p>{identity.data?.role}</p><p className="mono break-all">{identity.data?.tenant_id}</p></section>
    <section className="card space-y-4"><h2>{t("settings.appearance.title")}</h2><p>{t("settings.browser_only")}</p><div className="flex gap-3"><button className="btn-secondary" aria-pressed={lang==="vi"} onClick={()=>setLang("vi")}>Tiếng Việt</button><button className="btn-secondary" aria-pressed={lang==="en"} onClick={()=>setLang("en")}>English</button></div><div className="flex gap-3"><button className="btn-secondary" aria-pressed={theme==="light"} onClick={()=>setTheme("light")}>{t("theme.light")}</button><button className="btn-secondary" aria-pressed={theme==="dark"} onClick={()=>setTheme("dark")}>{t("theme.dark")}</button></div><button className="btn-secondary" aria-pressed={collapsed} onClick={()=>setCollapsed(!collapsed)}>{t(collapsed?"nav.expand":"nav.collapse")}</button>{saveFailed && <p role="alert">{t("preferences.unsaved")}</p>}</section>
    <section className="card"><UsageGuide /><Link className="ml-4 text-action" to="/runs">{t("nav.runs")}</Link></section>
    {admin && <section className="card space-y-3"><h2>{t("settings.deployment")}</h2><p>{t("settings.configured_only")}</p><ProblemAlert error={config.error} onRetry={()=>void config.refetch()} />{config.data && <><dl>{Object.entries(config.data.deployment).map(([key,value])=><div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl><h3>{t("settings.reported")}</h3>{config.data.reported_workers.map(worker=><p key={worker.worker_id}>{worker.worker_id}: {worker.sizing.executor_instances} executors · {worker.sizing.executor_memory}</p>)}</>}<Link className="text-action" to="/monitor">{t("operations.title")}</Link></section>}
  </div>;
}
