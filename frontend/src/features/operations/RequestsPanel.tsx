import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { session } from "../../api/client";
import { listRuns } from "../../api/endpoints";
import { Field } from "../../components/Field";
import { ProblemAlert } from "../../components/ProblemAlert";
import { RunBadge } from "../../components/StatusBadge";
import { formatTimestamp } from "../../lib/format";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { useOperationsText } from "./operationsText";

const STATUSES = ["QUEUED", "LEASED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Admin-only: explicit workspace scope, server-side filters and pagination. */
export function RequestsPanel() {
  const { t, lang } = useI18n();
  const text = useOperationsText();
  const [status, setStatus] = useState("");
  const [creator, setCreator] = useState("");
  const [page, setPage] = useState(1);
  const creatorValid = creator === "" || UUID.test(creator);
  const runs = useQuery({
    queryKey: ["ops-requests", session.email(), status, creator, page],
    queryFn: ({ signal }) => listRuns({ scope: "workspace", status, created_by: creator, page }, signal),
    enabled: creatorValid,
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
  });
  return (
    <section className="card space-y-3" aria-labelledby="ops-requests-title">
      <h2 id="ops-requests-title">{text("requests")}</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("common.status")}>{id => <select id={id} className="input" value={status} onChange={e => { setStatus(e.target.value); setPage(1); }}><option value="">{t("common.all")}</option>{STATUSES.map(s => <option key={s} value={s}>{t(`status.${s}` as TranslationKey)}</option>)}</select>}</Field>
        <Field label={text("creator")}>{id => <input id={id} className="input mono" value={creator} aria-invalid={!creatorValid} onChange={e => { setCreator(e.target.value.trim()); setPage(1); }} />}</Field>
      </div>
      <ProblemAlert error={runs.isError ? runs.error : null} onRetry={() => void runs.refetch()} />
      <div className="overflow-x-auto">
        <table className="w-full">
          <tbody>
            {runs.data?.items.map(run => (
              <tr key={run.run_id}>
                <th scope="row" className="text-left p-2 mono">{run.run_id.slice(0, 8)}</th>
                <td className="p-2"><RunBadge status={run.status} /></td>
                <td className="p-2 mono">{run.created_by ? run.created_by.slice(0, 8) : text("owner_unknown")}{run.owned_by_me && ` (${text("mine_marker")})`}</td>
                <td className="p-2">{text("submitted")}: {formatTimestamp(run.created_at, lang).local}</td>
                <td className="p-2"><Link className="text-action inline-flex min-h-11 items-center" to={`/runs/${run.run_id}`}>{text("open")}</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {runs.data?.total === 0 && <p>{t("common.empty")}</p>}
      <div className="flex flex-wrap items-center gap-3">
        <button className="btn-secondary min-h-11" disabled={page <= 1} onClick={() => setPage(page - 1)}>{t("common.previous")}</button>
        <p>{t("common.count", { count: runs.data?.total ?? 0 })}</p>
        <button className="btn-secondary min-h-11" disabled={page * 25 >= (runs.data?.total ?? 0)} onClick={() => setPage(page + 1)}>{t("common.next")}</button>
      </div>
    </section>
  );
}
