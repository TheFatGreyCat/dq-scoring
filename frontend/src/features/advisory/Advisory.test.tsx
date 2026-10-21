import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi, type Mock } from "vitest";
import { session } from "../../api/client";
import { json, renderRoute } from "../../test/render";
import { AiRecommendationsPanel } from "./AiRecommendationsPanel";
import { AssessmentNarrativePanel } from "./AssessmentNarrativePanel";

const ID = "77777777-7777-4777-8777-777777777777";
let fetchMock: Mock;
let aiOn = true;
let role = "DATA_OWNER";

const rule = (code: string) => ({
  rule: { rule_code: code, dimension: "COMPLETENESS", rule_type: "NON_NULL", parameters: { column: "fare" }, null_policy: "fail", is_required: false, is_critical: false, gate_enabled: true, score_enabled: true, contribution_weight: 1, acceptance_threshold: null, is_advisory: false },
  reason_code: "X", reason_params: {}, sample_rows: 10, is_sample: true, source: "LLM",
});
const provenance = { engine: "HYBRID", source: "HEURISTIC_FALLBACK", model: "m1", prompt_version: "v1", context_sha256: "h", generated_at: "2026-10-16T10:00:00Z", fallback: true, fallback_code: "AI_TIMEOUT", candidates_rejected: 1, columns_sent: 3 };
const calls = (frag: string, method = "GET") =>
  fetchMock.mock.calls.filter(([u, o]) => String(u).includes(frag) && (o?.method ?? "GET") === method);

beforeEach(() => {
  aiOn = true;
  role = "DATA_OWNER";
  fetchMock = vi.fn((url: string, opts?: RequestInit) => {
    const m = opts?.method ?? "GET";
    if (url.includes("/auth/me")) return Promise.resolve(json(200, { user_id: "u", tenant_id: "t", email: "a@b.c", role }));
    if (url.includes("/ai/status")) return Promise.resolve(json(200, { enabled: aiOn, model: "m1", recommendations: aiOn, narrative: aiOn }));
    if (url.includes("/recommendations/ai") && m === "POST")
      return Promise.resolve(json(200, { rules: [rule("AI_FARE")], ruleset_templates: [], policy_templates: [], warnings: [], provenance }));
    if (url.includes("/narrative") && m === "GET") return Promise.resolve(json(404, { title: "nf", status: 404, error_code: "NARRATIVE_NOT_FOUND" }));
    if (url.includes("/narrative") && m === "POST")
      return Promise.resolve(json(201, { report_id: "r", assessment_id: ID, assessment_hash: "h1", narrative: "<img src=x onerror=alert(1)> **bold** [l](javascript:x)", cited_rules: [], model: "m1", prompt_version: "v", context_sha256: "c", advisory: true, created_at: "2026-10-16T10:00:00Z" }));
    return Promise.resolve(json(404, {}));
  });
  vi.stubGlobal("fetch", fetchMock);
  session.set({ access_token: "t", token_type: "bearer", expires_in: 3600, refresh_token: "r" }, "a@b.c");
});
afterEach(() => { session.clear(); vi.unstubAllGlobals(); });

it("never infers on mount; explicit click shows fallback provenance and merges only selected items", async () => {
  const onMerge = vi.fn();
  renderRoute(<AiRecommendationsPanel snapshotId={ID} onMerge={onMerge} />, "/x", "/x");
  const generate = await screen.findByRole("button", { name: /generate ai suggestions/i });
  expect(calls("/recommendations/ai", "POST")).toHaveLength(0);
  await userEvent.click(generate);
  expect(await screen.findByText(/AI_TIMEOUT/)).toBeInTheDocument();
  expect(screen.getByText(/Heuristic \(fallback\)/)).toBeInTheDocument();
  const merge = screen.getByRole("button", { name: /add 0 selected/i });
  expect(merge).toBeDisabled();
  await userEvent.click(screen.getByRole("checkbox", { name: /AI_FARE/ }));
  await userEvent.click(screen.getByRole("button", { name: /add 1 selected/i }));
  expect(onMerge).toHaveBeenCalledTimes(1);
  expect(onMerge.mock.calls[0][0].map((r: { rule_code: string }) => r.rule_code)).toEqual(["AI_FARE"]);
  expect(JSON.parse(calls("/recommendations/ai", "POST")[0][1].body)).toMatchObject({ engine: "HYBRID", domain: "GENERAL" });
});

it("hides generation when AI is off or the role cannot write", async () => {
  aiOn = false;
  renderRoute(<AiRecommendationsPanel snapshotId={ID} onMerge={vi.fn()} />, "/x", "/x");
  await waitFor(() => expect(calls("/ai/status")).toHaveLength(1));
  expect(screen.queryByRole("button", { name: /generate/i })).not.toBeInTheDocument();
});

it("hides generation for viewers even when AI is enabled", async () => {
  role = "BUSINESS_VIEWER";
  renderRoute(<AiRecommendationsPanel snapshotId={ID} onMerge={vi.fn()} />, "/x", "/x");
  await waitFor(() => expect(calls("/auth/me")).toHaveLength(1));
  await waitFor(() => expect(calls("/ai/status")).toHaveLength(1));
  expect(screen.queryByRole("button", { name: /generate/i })).not.toBeInTheDocument();
});

it("narrative: absent report generates nothing on load; generated text renders as inert plaintext", async () => {
  renderRoute(<AssessmentNarrativePanel assessmentId={ID} assessmentHash="h1" />, "/x", "/x");
  const btn = await screen.findByRole("button", { name: /generate ai summary/i });
  expect(calls("/narrative", "POST")).toHaveLength(0);
  await userEvent.click(btn);
  const text = await screen.findByTestId("ai-narrative-text");
  expect(text.textContent).toContain("<img src=x onerror=alert(1)>");
  expect(text.querySelector("img, a, strong")).toBeNull();
});

it("narrative: renders nothing and no error when AI is off and no report exists", async () => {
  aiOn = false;
  renderRoute(<AssessmentNarrativePanel assessmentId={ID} assessmentHash="h1" />, "/x", "/x");
  await waitFor(() => expect(calls("/narrative")).toHaveLength(1));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("sends the chosen profile mode with the explicit request", async () => {
  renderRoute(<AiRecommendationsPanel snapshotId={ID} onMerge={vi.fn()} />, "/x", "/x");
  await userEvent.selectOptions(await screen.findByLabelText(/profile source/i), "FULL");
  await userEvent.click(screen.getByRole("button", { name: /generate ai suggestions/i }));
  await waitFor(() => expect(calls("/recommendations/ai", "POST")).toHaveLength(1));
  expect(JSON.parse(calls("/recommendations/ai", "POST")[0][1].body)).toMatchObject({ profile_mode: "FULL" });
});
