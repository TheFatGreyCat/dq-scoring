import { useQuery } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";
import { session } from "../../api/client";
import { getCurrentUser } from "../../api/endpoints";

export function useIdentity() {
  const generation = useSyncExternalStore(session.subscribe, session.generation);
  const authenticated = useSyncExternalStore(session.subscribe, session.isAuthenticated);
  return useQuery({ queryKey: ["identity", generation], queryFn: ({signal}) => getCurrentUser(signal), enabled: authenticated, retry: false });
}
export const IMPORT_ROLES: Record<string, true> = { WORKSPACE_ADMIN: true, DATA_OWNER: true, DATA_STEWARD: true, DATA_ENGINEER: true };
export const POLICY_WRITE_ROLES: Record<string, true> = { WORKSPACE_ADMIN: true, DATA_OWNER: true, DATA_STEWARD: true };
