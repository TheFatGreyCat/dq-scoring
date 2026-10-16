import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi, type Mock } from "vitest";
import { session } from "../../api/client";
import { renderRoute, json } from "../../test/render";
import { PrivacyPanel } from "./PrivacyPanel";

const SNAPSHOT_ID = "00000000-0000-0000-0000-000000000001";
const ASSET_ID = "00000000-0000-0000-0000-000000000002";
let fetchMock: Mock;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  window.URL.createObjectURL = vi.fn(() => "blob:mock-export");
  window.URL.revokeObjectURL = vi.fn();
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

it("renders sensitive findings table and asset protection policy", async () => {
  fetchMock.mockImplementation((url: string, opts?: RequestInit) => {
    if (url.includes("/auth/me")) {
      return Promise.resolve(json(200, {
        user_id: "u-1",
        tenant_id: "t-1",
        email: "owner@test.com",
        role: "DATA_OWNER",
      }));
    }
    if (url.includes(`/snapshots/${SNAPSHOT_ID}/sensitive-findings`)) {
      return Promise.resolve(json(200, {
        scan_status: "COMPLETE",
        detector_revision: "builtin-v1",
        findings: {
          items: [
            {
              finding_id: "f-1",
              column_name: "email",
              path: "",
              category: "BASIC_PERSONAL_DATA",
              detector_code: "EMAIL",
              matched_count: 5,
              observed_count: 10,
              status: "DETECTED",
              detector_revision: "builtin-v1",
              method: "VALUE_PATTERN",
            },
          ],
          total: 1,
          page: 1,
          page_size: 25,
        },
      }));
    }
    if (url.includes(`/assets/${ASSET_ID}/protection-policy`)) {
      if (opts?.method === "PUT") {
        return Promise.resolve(json(200, {
          asset_id: ASSET_ID,
          version: 2,
          categories: ["BASIC_PERSONAL_DATA", "SENSITIVE_PERSONAL_DATA"],
          unsupported_policies: 0,
        }));
      }
      return Promise.resolve(json(200, {
        asset_id: ASSET_ID,
        version: 1,
        categories: ["BASIC_PERSONAL_DATA"],
        unsupported_policies: 0,
      }));
    }
    return Promise.resolve(json(404, { detail: "not found" }));
  });

  renderRoute(
    <PrivacyPanel assetId={ASSET_ID} snapshotId={SNAPSHOT_ID} />,
    "/snapshots/:id",
    `/snapshots/${SNAPSHOT_ID}`,
  );

  // 1. Findings table assertions
  expect(await screen.findByText("email")).toBeInTheDocument();
  expect(screen.getByText("EMAIL")).toBeInTheDocument();
  expect(screen.getByText("5 / 10")).toBeInTheDocument();
  expect(screen.getByText("DETECTED")).toBeInTheDocument();

  // 2. Policy assertions
  expect(await screen.findByText("Asset Protection Policy")).toBeInTheDocument();
  expect(screen.getByText("Export Masked Parquet")).toBeInTheDocument();

  expect(screen.queryByText(/Additional Columns/)).not.toBeInTheDocument();

  // 3. Finding review requires a reason
  const confirmBtn = screen.getByRole("button", { name: "Confirm" });
  expect(confirmBtn).toBeDisabled();
  await userEvent.type(screen.getByLabelText("Review reason"), "Synthetic review");
  await userEvent.click(confirmBtn);

  await waitFor(() => {
    const patchCall = fetchMock.mock.calls.find((call) =>
      typeof call[0] === "string" && call[0].includes("/sensitive-findings/f-1")
    );
    expect(patchCall?.[1]?.method).toBe("PATCH");
    expect(JSON.parse(String(patchCall?.[1]?.body))).toEqual({
      expected_status: "DETECTED", status: "CONFIRMED", reason: "Synthetic review",
    });
  });
});

