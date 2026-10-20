import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import type { ComponentProps } from "react";
import type { ColumnClassification, DatasetPreview, DatasetProfile, SnapshotResponse } from "../../api/types";
import { I18nProvider } from "../../lib/i18n";
import { ProfilingPanel } from "./ProfilingPanel";

const SNAPSHOT: SnapshotResponse = {
  snapshot_id: "00000000-0000-0000-0000-000000000001",
  asset_id: "00000000-0000-0000-0000-000000000002",
  tenant_id: "00000000-0000-0000-0000-000000000003",
  source_kind: "OBJECT_FILE",
  source_descriptor: { format: "CSV", size_bytes: 2048 },
  captured_at: "2026-03-01T12:00:00Z",
  total_rows: 500,
  total_columns: 2,
  schema_definition: {
    columns: [
      { name: "salary", type: "NUMERIC" },
      { name: "item_count", type: "INTEGER" },
    ],
  },
};

const PREVIEW_DATA: DatasetPreview = {
  schema_definition: SNAPSHOT.schema_definition,
  preview: [],
  total_rows: 500,
  total_columns: 2,
  warnings: [],
  source_descriptor: {},
  profile: {
    sample_rows: 100,
    total_rows: 500,
    is_sample: true,
    columns: [
      {
        name: "salary",
        type_hint: "NUMERIC",
        min: 50000,
        max: 200000,
        null_count: 0,
        non_null_count: 100,
        distinct_count: 90,
        parse_success_count: 100,
        sample_rows: 100,
      },
      {
        name: "item_count",
        type_hint: "INTEGER",
        min: 1,
        max: 100,
        null_count: 0,
        non_null_count: 100,
        distinct_count: 50,
        parse_success_count: 100,
        sample_rows: 100,
      },
    ],
  },
};

const CLASSIFICATIONS: ColumnClassification[] = [
  {
    column_name: "salary",
    declared_category: "CONFIDENTIAL_BUSINESS_DATA",
    detected_categories: ["CONFIDENTIAL_BUSINESS_DATA"],
    effective_categories: ["CONFIDENTIAL_BUSINESS_DATA"],
    protected: true,
    conflict: false,
    reason: "Confidential compensation",
  },
  {
    column_name: "item_count",
    declared_category: "STANDARD_DATA",
    detected_categories: [],
    effective_categories: ["STANDARD_DATA"],
    protected: false,
    conflict: false,
    reason: null,
  },
];

function renderPanel(props: Partial<ComponentProps<typeof ProfilingPanel>> = {}) {
  render(
    <I18nProvider>
      <ProfilingPanel
        snapshot={SNAPSHOT}
        previewData={PREVIEW_DATA}
        classifications={CLASSIFICATIONS}
        {...props}
      />
    </I18nProvider>
  );
  fireEvent.click(screen.getByRole("tab", { name: /column profile|hồ sơ cột/i }));
}

const expandAll = () =>
  screen.getAllByRole("button", { expanded: false }).forEach((b) => fireEvent.click(b));

const BASE_PROFILE = PREVIEW_DATA.profile as unknown as DatasetProfile;

function withProfile(patch: Partial<DatasetProfile>): DatasetPreview {
  return { ...PREVIEW_DATA, profile: { ...BASE_PROFILE, ...patch } as unknown as DatasetPreview["profile"] };
}

it("never renders protected extrema or distinct counts; unprotected extrema appear on disclosure", () => {
  renderPanel();
  expandAll();
  expect(screen.queryByText(/50000/)).not.toBeInTheDocument();
  expect(screen.queryByText(/200000/)).not.toBeInTheDocument();
  expect(screen.queryByText("90")).not.toBeInTheDocument();
  expect(screen.getByText("1 … 100")).toBeInTheDocument();
});

it("fails closed before classifications load", () => {
  renderPanel({ classifications: undefined });
  expandAll();
  expect(screen.queryByText(/50000/)).not.toBeInTheDocument();
  expect(screen.queryByText("1 … 100")).not.toBeInTheDocument();
});

it("shows extrema when the column is not protected", () => {
  renderPanel({
    classifications: [
      { ...CLASSIFICATIONS[0], protected: false, declared_category: "STANDARD_DATA" },
      CLASSIFICATIONS[1],
    ],
  });
  expandAll();
  expect(screen.getByText("50000 … 200000")).toBeInTheDocument();
});

