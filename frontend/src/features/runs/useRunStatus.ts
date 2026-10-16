import { useQuery } from "@tanstack/react-query";
import { getRunStatus } from "../../api/endpoints";
import { TERMINAL_RUN_STATUSES } from "../../api/types";

/** Poll interval while a run is active and the page is visible (doc §3.4: 5–10 s). */
export const RUN_POLL_INTERVAL_MS = 5_000;

export function useRunStatus(runId: string) {
  return useQuery({
    queryKey: ["run-status", runId],
    queryFn: ({ signal }) => getRunStatus(runId, signal),
    // Stop at terminal state; TanStack pauses in background tabs and refetches on focus.
    refetchInterval: (query) =>
      query.state.data && TERMINAL_RUN_STATUSES.includes(query.state.data.status) ? false : RUN_POLL_INTERVAL_MS,
    refetchIntervalInBackground: false,
  });
}
