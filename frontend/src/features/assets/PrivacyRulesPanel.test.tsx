import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi, type Mock } from "vitest";
import { session } from "../../api/client";
import { json, renderRoute } from "../../test/render";
import { PrivacyRulesPanel } from "./PrivacyRulesPanel";

const SNAPSHOT_ID = "00000000-0000-0000-0000-000000000001";
const ASSET_ID = "00000000-0000-0000-0000-000000000002";
let fetchMock: Mock;

const MOCK_RULE = {
  rule_id: "00000000-0000-0000-0000-000000000010",
  revision: 1,
  code: "RULE_EMAIL",
  kind: "BUILTIN" as const,
  category: "BASIC_PERSONAL_DATA" as const,
  enabled: true,
  builtin_code: "EMAIL",
  match_mode: "CONTAINS" as const,
  case_sensitive: false,
  columns: ["email"],
  pattern: null,
  created_at: "2026-03-01T00:00:00Z",
  created_by: "00000000-0000-0000-0000-000000000099",
};

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  session.set({
    access_token: "mock-token",
    token_type: "bearer",
    expires_in: 3600,
    refresh_token: "mock-refresh",
  }, "owner@test.com");
});

afterEach(() => {
  session.clear();
  vi.unstubAllGlobals();
});

it("runs PREVIEW scan and displays non-mutating preview findings table", async () => {
  fetchMock.mockImplementation((url: string, opts?: RequestInit) => {
    if (url.includes("/auth/me")) {
      return Promise.resolve(json(200, {
        user_id: "u-1",
        tenant_id: "t-1",
        email: "owner@test.com",
        role: "DATA_OWNER",
      }));
    }
    if (url.includes("/privacy-rules")) {
      return Promise.resolve(json(200, {
        items: [MOCK_RULE],
        total: 1,
        page: 1,
        page_size: 50,
      }));
    }
    if (url.includes(`/snapshots/${SNAPSHOT_ID}/sensitive-findings`)) {
      return Promise.resolve(json(200, {
        scan_status: "COMPLETE",
        detector_revision: "builtin-v1",
        scan_stale: false,
        scanned_at: "2026-03-01T00:00:00Z",
        config_version: 1,
        findings: { items: [], total: 0, page: 1, page_size: 1 },
      }));
    }
    if (url.includes(`/snapshots/${SNAPSHOT_ID}/privacy-scans`) && opts?.method === "POST") {
      const body = JSON.parse(String(opts.body));
      expect(body).toEqual({
        purpose: "PREVIEW",
        rule_id: MOCK_RULE.rule_id,
        revision: MOCK_RULE.revision,
      });
      return Promise.resolve(json(202, {
        scan_id: "00000000-0000-0000-0000-000000000050",
        snapshot_id: SNAPSHOT_ID,
        purpose: "PREVIEW",
        state: "COMPLETE",
        result_summary: { finding_count: 1 },
      }));
    }
    if (url.includes("/privacy-scans/00000000-0000-0000-0000-000000000050/findings")) {
      return Promise.resolve(json(200, {
        items: [
          {
            column_name: "email",
            path: "",
            detector_code: "EMAIL",
            category: "BASIC_PERSONAL_DATA",
            matched_count: 5,
            observed_count: 10,
          },
        ],
        total: 1,
        page: 1,
        page_size: 25,
      }));
    }
    if (url.includes("/privacy-scans/00000000-0000-0000-0000-000000000050")) {
      return Promise.resolve(json(200, {
        scan_id: "00000000-0000-0000-0000-000000000050",
        snapshot_id: SNAPSHOT_ID,
        purpose: "PREVIEW",
        state: "COMPLETE",
        result_summary: { finding_count: 1 },
      }));
    }
    return Promise.resolve(json(404, { detail: "not found" }));
  });

  renderRoute(
    <PrivacyRulesPanel
      assetId={ASSET_ID}
      snapshotId={SNAPSHOT_ID}
      snapshotColumns={["id", "email", "notes"]}
    />,
    "/snapshots/:id",
    `/snapshots/${SNAPSHOT_ID}`,
  );

  expect(await screen.findByText("RULE_EMAIL")).toBeInTheDocument();

  const testBtn = screen.getByRole("button", { name: "Try Rule" });
  await userEvent.click(testBtn);

  // Active scan preview card displays non-mutating preview findings
  expect(await screen.findByText("Rule Preview Results (Test Run)")).toBeInTheDocument();
  expect(screen.getByText("Preview (Does not persist findings)")).toBeInTheDocument();
  expect(screen.getByText("[COMPLETE]")).toBeInTheDocument();

  // Preview table contains the matched finding
  expect(await screen.findByText("5 / 10")).toBeInTheDocument();
  expect(screen.getByText("EMAIL")).toBeInTheDocument();
});

it("runs APPLY scan and renders scan completion banner", async () => {
  fetchMock.mockImplementation((url: string, opts?: RequestInit) => {
    if (url.includes("/auth/me")) {
      return Promise.resolve(json(200, {
        user_id: "u-1",
        tenant_id: "t-1",
        email: "owner@test.com",
        role: "DATA_OWNER",
      }));
    }
    if (url.includes("/privacy-rules")) {
      return Promise.resolve(json(200, {
        items: [MOCK_RULE],
        total: 1,
        page: 1,
        page_size: 50,
      }));
    }
    if (url.includes(`/snapshots/${SNAPSHOT_ID}/sensitive-findings`)) {
      return Promise.resolve(json(200, {
        scan_status: "COMPLETE",
        detector_revision: "builtin-v1",
        scan_stale: false,
        scanned_at: "2026-03-01T00:00:00Z",
        config_version: 1,
        findings: { items: [], total: 0, page: 1, page_size: 1 },
      }));
    }
    if (url.includes(`/snapshots/${SNAPSHOT_ID}/privacy-scans`) && opts?.method === "POST") {
      const body = JSON.parse(String(opts.body));
      expect(body).toEqual({ purpose: "APPLY" });
      return Promise.resolve(json(202, {
        scan_id: "00000000-0000-0000-0000-000000000060",
        snapshot_id: SNAPSHOT_ID,
        purpose: "APPLY",
        state: "COMPLETE",
        result_summary: { finding_count: 3 },
      }));
    }
    if (url.includes("/privacy-scans/00000000-0000-0000-0000-000000000060")) {
      return Promise.resolve(json(200, {
        scan_id: "00000000-0000-0000-0000-000000000060",
        snapshot_id: SNAPSHOT_ID,
        purpose: "APPLY",
        state: "COMPLETE",
        result_summary: { finding_count: 3 },
      }));
    }
    return Promise.resolve(json(404, { detail: "not found" }));
  });

  renderRoute(
    <PrivacyRulesPanel
      assetId={ASSET_ID}
      snapshotId={SNAPSHOT_ID}
      snapshotColumns={["id", "email", "notes"]}
    />,
    "/snapshots/:id",
    `/snapshots/${SNAPSHOT_ID}`,
  );

  expect(await screen.findByText("RULE_EMAIL")).toBeInTheDocument();

  const rescanBtn = screen.getByRole("button", { name: "Rescan & Apply" });
  await userEvent.click(rescanBtn);

  // Active scan card displays Apply title
  expect(await screen.findByText("Scan & Apply Results")).toBeInTheDocument();
  expect(screen.getByText("[COMPLETE]")).toBeInTheDocument();

  // In apply mode, the preview findings table is NOT rendered
  expect(screen.queryByText("Preview (Does not persist findings)")).not.toBeInTheDocument();
  expect(screen.queryByText("Matched / Obs")).not.toBeInTheDocument();
});
