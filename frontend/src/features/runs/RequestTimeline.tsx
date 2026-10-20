import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { listRunEvents } from "../../api/endpoints";
import type { RunScope } from "../../api/types";
import { ProblemAlert } from "../../components/ProblemAlert";
import { formatTimestamp } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { RUN_POLL_INTERVAL_MS } from "./useRunStatus";
import { useRunText, type RunTextKey } from "./runText";

/**
 * Safe, typed event timeline. Query identity is run + scope only, so loaded pages survive status
 * transitions and transport failures; a status change (including the terminal one) triggers a refresh.
 */
export function RequestTimeline({ runId, scope, runStatus, active }: { runId: string; scope?: RunScope; runStatus: string; active: boolean }) {
  const { t, lang } = useI18n();
  const text = useRunText();
  const events = useInfiniteQuery({
    queryKey: ["run-events", runId, scope ?? "default"],
    queryFn: ({ pageParam, signal }) => listRunEvents(runId, { scope, cursor: pageParam ?? undefined }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: page => page.next_cursor,
    refetchInterval: active ? RUN_POLL_INTERVAL_MS : false,
    refetchIntervalInBackground: false,
  });
  const seenStatus = useRef(runStatus);
  const { refetch } = events;
  useEffect(() => {
    if (seenStatus.current === runStatus) return;
    seenStatus.current = runStatus;
    void refetch();
  }, [runStatus, refetch]);
  const items = events.data?.pages.flatMap(page => page.items) ?? [];
  return (
    <section className="card space-y-3" aria-labelledby="run-timeline-title">
      <h2 id="run-timeline-title">{text("timeline")}</h2>
      <ProblemAlert error={events.isError && !events.data ? events.error : null} onRetry={() => void events.refetch()} />
      {events.isPending && <p aria-busy>{t("common.loading")}</p>}
      {events.data && items.length === 0 && <p>{text("timeline_empty")}</p>}
      <ol className="divide-y divide-border">
        {items.map(event => {
          const when = formatTimestamp(event.created_at, lang);
          return (
            <li key={event.event_id} className="py-2 flex flex-wrap items-baseline gap-x-4 gap-y-1">
              <span className="font-medium">{text(`EVENT_${event.event_type}` as RunTextKey)}</span>
              <span className="text-sm text-fg-muted">{text("attempt", { n: event.attempt_count })}</span>
              <time className="text-sm text-fg-muted" dateTime={event.created_at} title={when.utc}>{when.local}</time>
              {event.error_code && <span className="mono text-sm text-fail">{event.error_code}</span>}
            </li>
          );
        })}
      </ol>
      {events.hasNextPage && (
        <button className="btn-secondary min-h-11" disabled={events.isFetchingNextPage} onClick={() => void events.fetchNextPage()}>
          {text("load_more")}
        </button>
      )}
    </section>
  );
}
