import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, renderRoute } from "../../test/render";
import { RunStatusPage } from "./RunStatusPage";
import { RunWizardPage } from "./RunWizardPage";
import { RUN_POLL_INTERVAL_MS } from "./useRunStatus";

const RUN_ID = "11111111-1111-4111-8111-111111111111";
const ASSESSMENT_ID = "22222222-2222-4222-8222-222222222222";
const status = (s: string, extra = {}) => ({ run_id: RUN_ID, status: s, error_message: null, assessment_id: null, updated_at: "2026-10-07T10:00:00Z", ...extra });

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("run status polling", () => {
  it("polls while active and stops at SUCCEEDED, linking the scorecard", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const responses = [status("QUEUED"), status("RUNNING"), status("SUCCEEDED", { assessment_id: ASSESSMENT_ID })];
    fetchMock.mockImplementation(async () => json(200, responses.shift() ?? status("SUCCEEDED", { assessment_id: ASSESSMENT_ID })));

    renderRoute(<RunStatusPage />, "/runs/:runId", `/runs/${RUN_ID}`);
    expect(await screen.findByText("Queued")).toBeInTheDocument();

    await act(() => vi.advanceTimersByTimeAsync(RUN_POLL_INTERVAL_MS));
    expect(await screen.findByText("Running")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(RUN_POLL_INTERVAL_MS));
    expect(await screen.findByText("Succeeded")).toBeInTheDocument();
    expect(document.querySelector(`a[href="/assessments/${ASSESSMENT_ID}"]`)).toBeInTheDocument();

    const callsAtTerminal = fetchMock.mock.calls.length;
    await act(() => vi.advanceTimersByTimeAsync(RUN_POLL_INTERVAL_MS * 4));
    expect(fetchMock.mock.calls.length).toBe(callsAtTerminal);
  });

  it("shows FAILED with sanitized error and no assessment link", async () => {
    fetchMock.mockResolvedValue(json(200, status("FAILED", { error_message: "Storage unavailable" })));
    renderRoute(<RunStatusPage />, "/runs/:runId", `/runs/${RUN_ID}`);
    expect(await screen.findByText("Run failed")).toBeInTheDocument();
    expect(screen.getByText("Storage unavailable")).toBeInTheDocument();
    expect(document.querySelector(`a[href^="/assessments/"]`)).not.toBeInTheDocument();
  });
});

describe("run wizard", () => {
  const ids = {
    snapshot: "33333333-3333-4333-8333-333333333333",
    ruleset: "44444444-4444-4444-8444-444444444444",
    policy: "55555555-5555-4555-8555-555555555555",
  };

  it("reuses the same idempotency key when retrying after an unknown outcome", async () => {
    const user = userEvent.setup();
    let attempts = 0;
    const page = (items: unknown[]) => ({ items, total: items.length, page: 1, page_size: 100 });
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      const path = new URL(url, "http://localhost").pathname;
      if (init?.method === "POST") {
        if (++attempts === 1) throw new TypeError("Failed to fetch");
        return json(202, { run_id: RUN_ID, snapshot_id: ids.snapshot, status: "QUEUED" });
      }
      if (path.endsWith(`/snapshots/${ids.snapshot}`)) return json(200, { snapshot_id: ids.snapshot, asset_id: "asset", schema_definition: { columns: [] } });
      if (path.endsWith("/rulesets")) return json(200, page([{ ruleset_id: ids.ruleset, name: "Approved rules", status: "ACTIVE" }]));
      if (path.endsWith("/policies")) return json(200, page([{ policy_id: ids.policy, name: "Approved policy", status: "ACTIVE" }]));
      return json(200, page([]));
    });

    const { router } = renderRoute(<RunWizardPage />, "/runs/new", `/runs/new?snapshot=${ids.snapshot}`);
    await screen.findByRole("option", { name: "Approved rules" });
    await user.selectOptions(screen.getByRole("combobox", { name: "Rulesets" }), ids.ruleset);
    await user.selectOptions(screen.getByRole("combobox", { name: "Policies" }), ids.policy);
    await user.click(screen.getByRole("button", { name: /trigger evaluation/i }));

    await screen.findByRole("button", { name: "Retry" });
    await user.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(router.state.location.pathname).toBe(`/runs/${RUN_ID}`));
    const keys = fetchMock.mock.calls.filter(([, init]) => init?.method === "POST").map(([, init]) => JSON.parse(init.body).idempotency_key);
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });
});
