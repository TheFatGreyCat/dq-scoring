import { ArrowRight, WifiOff } from "lucide-react";
import { useEffect } from "react";
import { Link, useParams } from "react-router";
import { ApiError } from "../../api/client";
import { TERMINAL_RUN_STATUSES } from "../../api/types";
import { CopyId } from "../../components/CopyId";
import { PageHeader } from "../../components/Field";
import { ProblemAlert } from "../../components/ProblemAlert";
import { RunBadge } from "../../components/StatusBadge";
import { formatTimestamp } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { recent } from "../../lib/recent";
import { useRunStatus } from "./useRunStatus";

export function RunStatusPage() {
  const { t, lang } = useI18n();
  const { runId = "" } = useParams();
  const query = useRunStatus(runId);
  const run = query.data;
  const terminal = run ? TERMINAL_RUN_STATUSES.includes(run.status) : false;
  // A failed poll while we still hold data is a transport problem, not a run failure.
  const reconnecting = !!run && query.isError && query.error instanceof ApiError && query.error.kind !== "http";

  useEffect(() => {
    if (run) recent.remember({ kind: "run", id: run.run_id, label: `Run ${run.run_id.slice(0, 8)}`, status: run.status });
    if (run?.assessment_id) recent.remember({ kind: "assessment", id: run.assessment_id, label: `Assessment of run ${run.run_id.slice(0, 8)}` });
  }, [run]);

  const updated = formatTimestamp(run?.updated_at, lang);

  return (
    <>
      <nav aria-label={t("scorecard.breadcrumb")} className="text-sm text-fg-muted mb-2">
        <Link to="/runs" className="hover:underline">{t("nav.runs")}</Link> / {t("run.title")}
      </nav>
      <PageHeader title={t("run.title")} />

      {query.isPending && <p aria-busy>{t("common.loading")}</p>}
      {query.isError && !run && <ProblemAlert error={query.error} onRetry={() => query.refetch()} />}

      {run && (
        <div className="space-y-6">
          <section className="card space-y-5">
            {/* Announce status transitions only, not every poll. */}
            <div role="status" aria-live="polite" className="flex flex-wrap items-center gap-3">
              <RunBadge status={run.status} size="lg" />
              {!terminal && <span className="text-sm text-fg-muted">{t("run.refresh")}</span>}
            </div>
            <button className="btn-secondary" onClick={() => void query.refetch()}>{t("operations.refresh")}</button>
            {run.status === "QUEUED" && <p>{t("run.waiting")} · {formatTimestamp(run.created_at, lang).local} · {run.attempt_count}</p>}
            {run.status === "LEASED" && <p>{t("run.claimed")}</p>}
            {run.heartbeat_at && <p>{t("run.heartbeat")}: {formatTimestamp(run.heartbeat_at, lang).local}</p>}

            {run.status === "RUNNING" && (
              <div aria-hidden className="h-1.5 w-full overflow-hidden rounded-full bg-info-bg">
                <div className="h-full w-1/3 rounded-full bg-info animate-[indeterminate_1.4s_ease-in-out_infinite]" />
              </div>
            )}

            {reconnecting && (
              <p className="flex items-center gap-2 rounded-control bg-neutral-bg p-3 text-sm text-neutral">
                <WifiOff aria-hidden className="size-4" /> {t("run.reconnecting")}
              </p>
            )}

            <dl className="grid gap-4 sm:grid-cols-2">
              <CopyId label={t("run.id")} value={run.run_id} />
              <div>
                <dt className="text-xs text-fg-muted">{t("run.updated")}</dt>
                <dd title={updated.utc}>{updated.local}</dd>
              </div>
            </dl>
          </section>

          {run.status === "SUCCEEDED" && run.assessment_id && (
            <section className="card flex flex-wrap items-center justify-between gap-4">
              <div>
                <h2>{t("run.ready")}</h2>
                <p className="mono text-sm text-fg-muted">{run.assessment_id}</p>
              </div>
              <Link to={`/assessments/${run.assessment_id}`} className="btn-primary">
                {t("assessments.open_scorecard")} <ArrowRight aria-hidden className="size-4" />
              </Link>
            </section>
          )}

          {run.status === "FAILED" && (
            <section role="alert" className="card border-fail/40 space-y-2">
              <h2 className="text-fail">{t("run.failed")}</h2>
              <p className="text-sm">{t("run.unpublished")}</p>
              {run.error_message && <p className="rounded-control bg-surface-muted p-3 text-sm whitespace-pre-wrap break-words">{run.error_message}</p>}
            </section>
          )}
        </div>
      )}
    </>
  );
}
