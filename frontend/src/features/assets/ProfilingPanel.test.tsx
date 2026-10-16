import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import type { ColumnClassification, DatasetPreview, SnapshotResponse } from "../../api/types";
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

it("hides extrema for protected columns while exposing unprotected extrema", () => {
  render(
    <I18nProvider>
      <ProfilingPanel
        snapshot={SNAPSHOT}
        previewData={PREVIEW_DATA}
        classifications={CLASSIFICATIONS}
      />
    </I18nProvider>
  );

  // Protected column: extrema are hidden to prevent re-identification
  expect(screen.queryByText(/50000/)).not.toBeInTheDocument();
  expect(screen.queryByText(/200000/)).not.toBeInTheDocument();

  // Unprotected column: extrema are shown
  expect(screen.getByText("1 … 100")).toBeInTheDocument();
});

it("displays extrema when column is not protected", () => {
  const unprotectedClassifications: ColumnClassification[] = [
    { ...CLASSIFICATIONS[0], protected: false, declared_category: "STANDARD_DATA" },
    CLASSIFICATIONS[1],
  ];

  render(
    <I18nProvider>
      <ProfilingPanel
        snapshot={SNAPSHOT}
        previewData={PREVIEW_DATA}
        classifications={unprotectedClassifications}
      />
    </I18nProvider>
  );

  expect(screen.getByText("50000 … 200000")).toBeInTheDocument();
  expect(screen.getByText("1 … 100")).toBeInTheDocument();
});
