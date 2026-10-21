/// <reference lib="es2024.promise" />

import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi, type Mock } from "vitest";
import { session } from "../../api/client";
import { json, renderRoute } from "../../test/render";
import { SemanticPanel } from "./SemanticPanel";

const ID = "77777777-7777-4777-8777-777777777777";
let fetchMock: Mock;
let putStatus = 200;
let revision = 3;

const view = () => ({
  vocabulary_version: "v1", revision,
  columns: [
    { column: "email_addr", suggested_label: "EMAIL", reason_codes: ["NAME_HINT"], confidence: 0.8, source: "EVIDENCE", protected: true, confirmed: null },
    { column: "fare", suggested_label: "MONEY", reason_codes: ["NUMERIC"], confidence: 0.6, source: "EVIDENCE", protected: false, confirmed: null },
  ],
});
const calls = (frag: string, method: string) => fetchMock.mock.calls.filter(([u, o]) => String(u).includes(frag) && (o?.method ?? "GET") === method);

beforeEach(() => {
  putStatus = 200;
  revision = 3;
  fetchMock = vi.fn((url: string, opts?: RequestInit) => {
    const m = opts?.method ?? "GET";
    if (url.includes("/auth/me")) return Promise.resolve(json(200, { user_id: "u", tenant_id: "t", email: "a@b.c", role: "DATA_OWNER" }));
    if (url.includes("/semantics/infer"))
      return Promise.resolve(json(200, { candidates: [{ column: "fare", label: "QUANTITY", reason_codes: [], source: "LOCAL" }], rejected: 0, provenance: { provider: "LOCAL", profile: { mode: "SAMPLE" } } }));
    if (url.includes("/semantics") && m === "PUT") {
      if (putStatus === 409) { revision = 4; return Promise.resolve(json(409, { title: "c", status: 409, error_code: "SEMANTIC_REVISION_CONFLICT" })); }
      if (putStatus === 403) return Promise.resolve(json(403, { title: "f", status: 403, error_code: "FORBIDDEN" }));
      return Promise.resolve(json(200, { revision: 4, changed: 1 }));
    }
    if (url.includes("/semantics")) return Promise.resolve(json(200, view()));
    return Promise.resolve(json(404, {}));
  });
  vi.stubGlobal("fetch", fetchMock);
  session.set({ access_token: "t", token_type: "bearer", expires_in: 3600, refresh_token: "r" }, "a@b.c");
});
afterEach(() => { session.clear(); vi.unstubAllGlobals(); });

it("never infers on mount; suggestion only stages, confirm sends expected revision and reason", async () => {
  renderRoute(<SemanticPanel snapshotId={ID} />, "/x", "/x");
  await screen.findByText("fare");
  expect(calls("/semantics/infer", "POST")).toHaveLength(0);
  await userEvent.click(await screen.findByRole("button", { name: /suggest labels/i }));
  await userEvent.click(await screen.findByRole("button", { name: /use suggestion/i }));
  expect(calls("/semantics", "PUT")).toHaveLength(0);
  const confirm = screen.getByRole("button", { name: /confirm 1 changes/i });
  expect(confirm).toBeDisabled();
  await userEvent.type(screen.getByLabelText(/confirmation reason/i), "checked");
  await userEvent.click(confirm);
  await waitFor(() => expect(calls("/semantics", "PUT")).toHaveLength(1));
  expect(JSON.parse(calls("/semantics", "PUT")[0][1].body)).toEqual({ expected_revision: 3, reason: "checked", changes: [{ column: "fare", label: "QUANTITY" }] });
});

it("on revision conflict refetches and keeps staged edits visible", async () => {
  putStatus = 409;
  renderRoute(<SemanticPanel snapshotId={ID} />, "/x", "/x");
  await screen.findByText("fare");
  await userEvent.selectOptions(screen.getByLabelText(/confirmed label: fare/i), "BOOLEAN");
  await userEvent.type(screen.getByLabelText(/confirmation reason/i), "r");
  await userEvent.click(screen.getByRole("button", { name: /confirm 1 changes/i }));
  expect(await screen.findByText(/changed by someone else/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/confirmed label: fare/i)).toHaveValue("BOOLEAN");
  await waitFor(() => expect(calls("/semantics", "GET").length).toBeGreaterThan(1));
});

it("flags protected columns as API-ineligible", async () => {
  renderRoute(<SemanticPanel snapshotId={ID} />, "/x", "/x");
  expect(await screen.findByText(/never sent to API/i)).toBeInTheDocument();
});

it.each(["mode", "provider"])("aborts a deferred inference and ignores its late result when the %s changes", async (selection) => {
  const original = fetchMock.getMockImplementation()!;
  const { promise: pending, resolve: release } = Promise.withResolvers<Response>();
  let signal: AbortSignal | null | undefined;
  fetchMock.mockImplementation((url: string, opts?: RequestInit) => {
    if (url.includes("/semantics/infer")) {
      signal = opts?.signal;
      return pending;
    }
    return original(url, opts);
  });
  renderRoute(<SemanticPanel snapshotId={ID} />, "/x", "/x");
  await userEvent.click(await screen.findByRole("button", { name: /suggest labels/i }));
  await waitFor(() => expect(signal).toBeDefined());
  if (selection === "mode") {
    await userEvent.selectOptions(screen.getByLabelText(/profile mode/i), "FULL");
  } else {
    await userEvent.click(screen.getByRole("radio", { name: /API/i }));
  }
  expect(signal?.aborted).toBe(true);
  const response = json(200, { candidates: [{ column: "fare", label: "QUANTITY", reason_codes: [], source: "LOCAL" }], rejected: 0, provenance: { provider: "LOCAL", profile: { mode: "SAMPLE" } } });
  const readJson = response.json.bind(response);
  const { promise: processed, resolve: bodyRead } = Promise.withResolvers<void>();
  vi.spyOn(response, "json").mockImplementation(async () => {
    const body = await readJson();
    bodyRead();
    return body;
  });
  await act(async () => {
    release(response);
    await processed;
    // Drain API/mutation continuations and React Query's scheduled notifications.
    const firstTurn = Promise.withResolvers<void>();
    setTimeout(firstTurn.resolve, 0);
    await firstTurn.promise;
    const notifications = Promise.withResolvers<void>();
    setTimeout(notifications.resolve, 0);
    await notifications.promise;
  });
  expect(screen.queryByRole("button", { name: /use suggestion/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("turns the panel read-only when confirm returns 403", async () => {
  putStatus = 403;
  renderRoute(<SemanticPanel snapshotId={ID} />, "/x", "/x");
  await screen.findByText("fare");
  await userEvent.selectOptions(screen.getByLabelText(/confirmed label: fare/i), "BOOLEAN");
  await userEvent.type(screen.getByLabelText(/confirmation reason/i), "checked");
  await userEvent.click(screen.getByRole("button", { name: /confirm 1 changes/i }));
  expect(await screen.findByText(/read-only/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/confirmed label: fare/i)).toBeDisabled();
});
