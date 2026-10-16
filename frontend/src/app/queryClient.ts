import { QueryClient } from "@tanstack/react-query";
import type { ApiError } from "../api/client";

/** Retry transport hiccups and 5xx only; 4xx are definitive answers. */
const MAX_QUERY_RETRIES = 2;

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, error) =>
        count < MAX_QUERY_RETRIES && !((error as ApiError).status != null && (error as ApiError).status! < 500),
      refetchOnWindowFocus: true,
    },
    mutations: { retry: false },
  },
});
