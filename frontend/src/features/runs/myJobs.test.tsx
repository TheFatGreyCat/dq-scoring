import type { Mock } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, renderRoute } from "../../test/render";
import { RunsPage } from "./RunsPage";
import { RunStatusPage } from "./RunStatusPage";
import { RUN_POLL_INTERVAL_MS } from "./useRunStatus";

const RUN_ID = "11111111-1111-4111-8111-111111111111";
const OTHER_ID = "99999999-9999-4999-8999-999999999999";

const run = (id: string, status: string, extra = {}) => ({
  run_id: id, tenant_id: "t", snapshot_id: "s", ruleset_id: "r", policy_id: "p", status,
  created_at: "2026-10-07T10:00:00Z", completed_at: null, error_message: null, assessment_id: null,
  created_by: null, owned_by_me: true, ...extra,
});
const page = (items: unknown[]) => ({ items, total: items.length, page: 1, page_size: 25 });
const runStatus = (status: string) => ({
  run_id: RUN_ID, status, error_message: null, assessment_id: null, updated_at: "2026-10-07T10:00:00Z",
  created_at: "2026-10-07T10:00:00Z", started_at: null, completed_at: null, heartbeat_at: null, attempt_count: 1,
  created_by: null, owned_by_me: true,
});
const event = (n: number, type = "RUN_QUEUED", extra = {}) => ({
  event_id: `00000000-0000-4000-8000-00000000000${n}`, event_type: type, attempt_count: 1,
  lease_generation: 1, created_at: `2026-10-07T10:00:0${n}Z`, error_code: null, ...extra,
});

const inList = () => within(screen.getByRole("list"));
const urlOf = (call: unknown[]) => new URL(String(call[0]), "http://localhost");
let fetchMock: Mock;
beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("my jobs list", () => {
  it("requests only the caller's jobs and polls until nothing is active", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const responses = [page([run(RUN_ID, "RUNNING")]), page([run(RUN_ID, "SUCCEEDED")])];
    fetchMock.mockImplementation(async () => json(200, responses.shift() ?? page([run(RUN_ID, "SUCCEEDED")])));

    renderRoute(<RunsPage mine />, "/my-jobs", "/my-jobs");
    await waitFor(() => expect(inList().getByText("Running")).toBeInTheDocument());
    expect(urlOf(fetchMock.mock.calls[0]).searchParams.get("scope")).toBe("mine");

    await act(() => vi.advanceTimersByTimeAsync(RUN_POLL_INTERVAL_MS));
    await waitFor(() => expect(inList().getByText("Succeeded")).toBeInTheDocument());

    const settled = fetchMock.mock.calls.length;
    await act(() => vi.advanceTimersByTimeAsync(RUN_POLL_INTERVAL_MS * 4));
    expect(fetchMock.mock.calls.length).toBe(settled);
  });

  it("does not let the URL widen the scope", async () => {
    fetchMock.mockResolvedValue(json(200, page([run(RUN_ID, "QUEUED")])));
    renderRoute(<RunsPage mine />, "/my-jobs", "/my-jobs?scope=workspace&created_by=someone-else");
    await screen.findByRole("link", { name: RUN_ID.slice(0, 8) });
    const sent = urlOf(fetchMock.mock.calls[0]).searchParams;
    expect(sent.get("scope")).toBe("mine");
    expect(sent.get("created_by")).toBeNull();
  });

  it("keeps rows and reports stale data on transport loss instead of marking jobs failed", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let calls = 0;
    fetchMock.mockImplementation(async () => {
      if (++calls === 1) return json(200, page([run(RUN_ID, "RUNNING")]));
      throw new TypeError("Failed to fetch");
    });
    renderRoute(<RunsPage mine />, "/my-jobs", "/my-jobs");
    await waitFor(() => expect(inList().getByText("Running")).toBeInTheDocument());
    await act(() => vi.advanceTimersByTimeAsync(RUN_POLL_INTERVAL_MS));
    expect(await screen.findByText(/connection lost/i)).toBeInTheDocument();
    expect(inList().getByText("Running")).toBeInTheDocument();
    expect(inList().queryByText("Failed")).not.toBeInTheDocument();
  });

  it("links each job to its detail with the personal scope", async () => {
    fetchMock.mockResolvedValue(json(200, page([run(RUN_ID, "QUEUED")])));
    renderRoute(<RunsPage mine />, "/my-jobs", "/my-jobs");
    const link = await screen.findByRole("link", { name: RUN_ID.slice(0, 8) });
    expect(link.getAttribute("href")).toBe(`/runs/${RUN_ID}?scope=mine`);
  });

  it("leaves scope to the server default on the legacy /runs history and plain links", async () => {
    fetchMock.mockResolvedValue(json(200, page([run(OTHER_ID, "FAILED", { owned_by_me: false })])));
    renderRoute(<RunsPage />, "/runs", "/runs");
    const link = await screen.findByRole("link", { name: OTHER_ID.slice(0, 8) });
    expect(urlOf(fetchMock.mock.calls[0]).searchParams.get("scope")).toBeNull();
    expect(link.getAttribute("href")).toBe(`/runs/${OTHER_ID}`);
  });
});

