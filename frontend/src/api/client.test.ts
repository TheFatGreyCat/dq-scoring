import { ApiError, api, session } from "./client";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const TOKENS = { access_token: "a1", refresh_token: "r1", token_type: "bearer", expires_in: 1800 };

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  session.set(TOKENS);
});

afterEach(() => {
  session.clear();
  vi.unstubAllGlobals();
});

const callsTo = (path: string) => fetchMock.mock.calls.filter(([url]) => url === `/api/v1${path}`);

it("sends the bearer token and never persists it to browser storage", async () => {
  fetchMock.mockResolvedValue(json(200, { ok: true }));
  await api("GET", "/runs/x/status");
  expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe("Bearer a1");
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
  expect(String(fetchMock.mock.calls[0][0])).not.toContain("a1");
});

it("refreshes once for concurrent 401s and retries with the new token", async () => {
  fetchMock.mockImplementation(async (url: string, init: RequestInit) => {
    if (url.endsWith("/auth/refresh")) return json(200, { ...TOKENS, access_token: "a2", refresh_token: "r2" });
    const auth = (init.headers as Record<string, string>).Authorization;
    return auth === "Bearer a2" ? json(200, { ok: true }) : json(401, { title: "Unauthorized", status: 401 });
  });

  await Promise.all([api("GET", "/a"), api("GET", "/b"), api("GET", "/c")]);

  expect(callsTo("/auth/refresh")).toHaveLength(1);
  expect(JSON.parse(callsTo("/auth/refresh")[0][1].body)).toEqual({ refresh_token: "r1" });
  expect(session.refreshToken()).toBe("r2");
});

it("clears the session when refresh is rejected", async () => {
  fetchMock.mockResolvedValue(json(401, { title: "Unauthorized", status: 401, detail: "Token reuse" }));
  await expect(api("GET", "/a")).rejects.toMatchObject({ status: 401 });
  expect(session.isAuthenticated()).toBe(false);
});

it("maps problem+json to ApiError without exposing the raw body", async () => {
  fetchMock.mockResolvedValue(json(403, { title: "Forbidden", status: 403, detail: "Cannot self-approve." }));
  const err = await api("POST", "/rulesets/x/approve").catch((e) => e);
  expect(err).toBeInstanceOf(ApiError);
  expect(err).toMatchObject({ kind: "http", status: 403, message: "Cannot self-approve." });
});

it("reports transport failures as network errors, not HTTP failures", async () => {
  fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
  await expect(api("GET", "/a")).rejects.toMatchObject({ kind: "network", status: null });
});
