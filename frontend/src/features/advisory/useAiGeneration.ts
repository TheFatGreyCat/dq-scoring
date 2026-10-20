import { useQuery } from "@tanstack/react-query";
import { getAiStatus } from "../../api/endpoints";
import { IMPORT_ROLES, useIdentity } from "../auth/useIdentity";

/**
 * Whether the user may start an explicit, cost-bearing AI action. Status failure or
 * disabled status simply yields `false`; it never blocks the host page and never infers.
 */
export function useAiGeneration(kind: "recommendations" | "narrative") {
  const identity = useIdentity();
  const status = useQuery({ queryKey: ["ai-status"], queryFn: ({ signal }) => getAiStatus(signal), retry: false, staleTime: 60_000 });
  const role = identity.data?.role;
  const canGenerate = Boolean(status.data?.enabled && status.data[kind] && role && IMPORT_ROLES[role]);
  return { canGenerate, model: status.data?.model ?? null };
}
