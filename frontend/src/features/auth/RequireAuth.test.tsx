import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider, useLocation } from "react-router";
import { RequireAuth } from "./RequireAuth";

vi.mock("./useSession", () => ({ useSession: () => ({ authenticated: false }) }));

function LoginDestination() {
  const location = useLocation();
  return <output>{location.state?.from}</output>;
}

it("keeps collection filters and import resume state across the login redirect", async () => {
  const router = createMemoryRouter([
    { path: "/assets", element: <RequireAuth /> },
    { path: "/login", element: <LoginDestination /> },
  ], { initialEntries: ["/assets?format=CSV&import=synthetic-upload#preview"] });
  render(<RouterProvider router={router} />);
  expect(await screen.findByText("/assets?format=CSV&import=synthetic-upload#preview")).toBeInTheDocument();
});
