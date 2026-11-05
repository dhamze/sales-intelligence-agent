import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRouter, RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { meQuery } from "@/features/auth/api";
import { ApiError } from "@/lib/api/client";
import { initMonitoring, reportError } from "@/lib/monitoring";
import { routeTree } from "./routeTree.gen";
import "./styles.css";

/** A request failed because the session ended (expired, revoked, logged out elsewhere). */
function onError(error: unknown): void {
  if (
    error instanceof ApiError &&
    error.status === 401 &&
    router.state.location.pathname !== "/login"
  ) {
    queryClient.clear();
    queryClient.setQueryData(meQuery.queryKey, null);
    void router.navigate({ to: "/login", search: { expired: true } });
  }
}

const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError }),
  mutationCache: new MutationCache({ onError }),
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // Don't retry client errors (4xx): they won't fix themselves.
      retry: (count, error) =>
        !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
    },
  },
});

const router = createRouter({
  routeTree,
  context: { queryClient },
  defaultPreload: "intent",
  defaultPreloadStaleTime: 0, // TanStack Query owns caching
  scrollRestoration: true,
  // Errors shown by a route's error screen never reach the global handlers: report them here.
  defaultOnCatch: reportError,
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

initMonitoring();

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root element");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