it("renders unavailable, not 0% or 100%, when the sample is empty", () => {
  const empty = withProfile({
    sample_rows: 0,
    columns: BASE_PROFILE.columns.map((c) => ({ ...c, sample_rows: 0, non_null_count: 0, parse_success_count: 0, distinct_count: 0 })),
  });
  renderPanel({ previewData: empty });
  const rows = screen.getAllByRole("row").slice(1);
  for (const row of rows) {
    expect(within(row).queryByText(/%/)).not.toBeInTheDocument();
  }
  expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
  expect(screen.queryByText("100.0%")).not.toBeInTheDocument();
});

it("leaves parse success unavailable when a column has no non-null values", () => {
  const allNull = withProfile({
    columns: BASE_PROFILE.columns.map((c) => ({ ...c, null_count: 100, non_null_count: 0, parse_success_count: 0 })),
  });
  renderPanel({ previewData: allNull });
  const row = screen.getByRole("button", { name: "item_count" }).closest("tr")!;
  const cells = within(row).getAllByRole("cell");
  expect(cells[2]).toHaveTextContent("0.0%");
  expect(cells[4]).toHaveTextContent("—");
});

it("uses each column's own sample denominator", () => {
  const mixed = withProfile({
    columns: [
      { ...BASE_PROFILE.columns[0], sample_rows: 100, non_null_count: 50 },
      { ...BASE_PROFILE.columns[1], sample_rows: 40, non_null_count: 20 },
    ],
  });
  renderPanel({ previewData: mixed });
  const fillOf = (name: string) =>
    within(screen.getByRole("button", { name }).closest("tr")!).getAllByRole("cell")[2];
  expect(fillOf("salary")).toHaveTextContent("50.0% (50 / 100)");
  expect(fillOf("item_count")).toHaveTextContent("50.0% (20 / 40)");
});

it("shows the weighted KPI fill only when every column has coverage", () => {
  const partial = withProfile({ columns: [BASE_PROFILE.columns[0]] });
  renderPanel({ previewData: partial });
  fireEvent.click(screen.getByRole("tab", { name: /sample|mẫu/i }));
  const kpi = screen.getByText(/fill rate|tỷ lệ điền/i, { selector: "dt" }).parentElement!;
  expect(kpi).toHaveTextContent("—");
});

it("handles a missing profile without throwing or inventing metrics", () => {
  renderPanel({ previewData: { ...PREVIEW_DATA, profile: {} } as unknown as DatasetPreview });
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(screen.queryByText(/%/)).not.toBeInTheDocument();
});

it("exposes subviews as an accessible tablist with arrow-key navigation", () => {
  renderPanel();
  const tabs = screen.getAllByRole("tab");
  expect(tabs).toHaveLength(3);
  expect(screen.getByRole("tab", { selected: true })).toBe(tabs[1]);
  fireEvent.keyDown(tabs[1], { key: "ArrowRight" });
  expect(tabs[2]).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", tabs[2].id);
});

it("sample search filters only the shown rows and distinguishes null from empty", () => {
  const preview: DatasetPreview = {
    ...PREVIEW_DATA,
    preview: [
      { salary: null, item_count: "" },
      { salary: 5, item_count: "alpha" },
    ],
  };
  renderPanel({ previewData: preview });
  fireEvent.click(screen.getByRole("tab", { name: /sample|mẫu/i }));
  expect(screen.getByText(/NULL/)).toBeInTheDocument();
  expect(screen.getByText(/empty string|chuỗi rỗng/i)).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("2");
  fireEvent.change(screen.getByRole("searchbox", { name: /^(search|tìm kiếm)$/i }), { target: { value: "zzz" } });
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("searchbox", { name: /^(search|tìm kiếm)$/i }), { target: { value: "alpha" } });
  expect(screen.getAllByRole("row")).toHaveLength(2);
});

it("reports a schema-only sample as empty rather than a blank table", () => {
  renderPanel({ previewData: { ...PREVIEW_DATA, preview: [] } });
  fireEvent.click(screen.getByRole("tab", { name: /sample|mẫu/i }));
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("0");
});
