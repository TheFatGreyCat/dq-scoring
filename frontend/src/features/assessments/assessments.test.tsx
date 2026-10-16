import { screen, within } from "@testing-library/react";
import type { AssessmentDetail, QualityGate, RuleResult } from "../../api/types";
import { json, renderRoute } from "../../test/render";
import { PublicScorecardPage } from "./PublicScorecardPage";
import { AssessmentsPage, ScorecardPage } from "./ScorecardPage";

const ID = "66666666-6666-4666-8666-666666666666";

const rule = (over: Partial<RuleResult>): RuleResult => ({
  rule_id: crypto.randomUUID(),
  rule_code: "R1",
  dimension: "COMPLETENESS",
  target_column: "fare",
  rule_type: "NOT_NULL",
  measurement_status: "MEASURED",
  computed_score: 97.123456,
  passed_count: 97,
  failed_count: 3,
  missing_count: 0,
  miscast_count: 0,
  not_applicable_count: 0,
  total_observed: 100,
  violations_count: 3,
  weight: 1,
  is_required: true,
  is_critical: false,
  is_advisory: false,
  evidence_samples: null,
  error_message: null,
  ...over,
});

const assessment = (over: Partial<AssessmentDetail> = {}): AssessmentDetail => ({
  assessment_id: ID,
  tenant_id: "t",
  run_id: "r",
  snapshot_id: "s",
  dq_score: 91.256,
  publication_status: "PUBLISHED",
  coverage_ratio: 0.9,
  quality_gate: "PASS",
  assessment_hash: "abc123",
  created_at: "2026-10-07T10:00:00Z",
  dimension_results: [
    { dimension: "COMPLETENESS", dimension_score: 97.123456, coverage_ratio: 1 },
    { dimension: "TIMELINESS", dimension_score: null, coverage_ratio: 0 },
    { dimension: "UNIQUENESS", dimension_score: null, coverage_ratio: null },
  ],
  rule_results: [
    rule({}),
    rule({ rule_code: "R2", dimension: "TIMELINESS", measurement_status: "NOT_MEASURABLE", computed_score: null }),
    rule({ rule_code: "R3", dimension: "UNIQUENESS", measurement_status: "NOT_APPLICABLE", computed_score: null }),
    rule({ rule_id: null, rule_code: "OUTLIER_IQR_fare", dimension: "ACCURACY", rule_type: "OUTLIER", is_advisory: true, is_required: false, weight: 0, computed_score: null }),
  ],
  ...over,
});

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

it("renders a WITHHELD null score as an em dash, never zero, with an explanation", async () => {
  fetchMock.mockResolvedValue(json(200, assessment({ dq_score: null, publication_status: "WITHHELD", quality_gate: "ERROR" })));
  renderRoute(<ScorecardPage />, "/assessments/:assessmentId", `/assessments/${ID}`);
  expect(await screen.findByTestId("dq-score")).toHaveTextContent(/^—$/);
  expect(screen.getByText("Withheld")).toBeInTheDocument();
  expect(screen.getByText(/required measurement failed technically/i)).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /public view/i })).not.toBeInTheDocument();
});

it("labels null dimensions as Not measurable / Not applicable and formats only for display", async () => {
  fetchMock.mockResolvedValue(json(200, assessment()));
  renderRoute(<ScorecardPage />, "/assessments/:assessmentId", `/assessments/${ID}`);
  const dims = await screen.findByRole("region", { name: "Dimensions" });
  expect(within(dims).getByText("Not measurable")).toBeInTheDocument();
  expect(within(dims).getByText("Not applicable")).toBeInTheDocument();
  expect(within(dims).getAllByText("No rules").length).toBeGreaterThan(0);
  expect(screen.getByTestId("dq-score")).toHaveTextContent("91.26");
});

it.each<[QualityGate, string]>([
  ["PASS", "PASS"],
  ["WARN", "WARN"],
  ["FAIL", "FAIL"],
  ["ERROR", "ERROR"],
  ["INSUFFICIENT_EVIDENCE", "Insufficient evidence"],
])("shows the server gate %s as returned (text label, not colour alone)", async (gate, label) => {
  // A high score with a FAIL gate must still show FAIL: no client re-scoring.
  fetchMock.mockResolvedValue(json(200, assessment({ dq_score: 99, quality_gate: gate })));
  renderRoute(<ScorecardPage />, "/assessments/:assessmentId", `/assessments/${ID}`);
  expect(await screen.findByText(label)).toBeInTheDocument();
});

it("renders advisory outlier rows that have no rule_id", async () => {
  fetchMock.mockResolvedValue(json(200, assessment()));
  renderRoute(<ScorecardPage />, "/assessments/:assessmentId", `/assessments/${ID}`);
  expect((await screen.findAllByText("OUTLIER_IQR_fare")).length).toBeGreaterThan(0);
  expect(screen.getAllByText("Advisory · no score effect").length).toBeGreaterThan(0);
});

it("public scorecard calls only the public projection, unauthenticated", async () => {
  fetchMock.mockResolvedValue(
    json(200, { assessment_id: ID, dq_score: 88, publication_status: "PUBLISHED", coverage_ratio: 1, quality_gate: "PASS", assessment_hash: "h", created_at: "2026-10-07T10:00:00Z", dimensions: [] }),
  );
  renderRoute(<PublicScorecardPage />, "/public/assessments/:assessmentId", `/public/assessments/${ID}`);
  expect(await screen.findByTestId("dq-score")).toHaveTextContent("88.00");
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe(`/api/v1/assessments/${ID}/public`);
  expect(init.headers.Authorization).toBeUndefined();
});

it("public scorecard shows a neutral unavailable page for 404", async () => {
  fetchMock.mockResolvedValue(json(404, { title: "Not Found", status: 404, detail: "Assessment not found." }));
  renderRoute(<PublicScorecardPage />, "/public/assessments/:assessmentId", `/public/assessments/${ID}`);
  expect(await screen.findByText("Scorecard unavailable")).toBeInTheDocument();
});

it("AssessmentsPage renders paged summaries and real scorecard links", async () => {
  fetchMock.mockResolvedValue(
    json(200, {
      items: [
        {
          assessment_id: ID,
          tenant_id: "00000000-0000-0000-0000-000000000001",
          run_id: "11111111-1111-4111-8111-111111111111",
          snapshot_id: "22222222-2222-4222-8222-222222222222",
          dq_score: 95.5,
          publication_status: "PUBLISHED",
          coverage_ratio: 0.9,
          quality_gate: "PASS",
          assessment_hash: "hash123",
          created_at: "2026-10-08T10:00:00Z",
          published_at: "2026-10-08T10:05:00Z",
        },
      ],
      total: 1,
      page: 1,
      page_size: 25,
    }),
  );
  renderRoute(<AssessmentsPage />, "/assessments", "/assessments");
  expect(await screen.findByText("95.50")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /open scorecard/i })).toHaveAttribute(
    "href",
    `/assessments/${ID}`,
  );
});
