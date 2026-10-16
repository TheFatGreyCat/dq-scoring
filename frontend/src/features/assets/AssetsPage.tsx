import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";
import { listAssets } from "../../api/endpoints";
import { useIdentity, IMPORT_ROLES } from "../auth/useIdentity";
import { ImportSessions } from "./ImportSessions";
import { Field, PageHeader } from "../../components/Field";
import { ProblemAlert } from "../../components/ProblemAlert";
import { useI18n } from "../../lib/i18n";
import { ImportWizard } from "./ImportWizard";

export function AssetsPage() {
  const { t } = useI18n();
  const identity = useIdentity();
  const [params, setParams] = useSearchParams();
  const filters = { q: params.get("q") ?? "", format: params.get("format") ?? "", page: Number(params.get("page") ?? 1) };
  const assets = useQuery({ queryKey: ["assets", identity.data?.user_id, identity.data?.tenant_id, filters], queryFn: ({ signal }) => listAssets(filters, signal), enabled: !!identity.data });
  const change = (key: string, value: string) => setParams(previous => { value ? previous.set(key, value) : previous.delete(key); if (key !== "page") previous.delete("page"); return previous; });
  return <>
    <PageHeader title={t("nav.assets")} description={t("assets.import")} />
    <section className="card space-y-4">
      <div className="grid gap-3 sm:grid-cols-2"><Field label={t("common.search")}>{id => <input id={id} className="input" value={filters.q} onChange={e => change("q", e.target.value)} />}</Field><Field label={t("common.format")}>{id => <select id={id} className="input" value={filters.format} onChange={e => change("format", e.target.value)}><option value="">{t("common.all")}</option>{["CSV", "PARQUET", "JSONL"].map(f => <option key={f}>{f}</option>)}</select>}</Field></div>
      <ProblemAlert error={assets.error} />
      {assets.isPending ? <p>{t("common.loading")}</p> : <ul className="divide-y divide-border">{assets.data?.items.map(asset => <li className="py-3 flex flex-wrap gap-3 justify-between" key={asset.asset_id}><span>{asset.name} · {asset.format} · {asset.version_count}</span>{asset.current_snapshot_id && <Link className="text-action" to={`/snapshots/${asset.current_snapshot_id}`}>{t("btn.open")}</Link>}</li>)}</ul>}
      {assets.data?.total === 0 && <p>{t("common.empty")}</p>}
      <div className="flex gap-3 items-center"><button className="btn-secondary" disabled={filters.page <= 1} onClick={() => change("page", String(filters.page - 1))}>{t("common.previous")}</button><p>{t("common.count", { count: assets.data?.total ?? 0 })}</p><button className="btn-secondary" disabled={filters.page * 25 >= (assets.data?.total ?? 0)} onClick={() => change("page", String(filters.page + 1))}>{t("common.next")}</button><button className="btn-secondary" onClick={() => { change("q", ""); change("format", ""); }}>{t("common.reset")}</button></div>
    </section>
    {identity.data && IMPORT_ROLES[identity.data.role] && <><ImportSessions /><ImportWizard /></>}
  </>;
}
