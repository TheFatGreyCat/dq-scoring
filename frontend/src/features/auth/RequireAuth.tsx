import { Navigate, Outlet, useLocation } from "react-router";
import { useSession } from "./useSession";

/** Presentation-only guard; the server remains the authority on access. */
export function RequireAuth() {
  const { authenticated } = useSession();
  const location = useLocation();
  if (!authenticated) return <Navigate to="/login" replace state={{ from: location.pathname + location.search + location.hash }} />;
  return <Outlet />;
}
