import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, renderRoute } from "../../test/render";
import { LoginPage } from "./LoginPage";

const LOCKED = {
  type: "urn:dq-scoring:error:423", title: "Account locked", status: 423,
  reason: "TOO_MANY_FAILED_ATTEMPTS", max_failed_attempts: 5,
  locked_until: "2026-10-08T10:15:00Z", retry_after_seconds: 900,
};

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function signIn(email: string, password: string) {
  const user = userEvent.setup(vi.isFakeTimers() ? { advanceTimers: (ms) => vi.advanceTimersByTimeAsync(ms) } : {});
  renderRoute(<LoginPage />, "/login", "/login");
  await user.type(screen.getByLabelText("Email"), email);
  await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("login lockout", () => {
  it("shows the lockout box with user name, timer and reason on 423", async () => {
    fetchMock.mockResolvedValue(json(423, LOCKED));
    await signIn("alice@example.com", "wrong");
    const box = await screen.findByRole("dialog");
    expect(within(box).getByText("alice@example.com")).toBeInTheDocument();
    expect(within(box).getByRole("timer")).toHaveTextContent("15:00");
    expect(within(box).getByText(/5 failed sign-in attempts in a row/)).toBeInTheDocument();
    expect(screen.queryByText(/is not valid/)).not.toBeInTheDocument();
    expect(box.closest("form")).toBeNull();
  });

  it("shows a generic reason and a fallback timer when the 423 body has no lock details", async () => {
    fetchMock.mockResolvedValue(json(423, { status: 423, title: "Account locked" }));
    await signIn("alice@example.com", "wrong");
    const box = await screen.findByRole("dialog");
    expect(within(box).getByText("Too many failed sign-in attempts.")).toBeInTheDocument();
    expect(within(box).getByRole("timer")).toHaveTextContent("01:00");
    expect(box.textContent).not.toMatch(/\b0 failed/);
  });

  it("counts down and closes when the lock expires", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fetchMock.mockResolvedValue(json(423, { ...LOCKED, retry_after_seconds: 3 }));
    await signIn("alice@example.com", "wrong");
    expect(await screen.findByRole("timer")).toHaveTextContent("00:03");
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(screen.getByRole("timer")).toHaveTextContent("00:02");
    await act(() => vi.advanceTimersByTimeAsync(2000));
    // react-query notifies observers on a (faked) setTimeout(0), so the unmount lands just after the tick.
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("keeps the generic message for 401", async () => {
    fetchMock.mockResolvedValue(json(401, { status: 401, title: "Unauthorized" }));
    await signIn("alice@example.com", "wrong");
    expect(await screen.findByText(/is not valid/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
