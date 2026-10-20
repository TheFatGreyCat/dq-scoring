import { useQuery } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import { getRunStatus } from "../../api/endpoints";
import { TERMINAL_RUN_STATUSES, type RunScope } from "../../api/types";

/** Poll interval while a run is active and the page is visible (doc §3.4: 5–10 s). */
export const RUN_POLL_INTERVAL_MS = 5_000;
const MAX_BACKOFF_STEPS = 3;

/** Next poll delay: none once terminal or when the server answered with a definitive 4xx; backs off on transport errors. */
export function pollDelay(terminal: boolean, error: unknown, errorCount: number): number | false {
  if (terminal) return false;
  if (error instanceof ApiError && error.kind === "http" && error.status !== null && error.status >= 400 && error.status < 500 && error.status !== 429) return false;
  return RUN_POLL_INTERVAL_MS * 2 ** Math.min(error ? errorCount : 0, MAX_BACKOFF_STEPS);
}

export function useRunStatus(runId: string, scope?: RunScope) {
  return useQuery({
    queryKey: ["run-status", runId, scope ?? "default"],
    queryFn: ({ signal }) => getRunStatus(runId, signal, scope),
    // TanStack pauses in background tabs and refetches on focus.
    refetchInterval: (query) =>
      pollDelay(!!query.state.data && TERMINAL_RUN_STATUSES.includes(query.state.data.status), query.state.error, query.state.errorUpdateCount),
    refetchIntervalInBackground: false,
  });
}