it("refreshes token once on 401 and retries masked export", async () => {
  fetchMock.mockImplementation((url: string, opts?: RequestInit) => {
    if (url.includes("/auth/me")) {
      return Promise.resolve(json(200, { user_id: "u-1", tenant_id: "t-1", email: "owner@test.com", role: "DATA_OWNER" }));
    }
    if (url.includes(`/snapshots/${SNAPSHOT_ID}/sensitive-findings`)) {
      return Promise.resolve(json(200, {
        scan_status: "COMPLETE",
        detector_revision: "builtin-v1",
        findings: { items: [], total: 0, page: 1, page_size: 25 },
      }));
    }
    if (url.includes(`/snapshots/${SNAPSHOT_ID}/column-classifications`)) {
      return Promise.resolve(json(200, {
        asset_id: ASSET_ID, snapshot_id: SNAPSHOT_ID, version: 1, scan_status: "COMPLETE", scan_stale: false,
        columns: [],
      }));
    }
    if (url.includes(`/assets/${ASSET_ID}/protection-policy`)) {
      return Promise.resolve(json(200, { asset_id: ASSET_ID, version: 1, categories: [], unsupported_policies: 0 }));
    }
    if (url.includes("/auth/refresh")) {
      return Promise.resolve(json(200, {
        access_token: "refreshed-token",
        refresh_token: "new-refresh",
        token_type: "bearer",
        expires_in: 3600,
      }));
    }
    if (url.includes(`/assets/${ASSET_ID}/masked-export`)) {
      const auth = (opts?.headers as Record<string, string>)?.Authorization;
      if (auth === "Bearer refreshed-token") {
        return Promise.resolve(new Response(new Blob(["PARQUET-DATA"]), { status: 200 }));
      }
      return Promise.resolve(json(401, { status: 401, title: "Unauthorized", detail: "Token expired" }));
    }
    return Promise.resolve(json(404, { detail: "not found" }));
  });

  renderRoute(
    <PrivacyPanel assetId={ASSET_ID} snapshotId={SNAPSHOT_ID} />,
    "/snapshots/:id",
    `/snapshots/${SNAPSHOT_ID}`,
  );

  const exportBtn = await screen.findByTestId("export-masked-btn");
  await userEvent.click(exportBtn);

  await waitFor(() => {
    expect(window.URL.createObjectURL).toHaveBeenCalledTimes(1);
  });

  const refreshCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes("/auth/refresh"));
  expect(refreshCalls).toHaveLength(1);

  const exportCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes("/masked-export"));
  expect(exportCalls).toHaveLength(2);
  expect(exportCalls[0][1]).toMatchObject({
    cache: "no-store",
    headers: expect.objectContaining({ Authorization: "Bearer mock-token" }),
  });
  expect(exportCalls[1][1]).toMatchObject({
    cache: "no-store",
    headers: expect.objectContaining({ Authorization: "Bearer refreshed-token" }),
  });
});

it("submits bulk column classification changes in single payload", async () => {
  let savedPayload: unknown = null;
  fetchMock.mockImplementation((url: string, opts?: RequestInit) => {
    if (url.includes("/auth/me")) {
      return Promise.resolve(json(200, { user_id: "u-1", tenant_id: "t-1", email: "owner@test.com", role: "DATA_OWNER" }));
    }
    if (url.includes(`/snapshots/${SNAPSHOT_ID}/sensitive-findings`)) {
      return Promise.resolve(json(200, {
        scan_status: "COMPLETE", detector_revision: "builtin-v1",
        findings: { items: [], total: 0, page: 1, page_size: 25 },
      }));
    }
    if (url.includes(`/assets/${ASSET_ID}/protection-policy`)) {
      return Promise.resolve(json(200, { asset_id: ASSET_ID, version: 1, categories: [], unsupported_policies: 0 }));
    }
    if (url.includes(`/snapshots/${SNAPSHOT_ID}/column-classifications`)) {
      return Promise.resolve(json(200, {
        asset_id: ASSET_ID,
        snapshot_id: SNAPSHOT_ID,
        version: 1,
        scan_status: "COMPLETE",
        scan_stale: false,
        columns: [
          {
            column_name: "email",
            declared_category: null,
            detected_categories: ["BASIC_PERSONAL_DATA"],
            effective_categories: ["BASIC_PERSONAL_DATA"],
            protected: true,
            conflict: false,
            reason: null,
          },
          {
            column_name: "notes",
            declared_category: null,
            detected_categories: [],
            effective_categories: ["STANDARD_DATA"],
            protected: false,
            conflict: false,
            reason: null,
          },
        ],
      }));
    }
    if (url.includes(`/assets/${ASSET_ID}/column-classifications`) && opts?.method === "PUT") {
      savedPayload = JSON.parse(String(opts.body));
      return Promise.resolve(json(200, {
        asset_id: ASSET_ID,
        snapshot_id: SNAPSHOT_ID,
        version: 2,
        scan_status: "COMPLETE",
        scan_stale: false,
        columns: [
          {
            column_name: "email",
            declared_category: "CONFIDENTIAL_BUSINESS_DATA",
            detected_categories: ["BASIC_PERSONAL_DATA"],
            effective_categories: ["CONFIDENTIAL_BUSINESS_DATA"],
            protected: true,
            conflict: false,
            reason: "Synthetic bulk classification update",
          },
          {
            column_name: "notes",
            declared_category: "CONFIDENTIAL_BUSINESS_DATA",
            detected_categories: [],
            effective_categories: ["CONFIDENTIAL_BUSINESS_DATA"],
            protected: true,
            conflict: false,
            reason: "Synthetic bulk classification update",
          },
        ],
      }));
    }
    return Promise.resolve(json(404, { detail: "not found" }));
  });

  renderRoute(
    <PrivacyPanel assetId={ASSET_ID} snapshotId={SNAPSHOT_ID} />,
    "/snapshots/:id",
    `/snapshots/${SNAPSHOT_ID}`,
  );

  const emailCheckbox = await screen.findByLabelText("Select email");
  const notesCheckbox = screen.getByLabelText("Select notes");
  await userEvent.click(emailCheckbox);
  await userEvent.click(notesCheckbox);

  expect(screen.getByText("2 column(s) selected")).toBeInTheDocument();

  const bulkSelect = screen.getByLabelText("Declared Classification");
  await userEvent.selectOptions(bulkSelect, "CONFIDENTIAL_BUSINESS_DATA");
  await userEvent.click(screen.getByRole("button", { name: "Apply to Selected" }));

  const reasonInput = screen.getByPlaceholderText(/Enter reason for this classification change/);
  await userEvent.type(reasonInput, "Synthetic bulk classification update");

  const saveBtn = screen.getByRole("button", { name: "Save Classifications" });
  await userEvent.click(saveBtn);

  await waitFor(() => {
    expect(savedPayload).toEqual({
      snapshot_id: SNAPSHOT_ID,
      expected_version: 1,
      changes: [
        { column_name: "email", category: "CONFIDENTIAL_BUSINESS_DATA", reason: "Synthetic bulk classification update" },
        { column_name: "notes", category: "CONFIDENTIAL_BUSINESS_DATA", reason: "Synthetic bulk classification update" },
      ],
    });
  });
});

