import { queryClient } from "../app/queryClient";
import { recent } from "../lib/recent";
import type { ProblemDetails, TokenResponse } from "./types";

const API_PREFIX = "/api/v1";
/** Per-request network timeout (ms); a timeout is reported as "unknown", never as a failure. */
const REQUEST_TIMEOUT_MS = 15_000;

export type ApiErrorKind = "http" | "network" | "timeout";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  readonly problem: ProblemDetails | null;

  constructor(kind: ApiErrorKind, status: number | null, problem: ProblemDetails | null) {
    super(problem?.detail ?? problem?.title ?? kind);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.problem = problem;
  }
}

/*
 * Tokens live in module memory only: never localStorage, cookies, or URLs.
 * A page reload therefore requires signing in again (APPLICATION_UI_DESIGN §3.1).
 */
interface Tokens {
  access: string;
  refresh: string;
  /** Email typed at sign-in; display only, never used for authorization. */
  email: string;
}

let tokens: Tokens | null = null;
let generation = 0;
const listeners = new Set<() => void>();

export const session = {
  isAuthenticated: () => tokens !== null,
  generation: () => generation,
  set(res: TokenResponse, email = tokens?.email ?? "") {
    if (!tokens) { generation++; void queryClient.cancelQueries(); queryClient.clear(); }
    tokens = { access: res.access_token, refresh: res.refresh_token, email };
    listeners.forEach((l) => l());
  },
  clear() {
    generation++;
    void queryClient.cancelQueries();
    queryClient.clear();
    recent.clear();
    tokens = null;
    listeners.forEach((l) => l());
  },
  accessToken: () => tokens?.access ?? null,
  refreshToken: () => tokens?.refresh ?? null,
  email: () => tokens?.email ?? null,
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};

let refreshInFlight: Promise<boolean> | null = null;

/** Single-flight refresh: concurrent 401s share one refresh request. */
function refreshOnce(): Promise<boolean> {
  refreshInFlight ??= (async () => {
    const refresh = tokens?.refresh;
    if (!refresh) return false;
    try {
      const res = await send<TokenResponse>("POST", "/auth/refresh", { refresh_token: refresh }, false);
      session.set(res);
      void queryClient.invalidateQueries({ queryKey: ["identity"] });
      return true;
    } catch {
      session.clear();
      return false;
    }
  })().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

async function send<T>(
  method: string,
  path: string,
  body: unknown,
  auth: boolean,
  signal?: AbortSignal,
  binary = false,
  responseType: "json" | "blob" = "json",
  cache?: RequestCache,
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: responseType === "blob" ? "*/*, application/problem+json" : "application/json, application/problem+json",
  };
  if (body !== undefined) headers["Content-Type"] = binary ? "application/octet-stream" : "application/json";
  if (auth && tokens) headers.Authorization = `Bearer ${tokens.access}`;

  const timeout = AbortSignal.timeout(binary || responseType === "blob" ? 120_000 : REQUEST_TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(API_PREFIX + path, {
      method,
      headers,
      body: body === undefined ? undefined : binary ? body as Blob : JSON.stringify(body),
      signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
      cache: cache ?? (responseType === "blob" ? "no-store" : undefined),
    });
  } catch (err) {
    if (signal?.aborted) throw err;
    throw new ApiError(timeout.aborted ? "timeout" : "network", null, null);
  }

  if (res.ok) {
    if (responseType === "blob") return (await res.blob()) as T;
    return (res.status === 204 ? undefined : await res.json()) as T;
  }
  const problem = (await res.json().catch(() => null)) as ProblemDetails | null;
  throw new ApiError("http", res.status, problem);
}

export async function api<T>(
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
  path: string,
  options: {
    body?: unknown;
    auth?: boolean;
    signal?: AbortSignal;
    binary?: boolean;
    responseType?: "json" | "blob";
    cache?: RequestCache;
  } = {},
): Promise<T> {
  const { body, auth = true, signal, binary = false, responseType = "json", cache } = options;
  try {
    return await send<T>(method, path, body, auth, signal, binary, responseType, cache);
  } catch (err) {
    const expired = err instanceof ApiError && err.status === 401 && auth && session.isAuthenticated();
    if (!expired || !(await refreshOnce())) throw err;
    return send<T>(method, path, body, auth, signal, binary, responseType, cache);
  }
}
