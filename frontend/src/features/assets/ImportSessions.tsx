import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { listImports } from "../../api/endpoints";
import { ProblemAlert } from "../../components/ProblemAlert";
import { useI18n } from "../../lib/i18n";
import { useIdentity } from "../auth/useIdentity";

export function ImportSessions() {
  const identity=useIdentity();
  const {t}=useI18n();
  const [params]=useSearchParams();
  const [status,setStatus]=useState("");
  const query=useQuery({queryKey:["imports",identity.data?.user_id,identity.data?.tenant_id,status],queryFn:({signal})=>listImports({status,page_size:25},signal),retry:false,refetchInterval:query=>query.state.data?.items.some(row=>["STAGED","VERIFYING","UPLOADING"].includes(row.status))?5000:false,refetchIntervalInBackground:false});
  return <section className="card space-y-3"><h2>{t("assets.import")}</h2><select className="input" aria-label={t("common.status")} value={status} onChange={event=>setStatus(event.target.value)}><option value="">{t("common.all")}</option>{["INITIATED","UPLOADING","STAGED","VERIFYING","VERIFIED","REJECTED","FAILED","REGISTERED","ABORTED"].map(value=><option key={value}>{value}</option>)}</select><button className="btn-secondary" onClick={()=>void query.refetch()}>{t("operations.refresh")}</button><ProblemAlert error={query.error} onRetry={()=>void query.refetch()} /><ul>{query.data?.items.map(row=>{const next=new URLSearchParams(params);next.set("import",row.upload_id);return <li className="py-2" key={row.upload_id}><Link className="text-action" to={`/assets?${next}`}>{row.original_filename} · {row.status}</Link>{row.snapshot_id && <Link className="ml-3 text-action" to={`/snapshots/${row.snapshot_id}`}>{t("btn.open")}</Link>}</li>;})}</ul>{query.data?.total===0 && <p>{t("common.empty")}</p>}</section>;
}