it("surfaces version conflict alert and preserves draft changes", async () => {
  fetchMock.mockImplementation((url: string, opts?: RequestInit) => {
    if (url.includes("/auth/me")) {
      return Promise.resolve(json(200, { user_id: "u-1", tenant_id: "t-1", email: "owner@test.com", role: "DATA_OWNER" }));
    }
    if (url.includes(`/snapshots/${SNAPSHOT_ID}/sensitive-findings`)) {
      return Promise.resolve(json(200, {
        scan_status: "COMPLETE", detector_revision: "builtin-v1",
        findings: { items: [], total: 0, page: 1, page_size: 25 },
      }));
    }
    if (url.includes(`/assets/${ASSET_ID}/protection-policy`)) {
      return Promise.resolve(json(200, { asset_id: ASSET_ID, version: 1, categories: [], unsupported_policies: 0 }));
    }
    if (url.includes(`/snapshots/${SNAPSHOT_ID}/column-classifications`)) {
      return Promise.resolve(json(200, {
        asset_id: ASSET_ID,
        snapshot_id: SNAPSHOT_ID,
        version: 1,
        scan_status: "COMPLETE",
        scan_stale: false,
        columns: [
          {
            column_name: "email",
            declared_category: null,
            detected_categories: ["BASIC_PERSONAL_DATA"],
            effective_categories: ["BASIC_PERSONAL_DATA"],
            protected: true,
            conflict: false,
            reason: null,
          },
        ],
      }));
    }
    if (url.includes(`/assets/${ASSET_ID}/column-classifications`) && opts?.method === "PUT") {
      return Promise.resolve(json(409, {
        title: "Conflict",
        status: 409,
        detail: "VERSION_CONFLICT",
      }));
    }
    return Promise.resolve(json(404, { detail: "not found" }));
  });

  renderRoute(
    <PrivacyPanel assetId={ASSET_ID} snapshotId={SNAPSHOT_ID} />,
    "/snapshots/:id",
    `/snapshots/${SNAPSHOT_ID}`,
  );

  const emailCheckbox = await screen.findByLabelText("Select email");
  await userEvent.click(emailCheckbox);

  const bulkSelect = screen.getByLabelText("Declared Classification");
  await userEvent.selectOptions(bulkSelect, "CONFIDENTIAL_BUSINESS_DATA");
  await userEvent.click(screen.getByRole("button", { name: "Apply to Selected" }));

  const reasonInput = screen.getByPlaceholderText(/Enter reason for this classification change/);
  await userEvent.type(reasonInput, "Concurrent edit test");

  const saveBtn = screen.getByRole("button", { name: "Save Classifications" });
  await userEvent.click(saveBtn);

  expect(
    await screen.findByText(/Protection policy was updated by another user \(version conflict\)/)
  ).toBeInTheDocument();

  expect(screen.getByRole("button", { name: "Discard Draft Changes" })).toBeInTheDocument();
});
