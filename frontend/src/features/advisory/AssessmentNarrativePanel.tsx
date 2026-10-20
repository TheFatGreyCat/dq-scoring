import { useSyncExternalStore } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot } from "lucide-react";
import { ApiError, session } from "../../api/client";
import { createAssessmentNarrative, getAssessmentNarrative } from "../../api/endpoints";
import type { AssessmentNarrative } from "../../api/types";
import { ProblemAlert } from "../../components/ProblemAlert";
import { formatTimestamp } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { useAiGeneration } from "./useAiGeneration";

/**
 * Optional advisory narrative. The latest stored report is read (404 = none, never inferred);
 * generation happens only on explicit click. Text is rendered as plain text — never Markdown/HTML.
 */
export function AssessmentNarrativePanel({ assessmentId, assessmentHash }: { assessmentId: string; assessmentHash: string }) {
  const { lang, t } = useI18n();
  const { canGenerate } = useAiGeneration("narrative");
  const queryClient = useQueryClient();
  const generation = useSyncExternalStore(session.subscribe, session.generation);
  const key = ["assessment-narrative", generation, assessmentId];

  const latest = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => getAssessmentNarrative(assessmentId, signal),
    retry: false,
  });
  const mutation = useMutation({
    mutationFn: () => createAssessmentNarrative(assessmentId),
    onSuccess: (report) => queryClient.setQueryData<AssessmentNarrative>(key, report),
  });

  const report = latest.data?.narrative ? latest.data : undefined;
  const missing = latest.error instanceof ApiError && latest.error.status === 404;
  // Hide entirely when nothing to show and generation isn't available; absence must not block the page.
  if (!report && !canGenerate) return null;

  return (
    <section className="card space-y-3" aria-labelledby="ai-narrative">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="ai-narrative" className="flex items-center gap-2">
          <Bot className="size-5 text-brand" aria-hidden /> {t("ai.narr.title")}
        </h2>
        <span className="rounded-control border border-border px-2 py-0.5 text-xs text-fg-muted">{t("ai.badge")}</span>
      </div>
      <p className="text-sm text-fg-muted">{t("ai.narr.unverified")}</p>

      {report && (
        <div className="space-y-2">
          <p className="text-xs text-fg-muted">
            {t("ai.model")}: {report.model} · {t("ai.generated_at")}: {formatTimestamp(report.created_at, lang).local}
          </p>
          {report.assessment_hash !== assessmentHash && <p role="status" className="text-xs text-warn">{t("ai.narr.stale")}</p>}
          <p className="whitespace-pre-wrap break-words text-sm" data-testid="ai-narrative-text">{report.narrative}</p>
          {report.cited_rules.length > 0 && (
            <p className="text-xs text-fg-muted">
              {t("ai.narr.cited")}:{" "}
              {report.cited_rules.map((c) => (c.rule_id ? c.token : `${c.token} (${t("ai.narr.cited_unresolved")})`)).join(", ")}
            </p>
          )}
        </div>
      )}

      {canGenerate && latest.isError && !missing && <ProblemAlert error={latest.error} onRetry={() => latest.refetch()} />}
      <ProblemAlert error={mutation.error} />

      {canGenerate && (
        <div className="space-y-1">
          <p className="text-xs text-fg-muted">{t("ai.cost_notice")}</p>
          <button type="button" className="btn-secondary" disabled={mutation.isPending || latest.isPending} onClick={() => mutation.mutate()}>
            {mutation.isPending ? t("ai.narr.generating") : report ? t("ai.narr.regenerate") : t("ai.narr.generate")}
          </button>
        </div>
      )}
    </section>
  );
}
