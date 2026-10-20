import { api } from "../../api/client";
import type { UUID } from "../../api/types";

export type AdapterState = "up" | "degraded" | "down" | "unknown" | "off" | "not_configured";
export interface AdapterObservation {
  name: "database" | "storage" | "spark_compute" | "advisory_gateway";
  state: AdapterState;
  source: "probe" | "worker_heartbeat" | "configuration";
  checked_at: string | null;
  last_success_at: string | null;
  stale: boolean;
  timeout_seconds: number | null;
}

export interface SparkJob { job_id: number; status: string; stages: number; tasks: number; active_tasks: number; completed_tasks: number; failed_tasks: number; }
export interface SparkAttempt {
  state: "OBSERVED" | "STALE" | "ENDED" | "UNKNOWN";
  observed_at: string | null;
  /** Present for workspace administrators only. */
  application_id: string | null;
  group_id: string | null;
  jobs: SparkJob[];
}
export interface ExecutionAttempt { lease_generation: number; attempt_count: number; claimed_at: string | null; outcome: string | null; spark: SparkAttempt; }
export interface RunExecution {
  request: { status: string; attempt_count: number; started_at: string | null; heartbeat_at: string | null; completed_at: string | null };
  attempts: ExecutionAttempt[];
  observed_scope: "RUN_ATTEMPT";
}

export const getRunExecution = (runId: UUID, scope: "mine" | "workspace" | undefined, signal?: AbortSignal) =>
  api<RunExecution>("GET", `/runs/${encodeURIComponent(runId)}/execution${scope ? `?scope=${scope}` : ""}`, { signal });