describe("run detail timeline", () => {
  const route = (calls: Record<string, () => Response>) =>
    fetchMock.mockImplementation(async (url: string) => {
      const path = new URL(url, "http://localhost").pathname;
      if (path.endsWith("/execution")) return json(200, { attempts: [], request: {}, observed_scope: "RUN_ATTEMPT" });
      const key = Object.keys(calls).find(k => path.endsWith(k));
      if (!key) throw new Error(`unexpected ${path}`);
      return calls[key]();
    });

  it("pages events with the server cursor", async () => {
    const user = userEvent.setup();
    route({
      "/status": () => json(200, runStatus("SUCCEEDED")),
      "/events": () => json(200, { items: [event(1)], next_cursor: "CURSOR-1" }),
    });
    renderRoute(<RunStatusPage />, "/runs/:runId", `/runs/${RUN_ID}`);
    await user.click(await screen.findByRole("button", { name: /load more/i }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(c => urlOf(c).searchParams.get("cursor") === "CURSOR-1")).toBe(true),
    );
  });

  it("keeps loaded events through a terminal transition even when the final events refresh fails", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    let statusCalls = 0;
    let failEvents = false;
    fetchMock.mockImplementation(async (url: string) => {
      const target = new URL(url, "http://localhost");
      if (target.pathname.endsWith("/execution")) return json(200, { attempts: [], request: {}, observed_scope: "RUN_ATTEMPT" });
      if (target.pathname.endsWith("/status")) return json(200, runStatus(++statusCalls === 1 ? "RUNNING" : "FAILED"));
      if (failEvents) throw new TypeError("Failed to fetch");
      if (target.searchParams.get("cursor") === "CURSOR-1") return json(200, { items: [event(2, "RUN_CLAIMED")], next_cursor: null });
      return json(200, { items: [event(1)], next_cursor: "CURSOR-1" });
    });
    renderRoute(<RunStatusPage />, "/runs/:runId", `/runs/${RUN_ID}`);
    await user.click(await screen.findByRole("button", { name: /load more/i }));
    expect(await screen.findByText("Claimed by worker")).toBeInTheDocument();
    expect(screen.getByText("Queued", { selector: "span.font-medium" })).toBeInTheDocument();

    failEvents = true;
    await act(() => vi.advanceTimersByTimeAsync(RUN_POLL_INTERVAL_MS));
    expect(await screen.findByText("Run failed")).toBeInTheDocument();
    expect(screen.getByText("Claimed by worker")).toBeInTheDocument();
    expect(screen.getByText("Queued", { selector: "span.font-medium" })).toBeInTheDocument();
  });

  it("shows not-found for another owner's job and stops polling it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fetchMock.mockImplementation(async () => json(404, { title: "Not Found", status: 404, detail: "Evaluation Run not found." }));
    renderRoute(<RunStatusPage />, "/runs/:runId", `/runs/${OTHER_ID}?scope=mine`);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    const settled = fetchMock.mock.calls.length;
    await act(() => vi.advanceTimersByTimeAsync(RUN_POLL_INTERVAL_MS * 4));
    expect(fetchMock.mock.calls.length).toBe(settled);
    expect(screen.queryByText("Running")).not.toBeInTheDocument();
  });

  it("treats a lost connection mid-run as stale, not as a failed job", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let calls = 0;
    fetchMock.mockImplementation(async (url: string) => {
      if (new URL(url, "http://localhost").pathname.endsWith("/events")) return json(200, { items: [], next_cursor: null });
      if (new URL(url, "http://localhost").pathname.endsWith("/execution")) return json(200, { attempts: [], request: {}, observed_scope: "RUN_ATTEMPT" });
      if (++calls === 1) return json(200, runStatus("RUNNING"));
      throw new TypeError("Failed to fetch");
    });
    renderRoute(<RunStatusPage />, "/runs/:runId", `/runs/${RUN_ID}`);
    expect(await screen.findByText("Running")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(RUN_POLL_INTERVAL_MS));
    expect(await screen.findByText(/reconnecting/i)).toBeInTheDocument();
    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(screen.queryByText("Run failed")).not.toBeInTheDocument();
  });
});
