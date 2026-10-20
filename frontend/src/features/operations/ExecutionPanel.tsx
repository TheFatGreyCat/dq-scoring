import { useQuery } from "@tanstack/react-query";
import { ProblemAlert } from "../../components/ProblemAlert";
import { formatTimestamp } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { getRunExecution } from "./operationsApi";
import { useOperationsText, type OperationsTextKey } from "./operationsText";

/** Request state and per-attempt Spark observation, shown as separate sources. Polls only while `active`. */
export function ExecutionPanel({ runId, scope, active }: { runId: string; scope?: "mine" | "workspace"; active: boolean }) {
  const { lang } = useI18n();
  const text = useOperationsText();
  const execution = useQuery({
    queryKey: ["run-execution", runId, scope ?? "default"],
    queryFn: ({ signal }) => getRunExecution(runId, scope, signal),
    refetchInterval: active ? 5000 : false,
    refetchIntervalInBackground: false,
  });
  const data = execution.data;
  return (
    <section className="card space-y-3" aria-labelledby="run-spark-title">
      <h2 id="run-spark-title">{text("spark_title")}</h2>
      <p className="text-sm text-fg-muted">{text("spark_note")}</p>
      <ProblemAlert error={execution.isError ? execution.error : null} onRetry={() => void execution.refetch()} />
      {data?.attempts.map(attempt => (
        <div key={attempt.lease_generation} className="border-t border-border pt-2 space-y-1">
          <p className="font-medium">{text("attempt")} {attempt.attempt_count} · {text(`spark_${attempt.spark.state.toLowerCase()}` as OperationsTextKey)}
            {attempt.spark.observed_at && <> · <time dateTime={attempt.spark.observed_at}>{formatTimestamp(attempt.spark.observed_at, lang).local}</time></>}</p>
          {attempt.spark.application_id && <p className="mono text-sm">{text("application")}: {attempt.spark.application_id}</p>}
          {attempt.spark.group_id && <p className="mono text-sm">{text("group")}: {attempt.spark.group_id}</p>}
          {attempt.spark.jobs.length > 0 && (
            <ul className="text-sm">
              {attempt.spark.jobs.map(job => (
                <li key={job.job_id}>#{job.job_id} {job.status} · {text("tasks")} {job.completed_tasks}/{job.tasks}{job.failed_tasks > 0 && ` · ${job.failed_tasks} failed`}</li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </section>
  );
}
