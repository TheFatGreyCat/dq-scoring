import { useSyncExternalStore } from "react";
import { session } from "../../api/client";

export function useSession() {
  const authenticated = useSyncExternalStore(session.subscribe, session.isAuthenticated);
  const email = useSyncExternalStore(session.subscribe, session.email);
  return { authenticated, email };
}
