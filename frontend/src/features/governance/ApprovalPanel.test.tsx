import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi, type Mock } from "vitest";
import { session } from "../../api/client";
import { json, renderRoute } from "../../test/render";
import { ApprovalPanel } from "./ApprovalPanel";

const ID = "88888888-8888-4888-8888-888888888888";
type Rev = { ruleset_id: string; name: string; status: "PENDING_APPROVAL" | "ACTIVE"; current_version: number; can_self_approve?: boolean };
let fetchMock: Mock;
let eligible = true;

const revision = (over: Partial<Rev> = {}): Rev => ({ ruleset_id: ID, name: "R1", status: "PENDING_APPROVAL", current_version: 1, can_self_approve: eligible, ...over });
const approveCalls = () => fetchMock.mock.calls.filter(([u]) => String(u).endsWith(`/rulesets/${ID}/approve`));

function renderPanel(selected: Rev = revision()) {
  renderRoute(
    <ApprovalPanel<Rev> kind="rulesets" recentKind="ruleset" idOf={(r) => r.ruleset_id} noun="Ruleset" selectedEntity={selected} />,
    "/x",
    "/x",
  );
}

beforeEach(() => {
  eligible = true;
  fetchMock = vi.fn((url: string, opts?: RequestInit) => {
    if (String(url).endsWith(`/rulesets/${ID}/approve`) && opts?.method === "POST") {
      const body = JSON.parse(String(opts.body));
      if (!body.self_approval_reason) return Promise.resolve(json(403, { title: "Forbidden", status: 403, detail: "Independent approval violation" }));
      return Promise.resolve(json(200, revision({ status: "ACTIVE", can_self_approve: false })));
    }
    return Promise.resolve(json(404, {}));
  });
  vi.stubGlobal("fetch", fetchMock);
  session.set({ access_token: "t", token_type: "bearer", expires_in: 3600, refresh_token: "r" }, "a@b.c");
});
afterEach(() => { session.clear(); vi.unstubAllGlobals(); });

it("offers no self-approval unless the server says the caller is eligible, and plain Approve stays disabled-free", async () => {
  eligible = false;
  renderPanel();
  expect(await screen.findByRole("button", { name: /^approve$/i })).toBeEnabled();
  expect(screen.queryByRole("button", { name: /self-approve/i })).not.toBeInTheDocument();
});

it("eligible admin cannot use the ordinary Approve button; self-approval needs an explicit reason and sends it", async () => {
  renderPanel();
  expect(await screen.findByRole("button", { name: /^approve$/i })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: /self-approve/i }));

  const confirm = await screen.findByRole("button", { name: /confirm self-approval/i });
  expect(confirm).toBeDisabled();
  await userEvent.type(screen.getByRole("textbox", { name: /reason/i }), "   ");
  expect(confirm).toBeDisabled();
  expect(approveCalls()).toHaveLength(0);

  await userEvent.type(screen.getByRole("textbox", { name: /reason/i }), "Sole admin, reviewed");
  await userEvent.click(confirm);

  await waitFor(() => expect(approveCalls()).toHaveLength(1));
  expect(JSON.parse(String(approveCalls()[0][1].body))).toMatchObject({ self_approval_reason: "Sole admin, reviewed" });
  const stages = await screen.findByRole("list", { name: /approval stage/i });
  await waitFor(() => expect(within(stages).getByRole("listitem", { current: "step" })).toHaveTextContent(/active/i));
  expect(screen.queryByRole("button", { name: /self-approve/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("does not apply a delayed approval response to a newly selected revision", async () => {
  let resolveResponse!: (response: Response) => void;
  fetchMock.mockImplementation(() => new Promise<Response>((resolve) => { resolveResponse = resolve; }));
  renderPanel();
  await userEvent.click(await screen.findByRole("button", { name: /self-approve/i }));
  await userEvent.type(screen.getByRole("textbox", { name: /reason/i }), "Reviewed A");
  await userEvent.click(screen.getByRole("button", { name: /confirm self-approval/i }));
  const otherId = "99999999-9999-4999-8999-999999999999";
  await userEvent.clear(screen.getByLabelText("Ruleset ID"));
  await userEvent.type(screen.getByLabelText("Ruleset ID"), otherId);
  resolveResponse(json(200, revision({ status: "ACTIVE", can_self_approve: false })));
  await waitFor(() => expect(screen.getByRole("button", { name: /^approve$/i })).toBeEnabled());
  expect(screen.getByLabelText("Ruleset ID")).toHaveValue(otherId);
  expect(document.querySelector('[aria-current="step"]')).toBeNull();
});
