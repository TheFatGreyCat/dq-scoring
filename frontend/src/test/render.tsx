import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { I18nProvider, type Language } from "../lib/i18n";
import "../lib/surfaceTranslations";

export const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** Render a page at `url`, matched by `path`, with a fresh no-retry QueryClient and I18nProvider. */
export function renderRoute(
  element: ReactNode,
  path: string,
  url: string,
  options?: { lang?: Language },
) {
  const chosenLang = options?.lang ?? "en";
  try {
    localStorage.setItem("dq_language", chosenLang);
  } catch {
    // ignore
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path, element },
      { path: "*", element: <p>navigated</p> },
    ],
    { initialEntries: [url] },
  );
  return {
    ...render(
      <I18nProvider>
        <QueryClientProvider client={client}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </I18nProvider>,
    ),
    router,
  };
}
